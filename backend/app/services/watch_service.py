import os
import threading
import time
from datetime import date, datetime
from uuid import UUID

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.services.devices import refresh_devices
from app.services.task_runner import start_task_process
from app.services.watch_reporter import watch_reporter


TERMINAL_ANALYSIS_STATUSES = {"success", "partial", "failed", "skipped"}
VALID_ANALYSIS_STATUSES = {"success", "partial"}
WATCH_ADMIN_ID = "watch-scheduler"

_scheduler_started = False


def build_watch_prompt(plan) -> str:
    focus = plan.focus_question or "无"
    return f"""你正在执行固定页面观察任务。

目标 App：{plan.target_app}
目标页面：{plan.target_page}
进入路径：{plan.entry_instruction}
关注问题：{focus}
采集范围：页面加载完成后的首屏。

执行规则：
1. 只采集目标页面首屏
2. 不要滚动
3. 不要进入商品详情页
4. 不要重复截图
5. 如果出现无关弹窗，关闭后继续进入目标页面
6. 如果弹窗本身与关注问题直接相关，先截图记录弹窗，再关闭弹窗继续进入目标页面
7. 完成目标页首屏截图后结束"""


def _is_visible_image(image) -> bool:
    return not os.path.basename(image.file_path).startswith("_temp_")


def _task_images(task) -> list:
    return sorted(
        [image for image in (task.images or []) if _is_visible_image(image)],
        key=lambda image: image.created_at or datetime.min,
    )


def _terminal_analyses_ready(task) -> bool:
    images = _task_images(task)
    if not images:
        return True
    return all(image.analysis and image.analysis.status in TERMINAL_ANALYSIS_STATUSES for image in images)


def _wait_for_analyses(db, task_id: UUID, timeout_seconds: int = 180):
    deadline = time.time() + timeout_seconds
    task = crud.get_task(db, task_id)
    while task and time.time() < deadline:
        db.refresh(task)
        if _terminal_analyses_ready(task):
            return task
        time.sleep(3)
        task = crud.get_task(db, task_id)
    return task


def _latest_period_dates(summaries: list) -> tuple[date, date]:
    dates = [summary.run.run_date for summary in summaries]
    return min(dates), max(dates)


def _refresh_period_reports(db, plan):
    for period_days in (7, 30):
        summaries = crud.list_watch_daily_summaries(db, plan.id, limit=period_days)
        if not summaries:
            continue
        summaries = list(reversed(summaries))
        date_from, date_to = _latest_period_dates(summaries)
        result = watch_reporter.summarize_period(plan, summaries, period_days, date_from, date_to)
        crud.create_watch_period_report(
            db,
            plan.id,
            period_days=period_days,
            date_from=date_from,
            date_to=date_to,
            report=result["report"],
            structured_json=result["structured_json"],
        )


def _finalize_success(db, run):
    task = _wait_for_analyses(db, run.task_id)
    if not task:
        _handle_failure(run.id, "关联任务不存在")
        return

    images = _task_images(task)
    valid_images = [
        image for image in images
        if image.analysis and image.analysis.status in VALID_ANALYSIS_STATUSES
    ]
    if not valid_images:
        _handle_failure(run.id, "未找到有效目标页截图")
        return

    primary_image = valid_images[0]
    crud.create_watch_snapshot(
        db,
        run.id,
        primary_image.id,
        is_primary=True,
        page_signature=primary_image.file_path,
    )

    previous_run = crud.get_latest_success_watch_run_before(db, run.watch_plan_id, run.run_date)
    previous_summary = previous_run.daily_summary if previous_run else None
    daily = watch_reporter.summarize_daily(run.plan, run, primary_image, previous_summary)
    crud.create_watch_daily_summary(
        db,
        run.id,
        summary=daily["summary"],
        design_summary=daily["design_summary"],
        ops_summary=daily["ops_summary"],
        key_modules_json=daily["key_modules_json"],
        promotions_json=daily["promotions_json"],
        changes_from_previous_json=daily["changes_from_previous_json"],
    )

    now = datetime.now()
    crud.update_watch_run(
        db,
        run.id,
        status="success",
        screenshot_count=len(images),
        valid_snapshot_count=1,
        completed_at=now,
    )
    plan = crud.get_watch_plan(db, run.watch_plan_id)
    if plan:
        plan.last_run_at = now
        plan.updated_at = now
        db.commit()
        db.refresh(plan)
        _refresh_period_reports(db, plan)


def _schedule_retry(run_id: UUID):
    timer = threading.Timer(600, retry_watch_run, args=(run_id,))
    timer.daemon = True
    timer.start()


