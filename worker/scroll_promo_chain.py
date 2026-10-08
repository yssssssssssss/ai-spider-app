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


COLLAPSED_WIDTH_RATIO = 2 / 3
STATIC_PROMO_CONFIDENCE_THRESHOLD = 0.75


def passes_static_confidence(present: bool, confidence: float | int | None, threshold: float = STATIC_PROMO_CONFIDENCE_THRESHOLD) -> bool:
    try:
        return bool(present) and float(confidence or 0) >= threshold
    except (TypeError, ValueError):
        return False


def is_collapsed_width(promo_width: int | None, baseline_width: int | None, threshold: float = COLLAPSED_WIDTH_RATIO) -> bool:
    if promo_width is None or not baseline_width:
        return False
    return (promo_width / baseline_width) < threshold


@dataclass(frozen=True)
class ScrollPromoConfig:
    app_name: str
    package: str
    device_serial: str
    output_dir: Path
    swipe_count: int = 1
    max_frames: int = 6
    fps: int = 10
    swipe_duration_ms: int = 2000
    motion_window_offset_seconds: float = 0.5
    motion_window_duration_seconds: float = 1.0
    app_wait_seconds: float = 6.0
    target_tab: str = "新品"
    page_wait_seconds: float = 5.0
    static_frame_count: int = 3
    static_scroll_distance_px: int = 600
    static_confidence_threshold: float = STATIC_PROMO_CONFIDENCE_THRESHOLD
    collapse_width_ratio: float = COLLAPSED_WIDTH_RATIO


@dataclass(frozen=True)
class ScrollPromoResult:
    annotated_paths: list[Path]
    static_detections: list[dict]
    static_summary: dict
    motion_detections: list[dict]
    report_path: Path
    capture_method: str

    @property
    def detections(self) -> list[dict]:
        return [*self.static_detections, *self.motion_detections]


