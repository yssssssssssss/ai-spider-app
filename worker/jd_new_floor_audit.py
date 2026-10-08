from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError


X_REGION_TOP = 510
X_REGION_BOTTOM = 1090
Y_REGION_RIGHT = 540
SECONDARY_TARGET_TAB = "新奇集市"
SECONDARY_TAB_ANCHOR_TEXT = "推荐"
SECONDARY_FRAME_FILENAMES = {
    "z1_before": "secondary_tab_z1_before.png",
    "z1_after_left": "secondary_tab_z1_after_left.png",
    "z2_before": "secondary_tab_z2_before.png",
    "z2_after_left": "secondary_tab_z2_after_left.png",
    "z3_before": "secondary_tab_z3_before.png",
}
HORIZONTAL_SWIPE_DISTANCE_PX = 400
PAGE_SCROLL_DOWN_PX = 800
PAGE_SCROLL_UP_PX = 400
SECONDARY_TAB_WAIT_SECONDS = 8.0
GESTURE_SETTLE_SECONDS = 0.8

TOP_NAV_FALLBACK_RATIOS = {
    "新品": (0.58, 0.056),
}


@dataclass(frozen=True)
class JdNewFloorConfig:
    app_name: str
    package: str
    device_serial: str
    output_dir: Path
    target_tab: str = "新品"
    app_wait_seconds: float = 6.0
    page_wait_seconds: float = 5.0


@dataclass(frozen=True)
class JdNewFloorResult:
    raw_path: Path
    annotated_path: Path
    report_path: Path
    report: dict


