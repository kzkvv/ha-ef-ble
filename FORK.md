# EcoFlow BLE socket cleanup build

Fork of [rabits/ha-ef-ble](https://github.com/rabits/ha-ef-ble).
Preview version `1.1.3b1` adds cleanup for Bluetooth clients whose radio link already dropped.
Base: upstream `89fa21c`, containing 1.1.2 plus upstream PowerStream and Wave 3 fixes.

## Fix

Bleak 3.0.2 can keep its D-Bus socket open after an unsolicited Bluetooth disconnect.
Previous integration code discarded that client and skipped cleanup when `is_connected` was false.
Repeated drops could exhaust D-Bus connection limits and prevent telemetry from recovering.

Cleanup now retains the old client, calls its public `disconnect()` method, and finishes before
another connection starts. Cleanup survives auth cancellation and integration unload. Late callbacks
from an old client cannot clear a newer connection. Existing five-second disconnect timeout remains.

## Install release

Download `ef_ble.zip` and `SHA256SUMS` from
[fork releases](https://github.com/kzkvv/ha-ef-ble/releases). No compilation needed on Home Assistant.
Archive contains `custom_components/ef_ble/`, including source revision and license.

1. Back up Home Assistant configuration and existing `custom_components/ef_ble` directory.
2. Verify downloaded archive: `sha256sum -c SHA256SUMS`.
3. Stop Home Assistant. Move existing `ef_ble` directory into the backup location.
4. Extract archive into Home Assistant's configuration directory, preserving file ownership.
5. Start Home Assistant and confirm integration version `1.1.3b1` and returning telemetry.

Existing integration entries and entity IDs stay in Home Assistant configuration. Keep those entries;
replace only component files. Loading changed Python code needs one restart. Recurring restarts
are not part of this fix.

For HACS-managed installations, register `https://github.com/kzkvv/ha-ef-ble` as an Integration
[custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) and select the fork release.
Enable beta versions if the preview release is hidden.
HACS installs from the release's source tag; attached ZIP supports manual installation.
Ensure only one repository manages domain `ef_ble`; upstream updates can overwrite a manual patch.
If HACS refuses the duplicate domain, use manual installation until repository ownership is switched.

Rollback: stop Home Assistant, restore backed-up component directory, then start Home Assistant.

## Build and verify locally

```sh
uv sync --group dev
uv run pytest tests/eflib
python scripts/build_release.py
```

Linux tests use a private `dbus-daemon`, real Bleak 3.0.2, and real D-Bus sockets. Radio drops are
simulated; 100 drops must leave zero additional open file descriptors. Other regression tests cover
reconnect ordering, unload, timeout, cancellation, and late callbacks. No physical Bluetooth device
or running Home Assistant is required. Live device recovery still needs validation after installation.

Build outputs: `dist/ef_ble.zip` and `dist/SHA256SUMS`. PR workflow also uploads these artifacts.
`FORK_BUILD.json` records source revision and whether tracked files differed during packaging.
Publish builds from a clean checkout; local builds with uncommitted changes are marked `dirty`.
