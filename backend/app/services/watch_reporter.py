import json
from datetime import date

from app.services.task_planner import _planner_client, planner_chat_completion_options


def _clip(text: str | None, limit: int = 600) -> str:
    if not text:
        return ""
    normalized = " ".join(text.split())
    return normalized[:limit]


def _json_from_text(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _dynamic_analysis_text(analysis) -> str:
    data = analysis.custom_analysis_json if analysis and isinstance(analysis.custom_analysis_json, dict) else {}
    return "\n".join(
        row.get("analysis", "")
        for row in data.get("results", [])
        if isinstance(row, dict) and row.get("analysis")
    ).strip()


class WatchReporter:
    def summarize_daily(self, plan, run, primary_image, previous_summary=None) -> dict:
        analysis = primary_image.analysis
        design = analysis.design_analysis if analysis else ""
        ops = analysis.ops_analysis if analysis else ""
        multi = _dynamic_analysis_text(analysis)
        fallback = self._fallback_daily(plan, run, design, ops, previous_summary, multi=multi)
        try:
            client, model = _planner_client()
            response = client.chat.completions.create(
                **planner_chat_completion_options(
                    model=model,
                    messages=[
                        {"role": "system", "content": self._daily_system_prompt()},
                        {"role": "user", "content": json.dumps({
                            "观察名称": plan.name,
                            "目标App": plan.target_app,
                            "目标页面": plan.target_page,
                            "关注问题": plan.focus_question or "",
                            "运行日期": run.run_date.isoformat(),
                            "今日多维分析": multi,
                            "今日设计分析": design or "",
                            "今日运营分析": ops or "",
                            "昨日摘要": previous_summary.summary if previous_summary else "",
                            "昨日变化": previous_summary.changes_from_previous_json if previous_summary else {},
                        }, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    max_tokens=1200,
                ),
            )
            parsed = _json_from_text(response.choices[0].message.content or "")
            return self._normalize_daily(parsed, fallback)
        except Exception as e:
            print(f"⚠️ 持续观察日报生成失败，使用兜底摘要: {e}")
            return fallback

    def summarize_period(self, plan, summaries: list, period_days: int, date_from: date, date_to: date) -> dict:
        fallback = self._fallback_period(plan, summaries, period_days, date_from, date_to)
        try:
            client, model = _planner_client()
            response = client.chat.completions.create(
                **planner_chat_completion_options(
                    model=model,
                    messages=[
                        {"role": "system", "content": self._period_system_prompt()},
                        {"role": "user", "content": json.dumps({
                            "观察名称": plan.name,
                            "目标App": plan.target_app,
                            "目标页面": plan.target_page,
                            "关注问题": plan.focus_question or "",
                            "周期天数": period_days,
                            "周期": [date_from.isoformat(), date_to.isoformat()],
                            "每日摘要": [
                                {
                                    "日期": summary.run.run_date.isoformat(),
                                    "综合摘要": summary.summary,
                                    "设计摘要": summary.design_summary,
                                    "运营摘要": summary.ops_summary,
                                    "变化": summary.changes_from_previous_json,
                                }
                                for summary in summaries
                            ],
                        }, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    max_tokens=1400,
                ),
            )
            parsed = _json_from_text(response.choices[0].message.content or "")
            if not parsed:
                return fallback
            return {
                "report": str(parsed.get("report") or fallback["report"]),
                "structured_json": parsed.get("structured_json") or fallback["structured_json"],
            }
        except Exception as e:
            print(f"⚠️ 持续观察周期报告生成失败，使用兜底报告: {e}")
            return fallback

    def _daily_system_prompt(self) -> str:
        return """你是电商竞品持续观察分析师。请只输出一个JSON对象：
{
  "summary": "今日页面整体摘要，120-250字",
  "design_summary": "设计侧摘要，80-180字",
  "ops_summary": "运营侧摘要，80-180字",
  "key_modules_json": [{"name": "模块名", "note": "观察"}],
  "promotions_json": [{"name": "促销或利益点", "note": "观察"}],
  "changes_from_previous_json": {"added": [], "removed": [], "strengthened": [], "weakened": [], "note": "与昨日相比"}
}
不要输出Markdown，不要输出解释。"""

    def _period_system_prompt(self) -> str:
        return """你是电商竞品周期观察分析师。请只输出一个JSON对象：
{
  "report": "面向运营和设计团队的周期分析报告，说明最近持续在做什么、中间发生了什么变化、哪些策略稳定存在，250-500字",
  "structured_json": {
    "continuous_actions": [],
    "key_changes": [],
    "stable_modules": [],
    "short_term_campaigns": [],
    "design_takeaways": [],
    "ops_takeaways": []
  }
}
不要输出Markdown，不要输出解释。"""

    def _normalize_daily(self, parsed: dict | None, fallback: dict) -> dict:
        if not parsed:
            return fallback
        return {
            "summary": str(parsed.get("summary") or fallback["summary"]),
            "design_summary": str(parsed.get("design_summary") or fallback["design_summary"]),
            "ops_summary": str(parsed.get("ops_summary") or fallback["ops_summary"]),
            "key_modules_json": parsed.get("key_modules_json") or fallback["key_modules_json"],
            "promotions_json": parsed.get("promotions_json") or fallback["promotions_json"],
            "changes_from_previous_json": parsed.get("changes_from_previous_json") or fallback["changes_from_previous_json"],
        }

    def _fallback_daily(self, plan, run, design: str | None, ops: str | None, previous_summary=None, multi: str | None = None) -> dict:
        design_text = _clip(design)
        ops_text = _clip(ops)
        multi_text = _clip(multi)
        baseline = "首次观察，暂无昨日基线。" if not previous_summary else "已基于昨日摘要形成对比，需结合截图复核细节变化。"
        return {
            "summary": f"{plan.target_app}「{plan.target_page}」在 {run.run_date.isoformat()} 完成首屏观察。{baseline}",
            "design_summary": design_text or multi_text or "暂无可用设计分析。",
            "ops_summary": ops_text or multi_text or "暂无可用运营分析。",
            "key_modules_json": [],
            "promotions_json": [],
            "changes_from_previous_json": {
                "added": [],
                "removed": [],
                "strengthened": [],
                "weakened": [],
                "note": baseline,
            },
        }

    def _fallback_period(self, plan, summaries: list, period_days: int, date_from: date, date_to: date) -> dict:
        count = len(summaries)
        return {
            "report": (
                f"{plan.target_app}「{plan.target_page}」在 {date_from.isoformat()} 至 {date_to.isoformat()} "
                f"共沉淀 {count} 条有效日报。当前为自动兜底报告：请重点查看每日摘要中的设计侧、运营侧和昨日变化字段。"
            ),
            "structured_json": {
                "continuous_actions": [],
                "key_changes": [],
                "stable_modules": [],
                "short_term_campaigns": [],
                "design_takeaways": [],
                "ops_takeaways": [],
                "period_days": period_days,
                "summary_count": count,
            },
        }


watch_reporter = WatchReporter()
