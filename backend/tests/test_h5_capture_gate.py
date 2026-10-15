"""Capture gating uses only metadata and must never guess from ordinary copy."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.h5_capture_gate import classify
from app.services.audit_workspace import parse_h5_results


@pytest.mark.parametrize("capture,reason", [
    ({"page_title": "挑好物逛京东"}, "venue_lost"),
    ({"first_screen_text": "糟糕，活动迷路了"}, "venue_lost"),
    ({"navigation_status": "unverified_redirect", "navigation_url": "https://example.test/other"}, "venue_lost"),
    ({"error_type": "NavigationReachedAnotherVenue", "capture_status": "failed"}, "venue_lost"),
    ({"page_title": "京东登录注册"}, "login_required"),
    ({"navigation_status": "login_required"}, "login_required"),
    ({"navigation_url": "https://plogin.m.jd.com/login/login?returnurl=example"}, "login_required"),
    ({"first_screen_text": "请先登录后查看活动"}, "login_required"),
    ({"first_screen_text": "登录/注册"}, "login_required"),
    ({"page_title": "提示"}, "expired"),
    ({"first_screen_text": "活动已过期"}, "expired"),
    ({"first_screen_text": "已结束的活动，暂不支持预览"}, "expired"),
    ({"first_screen_text": "已过期"}, "expired"),
    ({"first_screen_text": "已结束"}, "expired"),
    ({"first_screen_text": "暂不支持预览"}, "expired"),
    ({"capture_status": "failed"}, "capture_failed"),
    ({"error_type": "ScreenshotTimeout"}, "capture_failed"),
    ({"screens": [{"load_wait_timed_out": True, "pending_visible_images": 2}] * 2}, "not_ready"),
])
def test_strong_failures_are_blocked(capture, reason):
    result = classify(capture)
    assert result["verdict"] == "blocked"
    assert result["reason"] == reason
    assert result["signals"] and result["message"]


@pytest.mark.parametrize("capture", [
    {}, {"page_title": "正常会场", "screens": []},
    {"page_title": "提示", "first_screen_text": "新品上架"},
    {"first_screen_text": "登录领券，会员好礼，秒杀已结束，商品已过期"},
    {"first_screen_text": "请登录领取优惠券"},
    {"navigation_status": "unknown_status", "navigation_url": "https://example.test/unknown"},
    {"navigation_url": "https://example.test/?next=https://plogin.m.jd.com/login/login"},
    {"navigation_url": "https://plogin.m.jd.com.evil.test/login/login"},
    {"navigation_errors": ["Timeout"], "capture_status": "partial"},
    {"screens": [{"load_wait_timed_out": True, "pending_visible_images": 0, "broken_visible_images": 5}]},
    {"screens": [{"load_wait_timed_out": True, "pending_visible_images": 2},
                 {"load_wait_timed_out": False, "pending_visible_images": 0}]},
    {"screens": [{"pending_visible_images": 3}]},
])
def test_unknown_and_partial_signals_do_not_block(capture):
    assert classify(capture) == {"verdict": "ok", "reason": None, "signals": [], "message": ""}


def test_floor_error_is_degraded_and_specific_errors_win():
    assert classify({"first_screen_text": "楼层异常，请稍后重试"})["verdict"] == "degraded"
    gate = classify({"first_screen_text": "活动迷路了，楼层异常"})
    assert gate["reason"] == "venue_lost" and gate["verdict"] == "blocked"
    assert len(gate["signals"]) == 2


@pytest.mark.parametrize(("reason", "expected"), [("venue_lost", "offline"), ("login_required", "login_required"),
                                                  ("expired", "expired"), ("not_ready", "other"), ("capture_failed", "other")])
def test_parser_maps_gate_reason_to_v2_vocabulary(reason, expected):
    audit = {"page_state": "error", "page_warnings": ["活动迷路了"], "capture_gate": {"reason": reason}}
    packet = {"results": [{"venue": {"venue_id": "RA1", "venue_name": "测试"}, "status": "page_error", "audit": audit}]}
    assert parse_h5_results(packet)[0].capture_reason == expected
    del audit["capture_gate"]
    assert parse_h5_results(packet)[0].capture_reason == "offline"


def test_verified_408_metadata_fixture():
    entries = json.loads((Path(__file__).parent / "fixtures/h5_capture_gate_408.json").read_text())
    for entry in entries:
        assert classify(entry["capture"])["reason"] == entry["reason"], entry["venue_id"]
        if entry["reason"] == "expired":
            assert "过期" in " ".join(entry["page_warnings"])
