"""Build deterministic integration archive from tracked source files"""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "custom_components/ef_ble"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def build() -> None:
    manifest = json.loads((ROOT / COMPONENT / "manifest.json").read_text())
    files = git("ls-files", "-z", "--", COMPONENT).split("\0")
    entries = {name: (ROOT / name).read_bytes() for name in files if name}
    entries[f"{COMPONENT}/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    entries[f"{COMPONENT}/FORK_BUILD.json"] = (
        json.dumps(
            {
                "version": manifest["version"],
                "commit": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
                "source": "https://github.com/kzkvv/ha-ef-ble",
                "modified": {
                    "eflib/connection.py": "Close BLE clients after remote drops; preserve cleanup through cancellation",
                    "manifest.json": "Identify fork release",
                },
            },
            indent=2,
        )
        + "\n"
    ).encode()

    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "ef_ble.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for name, contents in sorted(entries.items()):
            info = ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            bundle.writestr(info, contents)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Built {archive}: {manifest['version']} ({len(entries)} files)")  # noqa: T201


if __name__ == "__main__":
    build()
