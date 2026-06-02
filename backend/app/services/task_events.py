"""
任务事件队列共享模块
用于 SSE 实时进度推送
"""
import asyncio
import json
import threading

_task_queues: dict[str, asyncio.Queue] = {}
_loop_refs: dict[str, asyncio.AbstractEventLoop] = {}


def ensure_queue(task_id: str) -> asyncio.Queue:
    if task_id not in _task_queues:
        _task_queues[task_id] = asyncio.Queue()
        # 捕获当前事件循环（FastAPI 主线程）
        try:
            _loop_refs[task_id] = asyncio.get_event_loop()
        except RuntimeError:
            _loop_refs[task_id] = None
    return _task_queues[task_id]


def push_event(task_id: str, message: str):
    """向指定任务的事件队列推送消息（线程安全，支持从子线程调用）"""
    queue = _task_queues.get(task_id)
    if queue is None:
        return
    loop = _loop_refs.get(task_id)
    try:
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(queue.put_nowait, message)
        else:
            queue.put_nowait(message)
    except Exception:
        pass


def task_event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False)


def task_event_type(message: str) -> str | None:
    if message == "DONE":
        return "done"
    if message.startswith("ERROR:"):
        return "error"
    if message.startswith("NEW_IMAGE:"):
        return "new_image"
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None
    return data.get("type")
