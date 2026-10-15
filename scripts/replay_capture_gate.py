"""Replay capture metadata against page_error ground truth without model calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.h5_capture_gate import classify


def replay(path):
    results = json.loads(Path(path).read_text(encoding="utf-8"))["results"]
    matrix, reasons, degraded = Counter(), Counter(), Counter()
    for result in results:
        gate = classify(result.get("capture") or {})
        error = result.get("status") == "page_error"
        blocked = gate["verdict"] == "blocked"
        matrix[(error, blocked)] += 1
        if blocked:
            reasons[gate["reason"]] += 1
            if not error:
                print("FALSE POSITIVE:", result["venue"]["venue_id"], gate["reason"])
        elif gate["verdict"] == "degraded":
            degraded[gate["reason"]] += 1
    print(f"total: {len(results)}")
    print("ground truth       blocked  not_blocked")
    print(f"page_error         {matrix[(True, True)]:7d}  {matrix[(True, False)]:11d}")
    print(f"valid              {matrix[(False, True)]:7d}  {matrix[(False, False)]:11d}")
    print("blocked by_reason:", json.dumps(dict(sorted(reasons.items())), ensure_ascii=False))
    print("degraded by_reason:", json.dumps(dict(sorted(degraded.items())), ensure_ascii=False))
    return 1 if matrix[(False, True)] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    sys.exit(replay(parser.parse_args().results))
