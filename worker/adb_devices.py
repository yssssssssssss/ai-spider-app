from __future__ import annotations

import shutil
import subprocess


def list_adb_devices() -> list[dict[str, str]]:
    if not shutil.which("adb"):
        print("⚠️ 未找到 adb，本地 worker 暂无可上报设备")
        return []

    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        print(f"⚠️ adb devices 执行失败: {exc}")
        return []

    if result.returncode != 0:
        print(f"⚠️ adb devices 返回失败: {result.stderr.strip()}")
        return []

    devices: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        serial, adb_state = parts[0], parts[1]
        devices.append(
            {
                "serial": serial,
                "name": serial,
                "status": "online" if adb_state == "device" else "offline",
                "notes": adb_state,
            }
        )
    return devices
