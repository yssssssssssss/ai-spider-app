"""
采集闭环桥接模块
任务启动后，后台监控 data/ 目录新文件，上传 OSS 后自动入库，入库后自动触发 LLM 分析
"""
import os
import time
import threading
import asyncio
from uuid import UUID
from datetime import UTC, datetime
from app.database import SessionLocal
from app import crud, schemas
from app.services.goal_validator import missing_goal_failure_reason, validate_task_run_goals
from app.services.task_events import push_event, task_event
from app.services.oss_uploader import oss_uploader


def _is_collectable_image_file(filename: str) -> bool:
    if filename.startswith("_temp_"):
        return False
    return filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))


def _trigger_analysis(image_id: UUID):
    """入库后异步触发 LLM 分析（在新线程中运行 asyncio）"""
    def _run():
        from app.routers.images import _analyze_and_embed
        try:
            asyncio.run(_analyze_and_embed(image_id))
            print(f"🧠 LLM 分析完成: image {image_id}")
        except Exception as e:
            print(f"⚠️ LLM 自动分析失败 {image_id}: {e}")

    t = threading.Thread(target=_run, daemon=True, name=f"analyze-{str(image_id)[:8]}")
    t.start()


def _finish_run(db, task_uuid: UUID, run_uuid: UUID | None, status: str, *, exit_code: int | None = None, failure_reason: str | None = None):
    now = datetime.now(UTC).replace(tzinfo=None)
    task = crud.get_task(db, task_uuid)
    goal_validation = None
    final_status = status
    final_failure_reason = failure_reason
    if status == "completed" and task:
        images = [image for image in task.images if run_uuid is None or image.task_run_id == run_uuid]
        goal_validation = validate_task_run_goals(task, images)
        missing_reason = missing_goal_failure_reason(goal_validation)
        if missing_reason:
            final_status = "failed"
            final_failure_reason = missing_reason

    crud.update_task_status(db, task_uuid, "completed" if final_status == "completed" else "failed")
    if run_uuid:
        crud.update_task_run(
            db,
            run_uuid,
            status=final_status,
            completed_at=now,
            exit_code=exit_code,
            failure_reason=final_failure_reason,
            goal_validation_json=goal_validation,
        )
        crud.release_device_for_run(db, run_uuid)


