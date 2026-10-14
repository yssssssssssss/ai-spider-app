"""Deterministic screenshot measurements; locating semantic elements is a separate step."""
from collections import Counter
from math import isfinite
import re

from PIL import Image


def _box(image: Image.Image, bbox) -> tuple[int, int, int, int]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or any(type(value) is not int for value in bbox):
        raise ValueError("bbox_px must contain four integer coordinates")
    left, top, right, bottom = bbox
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("bbox_px is outside the image or has zero area")
    return left, top, right, bottom


def _rgb(color: str) -> tuple[int, int, int]:
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("color must be #RRGGBB")
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def _hex(rgb) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def _delta(value) -> int:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("max_channel_delta must be an integer from 0 to 255")
    return value


def _matches(pixel, expected, delta: int) -> bool:
    return max(abs(a - b) for a, b in zip(pixel[:3], expected)) <= delta


def _finite_number(value) -> bool:
    return type(value) in (int, float) and isfinite(value)


def measure_color(image: Image.Image, bbox, *, expected_hex: str | None = None,
                  max_channel_delta: int = 0) -> dict:
    """Report actual opaque pixels, without guessing a stylesheet color or averaging a gradient."""
    bbox = _box(image, bbox)
    delta = _delta(max_channel_delta)
    expected = _rgb(expected_hex) if expected_hex is not None else None
    region = image.crop(bbox).convert("RGBA")
    histogram = region.getcolors(region.width * region.height)
    total = region.width * region.height
    opaque = Counter({pixel[:3]: count for count, pixel in histogram if pixel[3] == 255})
    opaque_count = sum(opaque.values())
    palette = sorted(opaque.items(), key=lambda item: (-item[1], item[0]))
    result = {
        "method": "opaque_pixel_histogram", "bbox_px": list(bbox), "pixel_count": total,
        "opaque_pixel_count": opaque_count, "nonopaque_pixel_count": total - opaque_count,
        "dominant_hex": _hex(palette[0][0]) if palette else None,
        "dominant_ratio": palette[0][1] / total if palette else 0,
        "uniform_opaque_region": len(palette) == 1 and opaque_count == total,
        "palette": [{"hex": _hex(rgb), "pixels": count, "ratio": count / total}
                    for rgb, count in palette[:5]],
        "status": "measured" if opaque_count else "no_opaque_pixels",
    }
    if expected is not None:
        matching = sum(count for rgb, count in palette if _matches(rgb, expected, delta))
        result["comparison"] = {
            "expected_hex": _hex(expected), "max_channel_delta": delta,
            "matching_pixel_count": matching, "matching_ratio": matching / total,
            "all_pixels_match": matching == total,
        }
    return result


def find_color_patch(image: Image.Image, bbox, *, color_hex: str, side_px: int = 3) -> list[int] | None:
    """Find a fully opaque square of the specified raster color inside a supplied region."""
    bbox, expected = _box(image, bbox), _rgb(color_hex)
    if type(side_px) is not int or side_px < 1:
        raise ValueError("side_px must be a positive integer")
    region = image.crop(bbox).convert("RGBA")
    pixels = region.load()
    for y in range(region.height - side_px + 1):
        for x in range(region.width - side_px + 1):
            if all(pixels[x + dx, y + dy] == (*expected, 255)
                   for dy in range(side_px) for dx in range(side_px)):
                return [bbox[0] + x, bbox[1] + y, bbox[0] + x + side_px, bbox[1] + y + side_px]
    return None


def scan_color_bands(image: Image.Image, bbox, *, background_hex: str,
                     axis: str = "vertical", max_channel_delta: int = 0,
                     min_matching_ratio: float = 1.0, min_length_px: int = 1) -> dict:
    """Find background-colored runs. Multiple runs remain candidates, not semantic floor gaps."""
    bbox = _box(image, bbox)
    expected = _rgb(background_hex)
    delta = _delta(max_channel_delta)
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be vertical or horizontal")
    if not _finite_number(min_matching_ratio) or not 0 < min_matching_ratio <= 1:
        raise ValueError("min_matching_ratio must be greater than 0 and at most 1")
    if type(min_length_px) is not int or min_length_px < 1:
        raise ValueError("min_length_px must be a positive integer")
    region = image.crop(bbox).convert("RGBA")
    if axis == "horizontal":
        region = region.transpose(Image.Transpose.TRANSPOSE)
    pixels = region.load()
    ratios = [sum(pixels[x, y][3] == 255 and _matches(pixels[x, y], expected, delta)
                  for x in range(region.width)) / region.width for y in range(region.height)]
    bands, start = [], None
    for index in range(len(ratios) + 1):
        qualifies = index < len(ratios) and ratios[index] >= min_matching_ratio
        if qualifies and start is None:
            start = index
        if not qualifies and start is not None:
            if index - start >= min_length_px:
                band_box = ([bbox[0], bbox[1] + start, bbox[2], bbox[1] + index]
                            if axis == "vertical" else
                            [bbox[0] + start, bbox[1], bbox[0] + index, bbox[3]])
                bands.append({"bbox_px": band_box, "length_px": index - start,
                              "min_matching_ratio": min(ratios[start:index]),
                              "touches_search_boundary": start == 0 or index == len(ratios)})
            start = None
    return {
        "method": "background_color_runs", "bbox_px": list(bbox), "axis": axis,
        "background_hex": _hex(expected), "max_channel_delta": delta,
        "required_matching_ratio": min_matching_ratio, "min_length_px": min_length_px,
        "bands": bands, "status": "no_band" if not bands else "single_candidate" if len(bands) == 1 else "multiple_candidates",
        "semantic_boundary_verified": False,
    }


