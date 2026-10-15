"""Conservative, deterministic checks of H5 capture metadata (no I/O)."""
import re


# Order gives specific page failures precedence over generic capture failures.
# The three legacy titles are verified against the 408-venue batch. A bare
# “提示” is only a fallback for old captures without first_screen_text.
PATTERNS = (
    ("login_required", "blocked", "页面要求登录，请登录后重新采集。", (
        ("page_title", r"^京东登录注册$"),
        ("navigation_status", r"^login_required$"),
        ("navigation_url", r"^https://(?:plogin\.m|passport)\.jd\.com/(?:login|new/login)(?:/|\?|$)"),
        ("first_screen_text", r"京东登录注册|(?:^|\n)\s*(?:请先登录|请登录)(?:[，。!！]|$)|(?:请先登录|请登录|登录后).{0,8}(?:预览|查看|浏览)|(?:^|\n)\s*登录[ /]*注册\s*(?:$|\n)"),
    )),
    ("venue_lost", "blocked", "活动迷路了，未采到目标会场，请检查预览链接后重新采集。", (
        ("page_title", r"^挑好物逛京东$"),
        ("navigation_status", r"^unverified_redirect$"),
        ("error_type", r"^NavigationReachedAnotherVenue$"),
        ("first_screen_text", r"活动迷路"),
    )),
    ("expired", "blocked", "活动已过期或已结束，暂不支持预览，请检查预览时间。", (
        ("page_title", r"^(?:提示|活动已过期|活动已结束)$"),
        ("first_screen_text", r"暂不支持预览|活动.{0,12}(?:已过期|已结束)|(?:已过期|已结束).{0,8}活动|^(?:已过期|已结束)$"),
    )),
    ("capture_failed", "blocked", "采集失败，请重新采集。", (
        ("capture_status", r"^failed$"), ("error_type", r"\S"),
    )),
    ("not_ready", "blocked", "页面所有截图均加载超时且仍有图片未加载，请重新采集。", ()),
    ("floor_error", "degraded", "页面出现楼层异常，相关规则需待正常展示后复核。", (
        ("page_title", r"楼层异常"),
        ("first_screen_text", r"楼层异常"),
    )),
)


def classify(capture: dict) -> dict:
    matches = []
    screens = capture.get("screens") or []
    for reason, verdict, message, patterns in PATTERNS:
        signals = []
        for field, pattern in patterns:
            value = capture.get(field)
            if field == "page_title" and isinstance(value, str) and value.strip() == "提示" and "first_screen_text" in capture:
                continue
            if isinstance(value, str) and re.search(pattern, value.strip()):
                signals.append(f"{field}:{value.strip()[:160]}")
        if reason == "not_ready" and screens and all(
                s.get("load_wait_timed_out") is True and (s.get("pending_visible_images") or 0) > 0
                for s in screens):
            signals.append("screens:all_load_wait_timed_out_with_pending_images")
        if signals:
            matches.append({"verdict": verdict, "reason": reason, "signals": signals,
                            "message": f"capture_gate:{reason}：{message}"})
    if matches:
        result = matches[0]
        result["signals"] = [signal for match in matches for signal in match["signals"]]
        return result
    return {"verdict": "ok", "reason": None, "signals": [], "message": ""}
