#!/usr/bin/env python3
"""Generate MediaMTX config and update cameras.json from ipcam_config.json.

Writes:
 - docker/mediamtx.yml    (MediaMTX config with paths -> original RTSP sources)
 - config/cameras.json    (converted cameras.json pointing to mediamtx RTSP endpoints)

Run this before `docker compose up` so the mediamtx service and app see the same streams.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IPCAM = ROOT / "config" / "ipcam_config.json"
MEDIAMTX_YAML = ROOT / "docker" / "mediamtx.yml"
CAMERAS_JSON = ROOT / "config" / "cameras.json"


def sanitize_id(i: int) -> str:
    return f"cam{(i+1):02d}"


def normalize_source(source: str) -> str:
    source = source.strip()
    if source.isdigit():
        return f"/dev/video{int(source)}"
    if source.startswith("/dev/video"):
        return source
    return source


def is_usb_source(source: str) -> bool:
    source = source.strip()
    return source.isdigit() or source.startswith("/dev/video")


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main():
    if not IPCAM.exists():
        print(f"No {IPCAM}, nothing to do.")
        return

    data = json.loads(IPCAM.read_text())
    streams = data.get("sources", None)
    if streams is None:
        streams = data.get("rtsp_streams", [])
    names = data.get("camera_names", [])

    # Build mediamtx YAML (paths -> source)
    paths = {}
    cameras_out = {"cameras": []}
    yaml_lines = ["paths:"]
    for i, src in enumerate(streams):
        cam_id = sanitize_id(i)
        path_name = cam_id
        src_value = normalize_source(str(src))
        if is_usb_source(str(src)):
            paths[path_name] = {}
            yaml_lines.append(f"  {path_name}:")
            yaml_lines.append(f"    source: {yaml_quote(src_value)}")
        else:
            paths[path_name] = {"source": src_value}
            yaml_lines.append(f"  {path_name}:")
            yaml_lines.append(f"    source: {yaml_quote(src_value)}")

        cam_name = names[i] if i < len(names) else cam_id
        mediamtx_rtsp = f"rtsp://mediamtx:8554/{path_name}"
        cameras_out["cameras"].append({
            "id": cam_id,
            "name": cam_name,
            "location": "IPCam",
            "rtsp": mediamtx_rtsp,
        })

    MEDIAMTX_YAML.parent.mkdir(parents=True, exist_ok=True)
    MEDIAMTX_YAML.write_text("\n".join(yaml_lines) + "\n")
    CAMERAS_JSON.write_text(json.dumps(cameras_out, indent=4))

    print(f"Wrote mediamtx config: {MEDIAMTX_YAML}")
    print(f"Wrote cameras.json for app: {CAMERAS_JSON}")


if __name__ == "__main__":
    main()