def _handle_failure(run_id: UUID, reason: str):
    db = SessionLocal()
    try:
        run = crud.get_watch_run(db, run_id)
        if not run:
            return
        if run.attempt_count < 2:
            run.status = "pending"
            run.attempt_count += 1
            run.failure_reason = reason
            db.commit()
            _schedule_retry(run.id)
            return

        now = datetime.now()
        crud.update_watch_run(db, run.id, status="failed", failure_reason=reason, completed_at=now)
        plan = crud.get_watch_plan(db, run.watch_plan_id)
        if plan:
            plan.status = "paused"
            plan.pause_reason = reason
            plan.updated_at = now
            db.commit()
    finally:
        db.close()


def _monitor_watch_run(run_id: UUID, timeout_seconds: int = 900):
    db = SessionLocal()
    try:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            run = crud.get_watch_run(db, run_id)
            if not run or not run.task_id:
                return
            task = crud.get_task(db, run.task_id)
            if not task:
                _handle_failure(run.id, "关联任务不存在")
                return
            db.refresh(task)
            if task.status == "completed":
                _finalize_success(db, run)
                return
            if task.status == "failed":
                _handle_failure(run.id, "AutoGLM 采集任务失败")
                return
            time.sleep(5)
        _handle_failure(run_id, "观察运行超时")
    finally:
        db.close()


def _start_monitor(run_id: UUID):
    thread = threading.Thread(target=_monitor_watch_run, args=(run_id,), daemon=True, name=f"watch-run-{str(run_id)[:8]}")
    thread.start()


def start_watch_run(db, run, *, start_process: bool = True, user_id: UUID | None = None):
    plan = crud.get_watch_plan(db, run.watch_plan_id)
    if not plan:
        raise ValueError("Watch plan not found")

    prompt = build_watch_prompt(plan)
    task = crud.create_task(
        db,
        name=f"[持续观察] {plan.name} {run.run_date.isoformat()}",
        keyword=plan.focus_question or "",
        target_app=plan.target_app,
        target_scenario=plan.target_page,
        admin_id=WATCH_ADMIN_ID,
        mode="autoglm",
        created_by=user_id or plan.created_by,
        approved_by=user_id or plan.created_by,
    )
    crud.update_task_instruction(db, task.id, prompt)
    task = crud.get_task(db, task.id)
    crud.update_task_status(db, task.id, "running")
    run = crud.update_watch_run(db, run.id, status="running", task_id=task.id)

    if not start_process:
        return run

    refresh_devices(db)
    device = crud.acquire_device(db)
    if not device:
        crud.update_task_status(db, task.id, "failed")
        _handle_failure(run.id, "No available device")
        return run
    task_run = crud.create_task_run(db, task.id, device_id=device.id, created_by=user_id or plan.created_by)
    if not crud.mark_device_busy(db, device.id, task_run.id):
        crud.update_task_status(db, task.id, "failed")
        crud.update_task_run(db, task_run.id, status="failed", failure_reason="Device is busy")
        _handle_failure(run.id, "Device is busy")
        return run

    try:
        start_task_process(task, prompt=prompt, task_run=task_run, created_by=user_id or plan.created_by, device=device)
    except Exception as e:
        crud.update_task_status(db, task.id, "failed")
        crud.update_task_run(db, task_run.id, status="failed", failure_reason=str(e))
        crud.release_device_for_run(db, task_run.id)
        _handle_failure(run.id, str(e))
        return run

    _start_monitor(run.id)
    return run


def retry_watch_run(run_id: UUID):
    db = SessionLocal()
    try:
        run = crud.get_watch_run(db, run_id)
        if not run or run.status != "pending":
            return
        start_watch_run(db, run)
    finally:
        db.close()


def run_due_watch_plans(db, now: datetime | None = None, *, start_process: bool = True) -> int:
    now = now or datetime.now()
    created = 0
    plans = crud.list_watch_plans(db, status="active", limit=1000)
    for plan in plans:
        if plan.schedule_time > now.time():
            continue
        if plan.created_at and plan.created_at.date() == now.date() and plan.created_at.time() > plan.schedule_time:
            continue
        run = crud.get_watch_run_by_date(db, plan.id, now.date())
        if run:
            continue
        run = crud.create_watch_run(db, plan.id, now.date())
        start_watch_run(db, run, start_process=start_process)
        created += 1
    return created


def _scheduler_loop():
    while True:
        db = SessionLocal()
        try:
            run_due_watch_plans(db)
        except Exception as e:
            print(f"⚠️ 持续观察调度失败: {e}")
        finally:
            db.close()
        time.sleep(max(10, settings.WATCH_SCHEDULER_INTERVAL_SECONDS))


def start_watch_scheduler():
    global _scheduler_started
    if _scheduler_started or not settings.WATCH_SCHEDULER_ENABLED:
        return
    _scheduler_started = True
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="watch-scheduler")
    thread.start()
