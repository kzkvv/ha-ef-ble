import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bleak import BleakClient
from bleak.backends.device import BLEDevice

from custom_components.ef_ble.eflib.connection import Connection, ConnectionState

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("dbus-daemon") is None,
    reason="Requires Linux and dbus-daemon",
)


@pytest.fixture
def private_bus():
    with subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    ) as daemon:
        try:
            yield daemon.stdout.readline().strip()
        finally:
            daemon.terminate()
            daemon.wait(timeout=5)


async def test_real_dbus_connections_released_after_repeated_drops(private_bus):
    # Real BlueZ backend and D-Bus sockets; only the radio disconnect is simulated.
    from bleak.backends.bluezdbus.client import (  # noqa: PLC0415 - Linux only
        BleakClientBlueZDBus,
    )
    from dbus_fast.aio import MessageBus  # noqa: PLC0415 - Linux only

    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Test device", {"path": "/test/device"})
    connection = Connection(
        device, "TEST_SERIAL", "TEST_USER", AsyncMock(), AsyncMock()
    )
    buses = []
    baseline = len(list(Path("/proc/self/fd").iterdir()))
    try:
        for _ in range(100):
            bus = await MessageBus(bus_address=private_bus).connect()
            buses.append(bus)
            client = BleakClient(
                device,
                backend=BleakClientBlueZDBus,
                disconnected_callback=connection.disconnected,
            )
            backend = client._backend
            backend._bus = bus
            connection._client = client
            connection._set_state(ConnectionState.AUTHENTICATED)

            # Same sequence as BlueZ's unsolicited-disconnect signal handler.
            backend._is_connected = False
            backend._cleanup_all()
            backend._disconnected_callback()
            await connection._disconnect_client()

            assert not bus.connected
            assert backend._bus is None

        await asyncio.sleep(0)
        assert len(list(Path("/proc/self/fd").iterdir())) == baseline
    finally:
        await connection.disconnect()
        for bus in buses:
            bus.disconnect()
            await bus.wait_for_disconnect()