def measure_distance(image: Image.Image, first_bbox, second_bbox, *, axis: str = "vertical") -> dict:
    """Measure the supplied edges; approximate VLM boxes do not become verified boundaries."""
    first, second = _box(image, first_bbox), _box(image, second_bbox)
    if axis == "vertical":
        if second[1] < first[1]:
            raise ValueError("vertical regions must be ordered top to bottom")
        low, high = max(first[0], second[0]), min(first[2], second[2])
        distance = second[1] - first[3]
        evidence = ([low, first[3], high, second[1]] if distance > 0 else
                    [low, second[1], high, min(first[3], second[3])])
    elif axis == "horizontal":
        if second[0] < first[0]:
            raise ValueError("horizontal regions must be ordered left to right")
        low, high = max(first[1], second[1]), min(first[3], second[3])
        distance = second[0] - first[2]
        evidence = ([first[2], low, second[0], high] if distance > 0 else
                    [second[0], low, min(first[2], second[2]), high])
    else:
        raise ValueError("axis must be vertical or horizontal")
    if low >= high:
        raise ValueError("regions have no overlap on the perpendicular axis")
    return {
        "method": "supplied_edge_coordinates", "axis": axis,
        "first_bbox_px": list(first), "second_bbox_px": list(second),
        "distance_px": distance, "relationship": "gap" if distance > 0 else "touching" if distance == 0 else "overlap",
        "evidence_bbox_px": evidence if distance else None, "semantic_boundary_verified": False,
    }


def compare_length(length_px: float, *, expected_design_px: float,
                   image_px_per_design_px: float | None = None,
                   calibration_source: str | None = None,
                   tolerance_design_px: float | None = None) -> dict:
    """Keep measurement, unit calibration, and an approved tolerance separate."""
    if not _finite_number(length_px) or not _finite_number(expected_design_px) or expected_design_px < 0:
        raise ValueError("lengths must be finite and the expected length nonnegative")
    result = {"observed_image_px": length_px, "expected_design_px": expected_design_px}
    if image_px_per_design_px is None:
        return {**result, "status": "needs_calibration"}
    if (not _finite_number(image_px_per_design_px) or image_px_per_design_px <= 0
            or not isinstance(calibration_source, str) or not calibration_source.strip()):
        raise ValueError("positive calibration scale and its source are required")
    observed = length_px / image_px_per_design_px
    result.update({"observed_design_px": observed, "image_px_per_design_px": image_px_per_design_px,
                   "calibration_source": calibration_source, "difference_design_px": observed - expected_design_px})
    if tolerance_design_px is None:
        return {**result, "status": "measured_without_acceptance_tolerance"}
    if not _finite_number(tolerance_design_px) or tolerance_design_px < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    return {**result, "tolerance_design_px": tolerance_design_px,
            "status": "within_tolerance" if abs(observed - expected_design_px) <= tolerance_design_px else "outside_tolerance"}


def compare_length_range(length_px: float, *, min_px: float, max_px: float) -> dict:
    """Compare already verified measurements in the same pixel unit, including both endpoints."""
    if not all(_finite_number(value) for value in (length_px, min_px, max_px)):
        raise ValueError("length and range endpoints must be finite numbers")
    if min_px < 0 or max_px < min_px:
        raise ValueError("pixel range must have ordered nonnegative endpoints")
    return {"observed_px": length_px, "min_px": min_px, "max_px": max_px,
            "inclusive": True,
            "status": "within_range" if min_px <= length_px <= max_px else "outside_range"}
