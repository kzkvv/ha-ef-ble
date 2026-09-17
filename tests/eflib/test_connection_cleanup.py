import asyncio
import contextlib
import socket
from unittest.mock import AsyncMock, Mock

import pytest
from bleak.backends.device import BLEDevice

from custom_components.ef_ble.eflib import connection as connection_module
from custom_components.ef_ble.eflib.connection import Connection, ConnectionState


@pytest.fixture
def connection():
    return Connection(
        BLEDevice("AA:BB:CC:DD:EE:FF", "Test device", {}),
        "TEST_SERIAL",
        "TEST_USER",
        AsyncMock(),
        AsyncMock(),
    )


@pytest.fixture
def transport_client():
    sockets = []

    def create(*, connected=False):
        transport, peer = socket.socketpair()
        sockets.extend((transport, peer))
        client = Mock(is_connected=connected)

        async def disconnect():
            client.is_connected = False
            transport.close()

        client.disconnect = AsyncMock(side_effect=disconnect)
        return client, transport

    yield create
    for sock in sockets:
        sock.close()


@pytest.mark.parametrize("retry", [False, True])
async def test_remote_drop_closes_transport(connection, transport_client, retry):
    client, transport = transport_client()
    connection._client = client
    connection._set_state(ConnectionState.AUTHENTICATED)
    connection._retry_on_disconnect = retry

    try:
        connection.disconnected(client)
        await connection._disconnect_client()

        client.disconnect.assert_awaited_once()
        assert transport.fileno() == -1
        assert connection._client is None
        assert (connection._reconnect_task is not None) == retry
    finally:
        await connection.disconnect()


@pytest.mark.parametrize("connected", [False, True])
async def test_explicit_disconnect_closes_transport(
    connection, transport_client, connected
):
    client, transport = transport_client(connected=connected)
    connection._client = client

    await connection.disconnect()

    client.disconnect.assert_awaited_once()
    assert transport.fileno() == -1
    assert connection._client is None
    assert connection._state == ConnectionState.DISCONNECTED


async def test_repeated_drops_do_not_accumulate_transports(
    connection, transport_client
):
    for _ in range(100):
        client, transport = transport_client()
        connection._client = client
        connection._set_state(ConnectionState.AUTHENTICATED)

        connection.disconnected(client)
        await connection._disconnect_client()

        assert transport.fileno() == -1
        client.disconnect.assert_awaited_once()


async def test_connect_waits_for_old_transport_cleanup(
    connection, transport_client, monkeypatch
):
    old_client, old_transport = transport_client()
    new_client, new_transport = transport_client(connected=True)
    connection._client = old_client

    async def establish(*args, **kwargs):
        assert old_transport.fileno() == -1
        return new_client

    monkeypatch.setattr(connection_module, "establish_connection", establish)
    monkeypatch.setattr(
        connection_module, "close_stale_connections_by_address", AsyncMock()
    )
    monkeypatch.setattr(connection, "_validate_characteristics", Mock())
    monkeypatch.setattr(connection, "_start_notify", AsyncMock())
    monkeypatch.setattr(connection, "_reset_assemblers", Mock())
    monkeypatch.setattr(connection, "_run_auth", AsyncMock())

    try:
        await connection.connect()
        assert connection._client is new_client
        assert new_transport.fileno() != -1
        old_client.disconnect.assert_awaited_once()
    finally:
        await connection.disconnect()


async def test_late_callback_leaves_new_client_untouched(connection, transport_client):
    old_client, _ = transport_client()
    new_client, transport = transport_client(connected=True)
    connection._client = new_client
    connection._set_state(ConnectionState.AUTHENTICATED)
    inbox = connection._inbox = asyncio.Queue()

    try:
        connection.disconnected(old_client)

        assert connection._client is new_client
        assert connection._state == ConnectionState.AUTHENTICATED
        assert connection._inbox is inbox
        assert transport.fileno() != -1
        new_client.disconnect.assert_not_awaited()
    finally:
        await connection.disconnect()


async def test_retry_connector_keeps_ownership_during_establishment(
    connection, transport_client
):
    client, _ = transport_client()
    connection._set_state(ConnectionState.ESTABLISHING_CONNECTION)

    connection.disconnected(client)
    await asyncio.sleep(0)

    assert connection._state == ConnectionState.ESTABLISHING_CONNECTION
    client.disconnect.assert_not_awaited()


async def test_cleanup_survives_cancelled_waiter(connection, transport_client):
    client, transport = transport_client()
    connection._client = client
    started = asyncio.Event()
    release = asyncio.Event()

    async def disconnect():
        started.set()
        await release.wait()
        transport.close()

    client.disconnect.side_effect = disconnect
    waiter = asyncio.create_task(connection._disconnect_client())
    try:
        await asyncio.wait_for(started.wait(), 1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await connection.disconnect()
        assert transport.fileno() == -1
        client.disconnect.assert_awaited_once()
    finally:
        release.set()
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter


async def test_unload_waits_for_callback_cleanup(connection, transport_client):
    client, transport = transport_client()
    connection._client = client
    connection._set_state(ConnectionState.AUTHENTICATED)
    started = asyncio.Event()
    release = asyncio.Event()

    async def disconnect():
        started.set()
        await release.wait()
        transport.close()

    client.disconnect.side_effect = disconnect
    unload = None
    try:
        connection.disconnected(client)
        await asyncio.wait_for(started.wait(), 1)
        unload = asyncio.create_task(connection.disconnect())
        await asyncio.sleep(0)
        assert not unload.done()
        release.set()
        await unload
        assert transport.fileno() == -1
        client.disconnect.assert_awaited_once()
    finally:
        release.set()
        if unload is not None:
            await unload


async def test_auth_cancellation_does_not_interrupt_cleanup(
    connection, transport_client
):
    client, transport = transport_client(connected=True)
    connection._client = client
    connection._set_state(ConnectionState.AUTHENTICATED)

    async def disconnect():
        client.is_connected = False
        connection.disconnected(client)
        await asyncio.sleep(0)
        transport.close()

    client.disconnect.side_effect = disconnect
    auth = connection._auth_task = asyncio.create_task(connection._disconnect_client())
    with pytest.raises(asyncio.CancelledError):
        await auth
    await connection.disconnect()

    assert transport.fileno() == -1
    client.disconnect.assert_awaited_once()


async def test_disconnect_timeout_remains_bounded(
    connection, transport_client, monkeypatch
):
    client, _ = transport_client()
    connection._client = client
    client.disconnect.side_effect = asyncio.Event().wait
    monkeypatch.setattr(connection_module, "DISCONNECT_TIMEOUT", 0.01)

    await asyncio.wait_for(connection.disconnect(), 1)

    assert connection._client is None
    assert connection.disconnect_log[-1]["outcome"] == "timeout"