def _watch_and_upload(
    task_id: str,
    project_root: str,
    process=None,
    interval: int = 5,
    timeout: int = 600,
    idle_threshold: int = 60,
    output_dir: str | None = None,
    task_run_id: str | None = None,
    device_id: str | None = None,
):
    """
    后台线程：监控 data/ 目录新截图并自动入库

    Args:
        task_id: 关联的任务 UUID（字符串）
        project_root: 项目根目录路径
        interval: 扫描间隔（秒）
        timeout: 最大监控时长（秒）
        process: 采集子进程，提供退出码用于失败判定
        idle_threshold: 连续无新文件多少秒后标记任务完成（秒）
    """
    data_dir = output_dir or os.path.join(project_root, "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(project_root, data_dir)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)

    # 记录启动时已存在的文件，避免重复入库
    known_files = set()
    for root, _, files in os.walk(data_dir):
        for f in files:
            if _is_collectable_image_file(f):
                known_files.add(os.path.join(root, f))

    start_time = time.time()
    last_new_file_time = start_time
    task_uuid = UUID(task_id)
    run_uuid = UUID(task_run_id) if task_run_id else None
    device_uuid = UUID(device_id) if device_id else None
    total_new = 0

    while time.time() - start_time < timeout:
        time.sleep(interval)

        db = SessionLocal()
        try:
            returncode = process.poll() if process is not None else None
            if returncode is not None and returncode != 0:
                _finish_run(db, task_uuid, run_uuid, "failed", exit_code=returncode, failure_reason=f"process exited with {returncode}")
                print(f"❌ 任务 {task_id} 采集进程失败，退出码: {returncode}")
                push_event(task_id, task_event("error", message=f"process exited with {returncode}"))
                push_event(task_id, task_event("done"))
                break

            current_files = set()
            for root, _, files in os.walk(data_dir):
                for f in files:
                    if _is_collectable_image_file(f):
                        current_files.add(os.path.join(root, f))

            new_files = current_files - known_files
            if new_files:
                last_new_file_time = time.time()
                for file_path in new_files:
                    rel_path = os.path.relpath(file_path, project_root)
                    task = crud.get_task(db, task_uuid)
                    existing = crud.get_image_by_file_and_task(db, rel_path, task_uuid)

                    # 上传到京东云 OSS
                    oss_url = existing.oss_url if existing else None
                    oss_key = existing.oss_key if existing else None
                    if not oss_url:
                        try:
                            result = oss_uploader.upload(file_path, scenario_name="screenshot")
                            if result.get("success"):
                                oss_url = result.get("url")
                                oss_key = result.get("key")
                                print(f"  ☁️  OSS 上传成功: {oss_url}")
                            else:
                                print(f"  ⚠️ OSS 上传失败: {result.get('error')}")
                        except Exception as e:
                            print(f"  ⚠️ OSS 上传异常: {e}")

                    image_in = schemas.ImageCreate(
                        file_path=rel_path,
                        oss_url=oss_url,
                        oss_key=oss_key,
                        source_app=(task.target_app if task else None),
                        scenario=(task.target_scenario if task else None),
                        captured_at=datetime.now(UTC).replace(tzinfo=None),
                        task_id=task_uuid,
                        task_run_id=run_uuid,
                        device_id=device_uuid,
                    )
                    try:
                        db_image = crud.create_image(db, image_in)
                        total_new += 1
                        print(f"📸 自动入库: {rel_path} -> task {task_id}")
                        # SSE 推送：新截图入库
                        push_event(task_id, task_event("new_image", count=total_new, image_id=str(db_image.id)))
                        if not db_image.analysis or db_image.analysis.status in ("pending", "failed"):
                            _trigger_analysis(db_image.id)
                    except Exception as e:
                        print(f"⚠️ 入库失败 {rel_path}: {e}")

            known_files = current_files

            process_done = process is None or process.poll() is not None
            if time.time() - last_new_file_time > idle_threshold and process_done:
                task = crud.get_task(db, task_uuid)
                if run_uuid:
                    image_count = sum(1 for image in (task.images if task else []) if image.task_run_id == run_uuid)
                else:
                    image_count = len(task.images) if task else 0
                if image_count == 0:
                    _finish_run(db, task_uuid, run_uuid, "failed", failure_reason="no images collected")
                    print(f"❌ 任务 {task_id} 未采集到截图")
                    push_event(task_id, task_event("error", message="no images collected"))
                else:
                    _finish_run(db, task_uuid, run_uuid, "completed", exit_code=returncode)
                    print(f"✅ 任务 {task_id} 采集完成（{idle_threshold}秒无新文件）")
                push_event(task_id, task_event("done", status=crud.get_task(db, task_uuid).status if task_uuid else None))
                break

            # 检查任务是否已被手动标记为 completed/failed
            task = crud.get_task(db, task_uuid)
            if task and task.status in ("completed", "failed"):
                print(f"🔚 任务 {task_id} 已结束，停止监控")
                push_event(task_id, task_event("done", status=task.status))
                break
        finally:
            db.close()
    else:
        db = SessionLocal()
        try:
            _finish_run(db, task_uuid, run_uuid, "timeout", failure_reason="collection timeout")
            push_event(task_id, task_event("error", message="collection timeout"))
            push_event(task_id, task_event("done", status="failed"))
        finally:
            db.close()


def start_collection_watcher(
    task_id: str,
    project_root: str,
    process=None,
    *,
    output_dir: str | None = None,
    task_run_id: str | None = None,
    device_id: str | None = None,
):
    """
    启动后台线程监控截图目录
    """
    t = threading.Thread(
        target=_watch_and_upload,
        args=(task_id, project_root, process, 5, 600, 60, output_dir, task_run_id, device_id),
        daemon=True,
        name=f"collector-watch-{task_id[:8]}"
    )
    t.start()
    print(f"🔍 启动采集监控: task={task_id}")