class FloorCapture(Protocol):
    def open_app(self, config: JdNewFloorConfig) -> None: ...

    def prepare_target(self, config: JdNewFloorConfig) -> dict: ...

    def enter_secondary_tab(self, config: JdNewFloorConfig, target_tab: str) -> str: ...

    def capture_fullscreen(self, config: JdNewFloorConfig) -> bytes: ...

    def swipe(
        self,
        config: JdNewFloorConfig,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None: ...

    def close_app(self, config: JdNewFloorConfig) -> None: ...


class AdbFloorCapture:
    """Open JD, enter the requested tab, dismiss blocking overlays and capture once."""

    def _adb(self, serial: str, *args: str) -> list[str]:
        return ["adb", "-s", serial, *args]

    def open_app(self, config: JdNewFloorConfig) -> None:
        subprocess.run(
            self._adb(config.device_serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP"),
            capture_output=True,
        )
        subprocess.run(
            self._adb(config.device_serial, "shell", "wm", "dismiss-keyguard"),
            capture_output=True,
        )
        subprocess.run(
            self._adb(config.device_serial, "shell", "am", "force-stop", config.package),
            capture_output=True,
        )
        resolved = subprocess.run(
            self._adb(
                config.device_serial,
                "shell",
                "cmd",
                "package",
                "resolve-activity",
                "--brief",
                "-c",
                "android.intent.category.LAUNCHER",
                config.package,
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
        component = next(
            (line.strip() for line in reversed(resolved.stdout.splitlines()) if "/" in line),
            "",
        )
        if not component:
            raise RuntimeError(f"Unable to resolve launcher activity for {config.package}")
        result = subprocess.run(
            self._adb(
                config.device_serial,
                "shell",
                "am",
                "start",
                "-S",
                "-W",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
                "-n",
                component,
            ),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0 or "Error:" in result.stdout:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Unable to launch {config.package}")
        time.sleep(max(0.0, config.app_wait_seconds))

    def prepare_target(self, config: JdNewFloorConfig) -> dict:
        import uiautomator2 as u2

        device = u2.connect(config.device_serial)
        navigation_method = self._click_target_tab(device, config.target_tab)
        time.sleep(max(0.0, config.page_wait_seconds))

        popup_close_count = 0
        for _ in range(3):
            if not self._close_one_popup(device):
                break
            popup_close_count += 1
            time.sleep(1.0)
        return {
            "target_tab": config.target_tab,
            "navigation_method": navigation_method,
            "popup_close_count": popup_close_count,
        }

    def enter_secondary_tab(self, config: JdNewFloorConfig, target_tab: str) -> str:
        import uiautomator2 as u2

        return self._click_secondary_tab(u2.connect(config.device_serial), target_tab)

    def _click_secondary_tab(self, device, target_tab: str) -> str:
        _, height = device.window_size()
        for selector_name in ("text", "description"):
            for instance in range(8):
                target = device(**{selector_name: target_tab, "instance": instance})
                if not target.exists:
                    break
                try:
                    bounds = (target.info or {}).get("bounds") or {}
                    center_y = (int(bounds.get("top", height)) + int(bounds.get("bottom", height))) / 2
                except Exception:
                    continue
                if 300 <= center_y <= min(900, height * 0.45):
                    target.click()
                    return "accessibility"
        raise RuntimeError(f"Secondary tab not found: {target_tab}")

    def _click_target_tab(self, device, target_tab: str) -> str:
        fallback = TOP_NAV_FALLBACK_RATIOS.get(target_tab)
        if fallback is None:
            raise RuntimeError(f"Target tab not found: {target_tab}")
        width, height = device.window_size()
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Invalid device window size: {width}x{height}")

        for selector_name in ("text", "description"):
            for instance in range(8):
                target = device(**{selector_name: target_tab, "instance": instance})
                if not target.exists:
                    break
                try:
                    bounds = (target.info or {}).get("bounds") or {}
                    center_y = (int(bounds.get("top", height)) + int(bounds.get("bottom", height))) / 2
                except Exception:
                    continue
                if center_y <= min(420, height * 0.2):
                    target.click()
                    return "accessibility"

        device.click(round(width * fallback[0]), round(height * fallback[1]))
        return "screen_ratio"

    def _close_one_popup(self, device) -> bool:
        markers = ("关闭", "取消", "跳过", "我知道了", "以后再说", "暂不", "X", "×")
        candidates = []
        for marker in markers:
            candidates.extend((device(text=marker), device(description=marker)))
        candidates.append(
            device(resourceIdMatches=r".*(close|cancel|dismiss|skip|iv_close|img_close|btn_close).*")
        )
        for element in candidates:
            try:
                if not element.exists:
                    continue
                bounds = (element.info or {}).get("bounds") or {}
                center_x = (int(bounds.get("left", 0)) + int(bounds.get("right", 0))) / 2
                center_y = (int(bounds.get("top", 0)) + int(bounds.get("bottom", 0))) / 2
                if 80 <= center_x <= 1000 and 160 <= center_y <= 2200:
                    element.click()
                    return True
            except Exception:
                continue
        return False

    def capture_fullscreen(self, config: JdNewFloorConfig) -> bytes:
        result = subprocess.run(
            self._adb(config.device_serial, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError("Full-screen capture failed")
        try:
            with Image.open(BytesIO(result.stdout)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise RuntimeError("Full-screen capture is not a valid image") from exc
        return result.stdout

    def swipe(
        self,
        config: JdNewFloorConfig,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None:
        result = subprocess.run(
            self._adb(
                config.device_serial,
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration_ms),
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Swipe gesture failed")

    def close_app(self, config: JdNewFloorConfig) -> None:
        subprocess.run(
            self._adb(config.device_serial, "shell", "am", "force-stop", config.package),
            capture_output=True,
            timeout=10,
        )


class JdNewFloorAudit:
    def __init__(
        self,
        *,
        analyze: Callable[[Path], dict],
        locate_secondary: Callable[[Path], dict] | None = None,
        analyze_secondary: Callable[[dict[str, Path], list[int]], dict] | None = None,
        capture: FloorCapture | None = None,
    ):
        self.analyze = analyze
        self.locate_secondary = locate_secondary
        self.analyze_secondary = analyze_secondary
        self.capture = capture or AdbFloorCapture()

    def run(self, config: JdNewFloorConfig) -> JdNewFloorResult:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = config.output_dir / "raw_fullscreen.png"
        annotated_path = config.output_dir / "annotated_floor_audit.png"
        report_path = config.output_dir / "jd_new_floor_report.json"

        try:
            self.capture.open_app(config)
            preparation = self.capture.prepare_target(config)
            raw_path.write_bytes(self.capture.capture_fullscreen(config))
            width, height = self._image_size(raw_path)
            if width < Y_REGION_RIGHT or height < X_REGION_BOTTOM:
                raise ValueError(
                    f"Screenshot must be at least {Y_REGION_RIGHT}x{X_REGION_BOTTOM}px; got {width}x{height}px"
                )

            secondary_paths = None
            secondary_z1_bbox = None
            secondary_location = None
            secondary_navigation_method = None
            if self.analyze_secondary is not None:
                if self.locate_secondary is None:
                    raise ValueError("Secondary Tab locator is required")
                secondary_navigation_method = self.capture.enter_secondary_tab(config, SECONDARY_TARGET_TAB)
                time.sleep(SECONDARY_TAB_WAIT_SECONDS)
                secondary_paths, secondary_z1_bbox, secondary_location = self._capture_secondary_frames(config, width, height)

            report = dict(self.analyze(raw_path))
            if report.get("report_type") != "jd_new_floor_audit":
                raise ValueError("Analyzer returned an unexpected report type")
            report.setdefault("capture", {}).update(
                {
                    "app_name": config.app_name,
                    "package": config.package,
                    "device_serial": config.device_serial,
                    "target_tab": config.target_tab,
                    "navigation_method": str(preparation.get("navigation_method") or "unknown"),
                    "popup_close_count": int(preparation.get("popup_close_count") or 0),
                    "image_width": width,
                    "image_height": height,
                }
            )
            report["artifacts"] = {
                "raw": {"filename": raw_path.name},
                "annotated": {"filename": annotated_path.name},
            }
            self._annotate(raw_path, annotated_path, report)

            if secondary_paths is not None and secondary_z1_bbox is not None:
                secondary = dict(self.analyze_secondary(secondary_paths, secondary_z1_bbox))
                if secondary.get("report_type") != "jd_secondary_tab_audit":
                    raise ValueError("Secondary Tab analyzer returned an unexpected report type")
                secondary.setdefault("capture", {}).update(
                    {
                        "secondary_target_tab": SECONDARY_TARGET_TAB,
                        "secondary_navigation_method": secondary_navigation_method or "unknown",
                        "secondary_tab_wait_seconds": SECONDARY_TAB_WAIT_SECONDS,
                        "z1_detection_method": "red_text_anchor",
                        "z1_anchor_text": SECONDARY_TAB_ANCHOR_TEXT,
                        "page_scroll_down_px": PAGE_SCROLL_DOWN_PX,
                        "page_scroll_up_px": PAGE_SCROLL_UP_PX,
                        "horizontal_swipe_direction": "left",
                        "horizontal_swipe_distance_px": HORIZONTAL_SWIPE_DISTANCE_PX,
                    }
                )
                secondary["z1_locator"] = secondary_location or {}
                report["secondary_tab_audit"] = secondary

            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return JdNewFloorResult(raw_path, annotated_path, report_path, report)
        finally:
            self.capture.close_app(config)

    def _capture_secondary_frames(
        self,
        config: JdNewFloorConfig,
        width: int,
        height: int,
    ) -> tuple[dict[str, Path], list[int], dict]:
        if width <= HORIZONTAL_SWIPE_DISTANCE_PX + 80 or height < 1300:
            raise ValueError(f"Screenshot is too small for secondary Tab gestures: {width}x{height}px")

        paths = {"z1_before": self._save_frame(config, "z1_before")}
        location = dict(self.locate_secondary(paths["z1_before"]))
        if location.get("report_type") != "jd_secondary_tab_locator":
            raise ValueError("Secondary Tab locator returned an unexpected report type")
        z1_bbox = location.get("bbox_px")
        if not isinstance(z1_bbox, list) or len(z1_bbox) != 4 or z1_bbox[0] != 0 or z1_bbox[2] != width:
            raise ValueError(f"Invalid detected z1 region: {z1_bbox}")
        z1_center_y = round((z1_bbox[1] + z1_bbox[3]) / 2)
        center_x = width // 2
        left_start_x = center_x + HORIZONTAL_SWIPE_DISTANCE_PX // 2
        left_end_x = center_x - HORIZONTAL_SWIPE_DISTANCE_PX // 2
        vertical_x = round(width * 0.82)
        down_start_y = min(height - 300, 1700)
        down_end_y = down_start_y - PAGE_SCROLL_DOWN_PX
        up_start_y = max(700, down_end_y)
        up_end_y = up_start_y + PAGE_SCROLL_UP_PX

        self._swipe(config, left_start_x, z1_center_y, left_end_x, z1_center_y, 350)
        paths["z1_after_left"] = self._save_frame(config, "z1_after_left")
        self._swipe(config, left_end_x, z1_center_y, left_start_x, z1_center_y, 350)

        # “页面向下滚动”对应手指向上：y 减少 800px。
        self._swipe(config, vertical_x, down_start_y, vertical_x, down_end_y, 600)
        paths["z2_before"] = self._save_frame(config, "z2_before")
        self._swipe(config, left_start_x, 487, left_end_x, 487, 350)
        paths["z2_after_left"] = self._save_frame(config, "z2_after_left")
        self._swipe(config, left_end_x, 487, left_start_x, 487, 350)

        # “页面向上回退”对应手指向下：y 增加 400px。
        self._swipe(config, vertical_x, up_start_y, vertical_x, up_end_y, 400)
        paths["z3_before"] = self._save_frame(config, "z3_before")
        return paths, z1_bbox, location

    def _swipe(
        self,
        config: JdNewFloorConfig,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None:
        self.capture.swipe(config, start_x, start_y, end_x, end_y, duration_ms)
        time.sleep(GESTURE_SETTLE_SECONDS)

    def _save_frame(self, config: JdNewFloorConfig, frame_key: str) -> Path:
        path = config.output_dir / SECONDARY_FRAME_FILENAMES[frame_key]
        path.write_bytes(self.capture.capture_fullscreen(config))
        return path

    def _image_size(self, path: Path) -> tuple[int, int]:
        with Image.open(path) as image:
            return image.size

    def _annotate(self, source: Path, output: Path, report: dict) -> None:
        with Image.open(source).convert("RGB") as image:
            draw = ImageDraw.Draw(image)
            font = self._font(max(18, image.width // 48))
            line_width = max(4, image.width // 180)
            regions = report.get("regions") or {}
            self._draw_box(
                draw,
                regions.get("x", {}).get("bbox_px"),
                "X REGION",
                "#ff9500",
                font,
                image.size,
                line_width,
                align_right=True,
            )
            self._draw_box(draw, regions.get("y", {}).get("bbox_px"), "Y REGION", "#00a3ff", font, image.size, line_width)

            checks = report.get("checks") or {}
            check_items = checks.values() if isinstance(checks, dict) else checks
            for check in check_items:
                if not isinstance(check, dict):
                    continue
                color = self._status_color(str(check.get("status") or "uncertain"))
                annotations = check.get("annotations") or check.get("evidence") or []
                for annotation_index, annotation in enumerate(annotations, start=1):
                    if not isinstance(annotation, dict):
                        continue
                    check_id = str(check.get("id") or "CHECK")
                    label = f"{check_id}-{annotation_index} {annotation.get('label') or ''}".strip()
                    self._draw_box(
                        draw,
                        annotation.get("bbox_px"),
                        label,
                        color,
                        font,
                        image.size,
                        line_width,
                        label_inside=True,
                    )
            image.save(output, format="PNG", optimize=True)

    def _draw_box(
        self,
        draw: ImageDraw.ImageDraw,
        value,
        label: str,
        color: str,
        font: ImageFont.ImageFont,
        image_size: tuple[int, int],
        line_width: int,
        *,
        label_inside: bool = False,
        align_right: bool = False,
    ) -> None:
        bbox = self._safe_bbox(value, image_size)
        if bbox is None:
            return
        draw.rectangle(bbox, outline=color, width=line_width)
        safe_label = label.strip() or "CHECK"
        try:
            text_box = draw.textbbox((0, 0), safe_label, font=font)
        except UnicodeEncodeError:
            safe_label = label.encode("ascii", errors="ignore").decode("ascii").strip() or "CHECK"
            text_box = draw.textbbox((0, 0), safe_label, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        label_x = max(bbox[0], bbox[2] - text_width - 12) if align_right else bbox[0]
        label_y = (
            min(image_size[1] - text_height - 8, bbox[1] + line_width)
            if label_inside
            else max(0, bbox[1] - text_height - 10)
        )
        draw.rectangle(
            (label_x, label_y, min(image_size[0] - 1, label_x + text_width + 12), label_y + text_height + 8),
            fill=color,
        )
        draw.text((label_x + 6, label_y + 3), safe_label, fill="white", font=font)

    def _safe_bbox(self, value, image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            left, top, right, bottom = (int(round(float(item))) for item in value)
        except (TypeError, ValueError):
            return None
        width, height = image_size
        left = max(0, min(width - 1, left))
        top = max(0, min(height - 1, top))
        right = max(0, min(width - 1, right))
        bottom = max(0, min(height - 1, bottom))
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _status_color(self, status: str) -> str:
        return {
            "pass": "#34c759",
            "fail": "#ff453a",
            "not_applicable": "#8e8e93",
        }.get(status, "#ffcc00")

    def _font(self, size: int) -> ImageFont.ImageFont:
        for path in (
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            "C:/Windows/Fonts/msyh.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
        return ImageFont.load_default()
