"""Measure existing screenshot regions without models, network calls, or database writes."""
import argparse
import base64
import hashlib
from html import escape
from io import BytesIO
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image
from app.services.visual_measurement import compare_length, measure_color, measure_distance, scan_color_bands


def measure_plan(image, plan):
    operations = {"color": measure_color, "bands": scan_color_bands, "distance": measure_distance}
    measurements = plan.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        raise ValueError("plan.measurements must be a nonempty list")
    results, ids = [], set()
    for item in measurements:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError("each measurement needs a nonempty string id")
        if item["id"] in ids:
            raise ValueError(f"duplicate measurement id: {item['id']}")
        ids.add(item["id"])
        kind, params = item.get("kind"), item.get("params")
        if kind not in operations or not isinstance(params, dict):
            raise ValueError(f"{item['id']}: kind must be color, bands, or distance; params must be an object")
        result = operations[kind](image, **params)
        comparison = item.get("length_comparison")
        if comparison is not None:
            if kind == "color" or not isinstance(comparison, dict):
                raise ValueError("length_comparison requires a bands or distance measurement and an object")
            compare_length(0, **comparison)  # Validate even if the scan finds no bands.
            if kind == "distance":
                result["length_comparison"] = compare_length(result["distance_px"], **comparison)
            else:
                for band in result["bands"]:
                    band["length_comparison"] = compare_length(band["length_px"], **comparison)
        results.append({"id": item["id"], "label": item.get("label", item["id"]),
                        "rule_id": item.get("rule_id"), "kind": kind, "measurement": result})
    return results


def capture_identity(capture, image_path, sha256, size):
    matches = [screen for screen in capture["screens"]
               if Path(screen["file"]).name == image_path.name and screen["sha256"] == sha256]
    if len(matches) != 1 or (matches[0]["width"], matches[0]["height"]) != size:
        raise ValueError("capture metadata does not uniquely match the screenshot hash and dimensions")
    return {"venue": capture["venue"], "screen": matches[0]}


def html_report(report, image_bytes, mime):
    width, height = report["source"]["width"], report["source"]["height"]
    uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    cards = []
    for item in report["measurements"]:
        value = item["measurement"]
        boxes = []
        if "bbox_px" in value:
            boxes.append((value["bbox_px"], "#0077CC"))
        if item["kind"] == "distance":
            boxes.extend([(value["first_bbox_px"], "#0077CC"), (value["second_bbox_px"], "#BE185D")])
            if value["evidence_bbox_px"]:
                boxes.append((value["evidence_bbox_px"], "#D97706"))
        boxes.extend((band["bbox_px"], "#008500") for band in value.get("bands", []))
        marks = "".join(f'<rect x="{x}" y="{y}" width="{r-x}" height="{b-y}" '
                        f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="1"/>'
                        for (x, y, r, b), color in boxes)
        summary = (f'主色 {value["dominant_hex"]}，占比 {value["dominant_ratio"]:.2%}' if item["kind"] == "color" else
                   f'边缘距离 {value["distance_px"]} 截图像素' if item["kind"] == "distance" else
                   f'背景色条带 {[band["length_px"] for band in value["bands"]]} 截图像素')
        cards.append(f'<section><h2>{escape(str(item["label"]))}</h2><p>{escape(summary)}</p>'
                     f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="测量区域标注">'
                     f'<use href="#source-image"/>{marks}</svg>'
                     f'<details><summary>坐标与原始数据</summary><pre>{escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></section>')
    identity = report.get("capture", {}).get("venue", {})
    description = (f'{identity.get("venue_name", "")} / 会场ID {identity.get("venue_id", "未提供")}'
                   f' / 通天塔项目ID {identity.get("project_id", "未提供")}')
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>截图视觉测量</title>
<style>body{{font:15px system-ui;margin:24px;background:#f3f4f6;color:#111827}}main{{display:flex;flex-wrap:wrap;gap:20px}}section{{background:white;padding:16px;width:390px;border-radius:8px}}svg{{width:100%;height:auto}}h2{{font-size:18px}}pre{{white-space:pre-wrap;word-break:break-word}}.source{{overflow-wrap:anywhere}}.definitions{{position:absolute;width:0;height:0;overflow:hidden}}</style>
<h1>截图视觉测量</h1><p>{escape(description)}</p>
<p>数值单位：截图像素。蓝/红框是输入区域，绿色框是背景色条带，橙色框是边缘间区域。条带不自动等同于楼层间隔；未校准尺寸时不判定24PX合规。</p>
<p class="source">截图 SHA256：{report["source"]["sha256"]}</p>
<svg class="definitions" aria-hidden="true"><defs><image id="source-image" width="{width}" height="{height}" href="{uri}"/></defs></svg>
<main>{''.join(cards)}</main></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--capture", help="Optional capture.json to preserve and verify venue identity")
    parser.add_argument("--output", required=True, help="Measurement JSON output")
    parser.add_argument("--html", help="Optional standalone report with annotated regions")
    args = parser.parse_args()
    try:
        image_path, plan_path = Path(args.image).resolve(), Path(args.plan).resolve()
        sources = {image_path, plan_path}
        if args.capture:
            sources.add(Path(args.capture).resolve())
        outputs = [Path(value).resolve() for value in (args.output, args.html) if value]
        if len(set(outputs)) != len(outputs) or any(path in sources for path in outputs):
            raise ValueError("output paths must be distinct from each other and all input files")
        image_bytes = image_path.read_bytes()
        plan_bytes = plan_path.read_bytes()
        plan = json.loads(plan_bytes)
        if not isinstance(plan, dict):
            raise ValueError("plan must be a JSON object")
        with Image.open(BytesIO(image_bytes)) as image:
            if getattr(image, "n_frames", 1) != 1 or image.getexif().get(274, 1) != 1:
                raise ValueError("use a single-frame screenshot without EXIF orientation")
            report = {
                "schema_version": 1, "mode": "screenshot_pixel_measurement", "audit_verdict": "not_evaluated",
                "source": {"file": str(image_path), "sha256": hashlib.sha256(image_bytes).hexdigest(),
                           "width": image.width, "height": image.height, "format": image.format,
                           "color_space": "decoded_raster_channels", "icc_profile_present": bool(image.info.get("icc_profile"))},
                "plan": {"file": str(plan_path), "sha256": hashlib.sha256(plan_bytes).hexdigest()},
                "measurements": measure_plan(image, plan),
            }
            if args.capture:
                report["capture"] = capture_identity(json.loads(Path(args.capture).read_text(encoding="utf-8")), image_path,
                                                     report["source"]["sha256"], image.size)
            html = html_report(report, image_bytes, Image.MIME[image.format]) if args.html else None
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        outputs[0].write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if html is not None:
            outputs[1].write_text(html, encoding="utf-8")
        print(f"measured {len(report['measurements'])} regions: {outputs[0]}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"measurement failed: {exc}\n")


if __name__ == "__main__":
    main()
