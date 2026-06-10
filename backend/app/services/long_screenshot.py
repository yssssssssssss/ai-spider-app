import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageStat

SAFE_SWIPE_START_RATIO = 0.70
SAFE_SWIPE_END_RATIO = 0.28


@dataclass(frozen=True)
class StitchResult:
    output_path: str
    input_paths: list[str]
    crop_tops: list[int]
    width: int
    height: int


@dataclass(frozen=True)
class CaptureResult:
    raw_paths: list[str]
    stitched_path: str
    stitch: StitchResult


def _average_delta(left: Image.Image, right: Image.Image) -> float:
    left_rgb = left.convert("RGB")
    right_rgb = right.convert("RGB")
    diff = ImageChops.difference(left_rgb, right_rgb)
    try:
        stat = ImageStat.Stat(diff)
        return sum(stat.mean)
    finally:
        diff.close()
        left_rgb.close()
        right_rgb.close()


def _row_fingerprints(image: Image.Image) -> list[bytes]:
    width = min(image.width, 96)
    converted = image.convert("RGB")
    comparable = converted
    if converted.width != width:
        comparable = converted.resize((width, converted.height), Image.Resampling.BILINEAR)
    try:
        row_stride = comparable.width * len(comparable.getbands())
        data = comparable.tobytes()
        return [data[y * row_stride:(y + 1) * row_stride] for y in range(comparable.height)]
    finally:
        if comparable is not converted:
            comparable.close()
        converted.close()


def find_vertical_overlap(
    previous: Image.Image,
    current: Image.Image,
    *,
    min_overlap: int = 80,
    max_average_delta: float = 0.5,
) -> int:
    if previous.width != current.width:
        raise ValueError("Images must have the same width")

    max_overlap = min(previous.height, current.height)
    if max_overlap < min_overlap:
        return 0

    previous_rows = _row_fingerprints(previous)
    current_rows = _row_fingerprints(current)
    for overlap in range(max_overlap, min_overlap - 1, -1):
        if previous_rows[-overlap] != current_rows[0]:
            continue
        if previous_rows[-1] != current_rows[overlap - 1]:
            continue
        previous_tail = previous.crop((0, previous.height - overlap, previous.width, previous.height))
        current_head = current.crop((0, 0, current.width, overlap))
        try:
            if _average_delta(previous_tail, current_head) <= max_average_delta:
                return overlap
        finally:
            previous_tail.close()
            current_head.close()
    return 0


def stitch_images(
    image_paths: Sequence[str],
    output_path: str,
    *,
    min_overlap: int = 80,
    max_average_delta: float = 0.5,
) -> StitchResult:
    if not image_paths:
        raise ValueError("At least one image is required")

    frames: list[Image.Image] = []
    cropped_parts: list[Image.Image] = []
    crop_tops: list[int] = []
    try:
        for index, image_path in enumerate(image_paths):
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
            if frames and image.width != frames[0].width:
                raise ValueError("Images must have the same width")
            if index == 0:
                crop_top = 0
            else:
                crop_top = find_vertical_overlap(
                    frames[-1],
                    image,
                    min_overlap=min_overlap,
                    max_average_delta=max_average_delta,
                )
            frames.append(image)
            crop_tops.append(crop_top)

        width = frames[0].width
        cropped_parts = [
            frame.crop((0, min(crop_top, frame.height), frame.width, frame.height))
            for frame, crop_top in zip(frames, crop_tops)
            if min(crop_top, frame.height) < frame.height
        ]
        if not cropped_parts:
            raise ValueError("All images were cropped away")

        height = sum(part.height for part in cropped_parts)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        stitched = Image.new("RGB", (width, height))
        try:
            offset = 0
            for part in cropped_parts:
                stitched.paste(part, (0, offset))
                offset += part.height
            stitched.save(output)
        finally:
            stitched.close()
        return StitchResult(
            output_path=str(output),
            input_paths=[str(path) for path in image_paths],
            crop_tops=crop_tops,
            width=width,
            height=height,
        )
    finally:
        for part in cropped_parts:
            part.close()
        for frame in frames:
            frame.close()


def _adb_command(device_id: str | None, *args: str) -> list[str]:
    command = ["adb"]
    if device_id:
        command.extend(["-s", device_id])
    command.extend(args)
    return command


def _run_adb(device_id: str | None, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    result = subprocess.run(
        _adb_command(device_id, *args),
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(stderr or f"adb command failed: {' '.join(args)}")
    return result


def _device_size(device_id: str | None) -> tuple[int, int]:
    result = _run_adb(device_id, "shell", "wm", "size")
    text = result.stdout.decode("utf-8", errors="ignore")
    match = re.search(r"(\d+)x(\d+)", text)
    if not match:
        return 1080, 2400
    return int(match.group(1)), int(match.group(2))


def _capture_screen(device_id: str | None, output_path: str) -> str:
    result = _run_adb(device_id, "exec-out", "screencap", "-p", timeout=20)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.stdout)
    return str(output)


def _safe_swipe_points(width: int, height: int) -> tuple[int, int, int, int]:
    x = width // 2
    return x, int(height * SAFE_SWIPE_START_RATIO), x, int(height * SAFE_SWIPE_END_RATIO)


def _swipe_one_screen(device_id: str | None, width: int, height: int) -> None:
    start_x, start_y, end_x, end_y = _safe_swipe_points(width, height)
    _run_adb(
        device_id,
        "shell",
        "input",
        "swipe",
        str(start_x),
        str(start_y),
        str(end_x),
        str(end_y),
        "650",
    )


def capture_product_detail_long_image(
    *,
    device_id: str | None,
    output_dir: str,
    screen_count: int = 10,
    wait_seconds: float = 1.2,
    min_overlap: int = 80,
) -> CaptureResult:
    if screen_count < 1:
        raise ValueError("screen_count must be at least 1")

    capture_dir = Path(output_dir) / "product_detail_long"
    raw_dir = capture_dir / "raw"
    stitched_path = capture_dir / "stitched_product_detail.png"
    raw_dir.mkdir(parents=True, exist_ok=True)

    width, height = _device_size(device_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_paths: list[str] = []
    for index in range(screen_count):
        if index > 0:
            _swipe_one_screen(device_id, width, height)
            time.sleep(wait_seconds)
        raw_path = raw_dir / f"detail_screen_{index + 1:02d}_{timestamp}.png"
        raw_paths.append(_capture_screen(device_id, str(raw_path)))

    stitch = stitch_images(raw_paths, str(stitched_path), min_overlap=min_overlap)
    return CaptureResult(raw_paths=raw_paths, stitched_path=str(stitched_path), stitch=stitch)
