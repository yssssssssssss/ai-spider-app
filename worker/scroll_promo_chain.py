from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat, UnidentifiedImageError


@dataclass(frozen=True)
class ScrollPromoConfig:
    app_name: str
    package: str
    device_serial: str
    output_dir: Path
    swipe_count: int = 1
    max_frames: int = 6
    fps: int = 10
    swipe_duration_ms: int = 1000
    app_wait_seconds: float = 6.0


@dataclass(frozen=True)
class ScrollPromoResult:
    annotated_paths: list[Path]
    detections: list[dict]
    report_path: Path
    capture_method: str


class ScrollCapture(Protocol):
    method: str

    def open_app(self, package: str, device_serial: str, wait_seconds: float) -> None: ...
    def capture_swipe(self, config: ScrollPromoConfig, scratch_dir: Path) -> list[Path]: ...
    def close_app(self, package: str, device_serial: str) -> None: ...


class ScrcpyScrollCapture:
    """Capture a real swipe through scrcpy recording, with screencap fallback."""

    method = "scrcpy_recording"

    def __init__(self):
        self.last_method = self.method

    def _adb(self, serial: str, *args: str) -> list[str]:
        return ["adb", "-s", serial, *args]

    def open_app(self, package: str, device_serial: str, wait_seconds: float) -> None:
        subprocess.run(self._adb(device_serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP"), capture_output=True)
        subprocess.run(self._adb(device_serial, "shell", "wm", "dismiss-keyguard"), capture_output=True)
        subprocess.run(self._adb(device_serial, "shell", "input", "keyevent", "KEYCODE_HOME"), capture_output=True)
        time.sleep(0.5)
        subprocess.run(self._adb(device_serial, "shell", "am", "force-stop", package), capture_output=True)
        result = subprocess.run(
            self._adb(device_serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Unable to launch {package}")
        time.sleep(max(0.0, wait_seconds))
        foreground = subprocess.run(
            self._adb(device_serial, "shell", "dumpsys", "activity", "activities"),
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        if package not in foreground:
            raise RuntimeError(f"Target app is not foreground after launch: {package}")
        baseline = subprocess.run(
            self._adb(device_serial, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=10,
        )
        if baseline.returncode != 0 or self.is_blank_png(baseline.stdout):
            raise RuntimeError("Target app screen is blank or keyguard is still active")

    def is_blank_png(self, content: bytes) -> bool:
        try:
            with Image.open(BytesIO(content)).convert("L") as image:
                stat = ImageStat.Stat(image.resize((64, 64), Image.Resampling.BILINEAR))
                return stat.mean[0] < 3.0 and stat.var[0] < 3.0
        except (UnidentifiedImageError, OSError):
            return True

    def _usable_frames(self, frames: list[Path]) -> list[Path]:
        usable = [path for path in frames if not self.is_blank_png(path.read_bytes())]
        if not usable:
            raise RuntimeError("All captured swipe frames are blank")
        return usable

    def capture_swipe(self, config: ScrollPromoConfig, scratch_dir: Path) -> list[Path]:
        if shutil.which("scrcpy") and shutil.which("ffmpeg"):
            try:
                frames = self._capture_with_scrcpy(config, scratch_dir)
                self.last_method = "scrcpy_recording"
                return self._usable_frames(frames)
            except Exception as exc:
                print(f"⚠️ scrcpy 滑动录制失败，降级并发截图: {exc}")
        self.last_method = "concurrent_screencap"
        return self._usable_frames(self._capture_with_screencap(config, scratch_dir))

    def _capture_with_scrcpy(self, config: ScrollPromoConfig, scratch_dir: Path) -> list[Path]:
        video = scratch_dir / "scroll.mp4"
        log_path = scratch_dir / "scrcpy.log"
        record_seconds = max(3, int(config.swipe_duration_ms / 1000) + 3)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    "scrcpy", "-s", config.device_serial, "-N", "--no-audio", "--no-control",
                    "--max-fps=30", f"--time-limit={record_seconds}", f"--record={video}",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        time.sleep(1.0)
        if process.poll() is not None:
            raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
        self._swipe(config)
        process.wait(timeout=record_seconds + 8)
        if not video.exists() or video.stat().st_size == 0:
            raise RuntimeError("scrcpy recording is empty")
        pattern = str(scratch_dir / "candidate-%03d.png")
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", "0.70", "-t", f"{config.swipe_duration_ms / 1000 + 1.0:.2f}",
                "-i", str(video), "-vf", f"fps={max(1, config.fps)}", pattern,
            ],
            check=True,
            timeout=30,
        )
        frames = sorted(scratch_dir.glob("candidate-*.png"))
        if not frames:
            raise RuntimeError("No frames extracted from scrcpy recording")
        return frames

    def _capture_with_screencap(self, config: ScrollPromoConfig, scratch_dir: Path) -> list[Path]:
        swipe = subprocess.Popen(self._adb(config.device_serial, *self._swipe_args(config)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        frames: list[Path] = []
        done_at = None
        while True:
            result = subprocess.run(
                self._adb(config.device_serial, "exec-out", "screencap", "-p"),
                capture_output=True,
                timeout=8,
            )
            if result.returncode == 0 and result.stdout.startswith(b"\x89PNG"):
                path = scratch_dir / f"candidate-{len(frames) + 1:03d}.png"
                path.write_bytes(result.stdout)
                frames.append(path)
            if swipe.poll() is not None and done_at is None:
                done_at = time.monotonic()
            if done_at is not None and time.monotonic() - done_at >= 0.2:
                break
        swipe.wait()
        if not frames:
            raise RuntimeError("No frames captured during swipe")
        return frames

    def _swipe_args(self, config: ScrollPromoConfig) -> list[str]:
        return ["shell", "input", "swipe", "540", "1900", "540", "600", str(config.swipe_duration_ms)]

    def _swipe(self, config: ScrollPromoConfig) -> None:
        subprocess.run(self._adb(config.device_serial, *self._swipe_args(config)), check=True, timeout=10)

    def close_app(self, package: str, device_serial: str) -> None:
        subprocess.run(self._adb(device_serial, "shell", "am", "force-stop", package), capture_output=True, timeout=10)


class ScrollPromoChain:
    """Open, capture, detect, annotate and close behind one interface."""

    def __init__(self, *, capture: ScrollCapture | None = None, detect: Callable[[Path], dict]):
        self.capture = capture or ScrcpyScrollCapture()
        self.detect = detect

    def run(self, config: ScrollPromoConfig) -> ScrollPromoResult:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        scratch = config.output_dir.parent / f".scroll-promo-{uuid.uuid4().hex}"
        scratch.mkdir(parents=True, exist_ok=True)
        annotated_paths: list[Path] = []
        detections: list[dict] = []
        try:
            self.capture.open_app(config.package, config.device_serial, config.app_wait_seconds)
            for swipe_index in range(max(1, config.swipe_count)):
                swipe_scratch = scratch / f"swipe-{swipe_index + 1:02d}"
                swipe_scratch.mkdir(parents=True, exist_ok=True)
                candidates = self.capture.capture_swipe(config, swipe_scratch)
                selected = self._select_motion_frames(candidates, max(1, min(config.max_frames, 10)))
                for frame_index, frame in enumerate(selected, start=1):
                    detection = dict(self.detect(frame))
                    detection.update({
                        "swipe_index": swipe_index + 1,
                        "frame_index": frame_index,
                        "source_frame": frame.name,
                    })
                    output = config.output_dir / f"swipe_{swipe_index + 1:02d}_frame_{frame_index:02d}_{detection.get('promo_state', 'unknown')}.png"
                    self._annotate(frame, output, detection)
                    detection["annotated_file"] = output.name
                    annotated_paths.append(output)
                    detections.append(detection)
        finally:
            self.capture.close_app(config.package, config.device_serial)
            shutil.rmtree(scratch, ignore_errors=True)

        method = getattr(self.capture, "last_method", getattr(self.capture, "method", "unknown"))
        report = {
            "app_name": config.app_name,
            "package": config.package,
            "device_serial": config.device_serial,
            "capture_method": method,
            "swipe_count": config.swipe_count,
            "max_frames_per_swipe": config.max_frames,
            "selected_frame_count": len(annotated_paths),
            "detections": detections,
        }
        report_path = config.output_dir / "promotion_detections.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return ScrollPromoResult(annotated_paths, detections, report_path, method)

    def _select_motion_frames(self, frames: list[Path], max_frames: int) -> list[Path]:
        if len(frames) <= max_frames:
            return list(frames)
        signatures = [self._signature(path) for path in frames]
        deltas = [self._delta(left, right) for left, right in zip(signatures, signatures[1:])]
        moving = [index for index, value in enumerate(deltas) if value > 1.5]
        if moving:
            start = max(0, moving[0])
            end = min(len(frames) - 1, moving[-1] + 1)
            pool = frames[start : end + 1]
        else:
            pool = frames
        if len(pool) <= max_frames:
            return list(pool)
        indices = []
        for index in range(max_frames):
            candidate = round(index * (len(pool) - 1) / max(1, max_frames - 1))
            if candidate not in indices:
                indices.append(candidate)
        return [pool[index] for index in indices]

    def _signature(self, path: Path) -> list[int]:
        with Image.open(path) as image:
            sample = ImageOps.grayscale(image).resize((32, 32), Image.Resampling.LANCZOS)
            pixels = sample.get_flattened_data() if hasattr(sample, "get_flattened_data") else sample.getdata()
            return [int(pixel) for pixel in pixels]

    def _delta(self, left: list[int], right: list[int]) -> float:
        return statistics.mean(abs(a - b) for a, b in zip(left, right))

    def _annotate(self, source: Path, output: Path, detection: dict) -> None:
        with Image.open(source).convert("RGB") as image:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            promo_bbox = self._pixel_bbox(detection.get("promo_bbox_norm"), image.size)
            close_bbox = self._pixel_bbox(detection.get("close_button_bbox_norm"), image.size)
            if detection.get("promo_present") and promo_bbox:
                draw.rectangle(promo_bbox, outline=(255, 0, 0), width=max(4, image.width // 180))
                self._label(draw, promo_bbox[0], promo_bbox[1], f"PROMO {detection.get('promo_state', 'uncertain')}", font, image.size)
            if detection.get("close_button_present") and close_bbox:
                draw.rectangle(close_bbox, outline=(255, 0, 0), width=max(4, image.width // 180))
                self._label(draw, close_bbox[0], close_bbox[1], "CLOSE", font, image.size)
            if not detection.get("promo_present"):
                self._label(draw, 12, 40, "PROMO none", font, image.size)
            image.save(output, format="PNG")

    def _pixel_bbox(self, bbox, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        width, height = size
        x1, y1, x2, y2 = (int(value) for value in bbox)
        return (
            max(0, min(width - 1, round(x1 * width / 1000))),
            max(0, min(height - 1, round(y1 * height / 1000))),
            max(0, min(width - 1, round(x2 * width / 1000))),
            max(0, min(height - 1, round(y2 * height / 1000))),
        )

    def _label(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font, size: tuple[int, int]) -> None:
        box = draw.textbbox((0, 0), text, font=font)
        label_width, label_height = box[2] - box[0] + 12, box[3] - box[1] + 10
        top = max(0, y - label_height)
        draw.rectangle((x, top, min(size[0] - 1, x + label_width), top + label_height), fill=(255, 0, 0))
        draw.text((x + 6, top + 4), text, fill=(255, 255, 255), font=font)