class ScrollCapture(Protocol):
    method: str

    def open_app(self, package: str, device_serial: str, wait_seconds: float) -> None: ...
    def prepare_target(self, config: ScrollPromoConfig) -> dict: ...
    def capture_still(self, config: ScrollPromoConfig, scratch_dir: Path) -> Path: ...
    def scroll_static(self, config: ScrollPromoConfig, pixels: int) -> None: ...
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

    def prepare_target(self, config: ScrollPromoConfig) -> dict:
        import uiautomator2 as u2

        device = u2.connect(config.device_serial)
        target = device(text=config.target_tab)
        if not target.exists:
            target = device(description=config.target_tab)
        if not target.exists:
            raise RuntimeError(f"Target tab not found: {config.target_tab}")
        target.click()
        time.sleep(max(0.0, config.page_wait_seconds))
        popup_closed = self._close_center_popup(device)
        if popup_closed:
            time.sleep(1.0)
        return {"target_tab": config.target_tab, "popup_closed": popup_closed}

    def _close_center_popup(self, device) -> bool:
        markers = ["关闭", "取消", "跳过", "我知道了", "以后再说", "暂不", "X", "×"]
        candidates = []
        for marker in markers:
            candidates.extend([device(text=marker), device(description=marker)])
        candidates.append(device(resourceIdMatches=r".*(close|cancel|dismiss|skip|iv_close|img_close|btn_close).*"))
        for element in candidates:
            try:
                if not element.exists:
                    continue
                info = element.info
                bounds = info.get("bounds") or {}
                center_x = (int(bounds.get("left", 0)) + int(bounds.get("right", 0))) / 2
                center_y = (int(bounds.get("top", 0)) + int(bounds.get("bottom", 0))) / 2
                if 160 <= center_x <= 920 and 300 <= center_y <= 2000:
                    element.click()
                    return True
            except Exception:
                continue
        return False

    def capture_still(self, config: ScrollPromoConfig, scratch_dir: Path) -> Path:
        result = subprocess.run(
            self._adb(config.device_serial, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0 or self.is_blank_png(result.stdout):
            raise RuntimeError("Baseline target-page screenshot is blank")
        path = scratch_dir / "baseline.png"
        path.write_bytes(result.stdout)
        return path

    def scroll_static(self, config: ScrollPromoConfig, pixels: int) -> None:
        distance = max(1, int(pixels))
        start_y = 1400
        end_y = max(200, start_y - distance)
        subprocess.run(
            self._adb(
                config.device_serial,
                "shell",
                "input",
                "swipe",
                "540",
                str(start_y),
                "540",
                str(end_y),
                "300",
            ),
            check=True,
            timeout=10,
        )
        time.sleep(1.0)

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
                "-i", str(video), "-vf", f"fps={max(1, config.fps)}", pattern,
            ],
            check=True,
            timeout=30,
        )
        frames = sorted(scratch_dir.glob("candidate-*.png"))
        if not frames:
            raise RuntimeError("No frames extracted from scrcpy recording")
        return self._motion_window(frames, config)

    def _motion_window(self, frames: list[Path], config: ScrollPromoConfig) -> list[Path]:
        signatures = []
        for path in frames:
            with Image.open(path) as image:
                sample = ImageOps.grayscale(image).resize((32, 32), Image.Resampling.LANCZOS)
                pixels = sample.get_flattened_data() if hasattr(sample, "get_flattened_data") else sample.getdata()
                signatures.append([int(pixel) for pixel in pixels])
        deltas = [statistics.mean(abs(a - b) for a, b in zip(left, right)) for left, right in zip(signatures, signatures[1:])]
        moving = [index for index, value in enumerate(deltas) if value > 1.5]
        if not moving:
            raise RuntimeError("No visual movement detected in scrcpy recording")
        offset_frames = round(config.motion_window_offset_seconds * config.fps)
        target_count = max(1, round(config.motion_window_duration_seconds * config.fps))
        start = min(len(frames) - 1, moving[0] + offset_frames)
        end = min(len(frames), start + target_count)
        if end - start < target_count:
            start = max(0, end - target_count)
        return frames[start:end]

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
        baseline_detection: dict = {}
        motion_detections: list[dict] = []
        preparation: dict = {}
        try:
            self.capture.open_app(config.package, config.device_serial, config.app_wait_seconds)
            preparation = self.capture.prepare_target(config)
            static_detections: list[dict] = []
            for static_index in range(1, max(1, config.static_frame_count) + 1):
                static_path = self.capture.capture_still(config, scratch)
                detection = dict(self.detect(static_path))
                detection.update({
                    "step": 2,
                    "static_index": static_index,
                    "source_frame": static_path.name,
                    "promo_confidence_threshold": config.static_confidence_threshold,
                    "promo_confidence_passed": passes_static_confidence(detection.get("promo_present"), detection.get("confidence"), config.static_confidence_threshold),
                    "close_confidence_passed": passes_static_confidence(detection.get("close_button_below_promo"), detection.get("confidence"), config.static_confidence_threshold),
                })
                output = config.output_dir / f"step_02_static_{static_index:02d}_{detection.get('promo_state', 'unknown')}.png"
                self._annotate(static_path, output, detection)
                detection["annotated_file"] = output.name
                static_detections.append(detection)
                annotated_paths.append(output)
                if static_index < max(1, config.static_frame_count):
                    self.capture.scroll_static(config, config.static_scroll_distance_px)

            static_widths = [
                item["promo_bbox_norm"][2] - item["promo_bbox_norm"][0]
                for item in static_detections
                if item.get("promo_confidence_passed") and item.get("promo_bbox_norm")
            ]
            baseline_width = max(static_widths) if static_widths else None
            static_summary = {
                "confidence_threshold": config.static_confidence_threshold,
                "promo_present": any(bool(item.get("promo_confidence_passed")) for item in static_detections),
                "close_button_present": any(bool(item.get("close_confidence_passed")) for item in static_detections),
                "static_promo_widths_norm": static_widths,
                "baseline_promo_width_norm": baseline_width,
            }

            candidate_frame_count = 0
            for swipe_index in range(max(1, config.swipe_count)):
                swipe_scratch = scratch / f"swipe-{swipe_index + 1:02d}"
                swipe_scratch.mkdir(parents=True, exist_ok=True)
                candidates = self.capture.capture_swipe(config, swipe_scratch)
                candidate_frame_count += len(candidates)
                selected = self._select_motion_frames(candidates, max(1, min(config.max_frames, 10)))
                for frame_index, frame in enumerate(selected, start=1):
                    detection = dict(self.detect(frame))
                    promo_bbox = detection.get("promo_bbox_norm") if detection.get("promo_present") else None
                    promo_width = (promo_bbox[2] - promo_bbox[0]) if promo_bbox else None
                    width_ratio = (promo_width / baseline_width) if promo_width is not None and baseline_width else None
                    collapsed_by_width = is_collapsed_width(promo_width, baseline_width, config.collapse_width_ratio)
                    if detection.get("promo_present") and width_ratio is not None:
                        detection["promo_state"] = "collapsed" if collapsed_by_width else "expanded"
                    detection.update({
                        "step": 3,
                        "swipe_index": swipe_index + 1,
                        "frame_index": frame_index,
                        "source_frame": frame.name,
                        "promo_width_norm": promo_width,
                        "baseline_promo_width_norm": baseline_width,
                        "width_ratio_to_baseline": round(width_ratio, 4) if width_ratio is not None else None,
                        "collapsed_by_width": collapsed_by_width,
                    })
                    output = config.output_dir / f"step_03_swipe_{swipe_index + 1:02d}_frame_{frame_index:02d}_{detection.get('promo_state', 'unknown')}.png"
                    self._annotate(frame, output, detection)
                    detection["annotated_file"] = output.name
                    annotated_paths.append(output)
                    motion_detections.append(detection)
        finally:
            self.capture.close_app(config.package, config.device_serial)
            shutil.rmtree(scratch, ignore_errors=True)

        method = getattr(self.capture, "last_method", getattr(self.capture, "method", "unknown"))
        report = {
            "report_type": "scroll_promo",
            "schema_version": 1,
            "app_name": config.app_name,
            "package": config.package,
            "device_serial": config.device_serial,
            "capture_method": method,
            "step1": {
                "target_tab": config.target_tab,
                "page_wait_seconds": config.page_wait_seconds,
                "popup_closed": bool(preparation.get("popup_closed")),
            },
            "step2": {
                "frames": static_detections,
                "static_frame_count": len(static_detections),
                "static_scroll_distance_px": config.static_scroll_distance_px,
                **static_summary,
            },
            "step3": {
                "swipe_count": config.swipe_count,
                "swipe_duration_seconds": config.swipe_duration_ms / 1000,
                "motion_window_start_seconds": config.motion_window_offset_seconds,
                "motion_window_duration_seconds": config.motion_window_duration_seconds,
                "fps": config.fps,
                "candidate_frame_count": candidate_frame_count,
                "max_frames_per_swipe": config.max_frames,
                "selected_frame_count": len(motion_detections),
                "detections": motion_detections,
            },
            "summary": {
                "collapse_width_ratio_threshold": config.collapse_width_ratio,
                "static_confidence_threshold": config.static_confidence_threshold,
                "static_promo_present": static_summary["promo_present"],
                "static_close_button_present": static_summary["close_button_present"],
                "baseline_promo_width_norm": baseline_width,
                "motion_promo_frame_count": sum(bool(item.get("promo_present")) for item in motion_detections),
                "collapsed_frame_count": sum(bool(item.get("collapsed_by_width")) for item in motion_detections),
            },
        }
        report_path = config.output_dir / "promotion_detections.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return ScrollPromoResult(annotated_paths, static_detections, static_summary, motion_detections, report_path, method)

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
            if detection.get("close_button_present") and detection.get("close_button_below_promo") and close_bbox:
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
