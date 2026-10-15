"""Local, serial H5 audit execution. Request hooks leave commits to their caller."""
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

from sqlalchemy import event

from app import models
from app.database import SessionLocal
from app.services import audit_jobs as jobs
from app.services.audit_workspace import create_h5_run
from app.services.audit_evidence import DirectoryEvidenceSource

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ("capture_venues.mjs", "venue_identity.py", "audit_spec_profile.py",
           "rerun_venue_audit.py", "build_venue_recheck_report.py")
STEP_LABELS = {"preflight": "检查登录", "catalog": "读取目录", "capture": "采集",
               "profile": "准备规范", "audit": "审核", "report": "生成报告", "ingest": "收录"}
log = logging.getLogger(__name__)


def safe_error(value: str) -> str:
    # Redact before truncating, so a cut cannot detach a value from its key.
    value = re.sub(r"(?im)\b(?:authorization|cookie|set-cookie)\s*[:=][^\r\n]*", "[REDACTED]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r'''(?ix)([\"']?[\w.-]*(?:token|cookie|key|secret|password)[\w.-]*[\"']?\s*[:=]\s*)
                       (\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&}]+)''', r"\1[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    return value.encode("utf-8")[-2048:].decode("utf-8", errors="ignore")


class Stopped(Exception):
    """The job no longer belongs to the running worker (usually cancellation)."""


class ProcessRunner:
    """All Ego/Python calls and process-group termination pass through this seam."""

    def terminate(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def run(self, args, *, cwd, stdin=None, on_start=None, on_json=None, cancelled=None):
        # Files avoid stdin/stderr pipe deadlocks; stdout is consumed incrementally.
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as errors:
            source.write((stdin or "").encode("utf-8"))
            source.seek(0)
            process = subprocess.Popen(args, cwd=cwd, stdin=source, stdout=subprocess.PIPE, stderr=errors,
                                       text=True, encoding="utf-8", errors="replace", start_new_session=True,
                                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
            try:
                if on_start:
                    on_start(process.pid)
                if cancelled and cancelled.is_set():
                    raise Stopped()
                for line in process.stdout:
                    if on_json:
                        try:
                            message = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(message, dict):
                            on_json(message)
                code = process.wait()
                errors.seek(0, os.SEEK_END)
                size = errors.tell()
                errors.seek(max(0, size - 65536))
                tail = errors.read().decode("utf-8", errors="replace")
                if size > 65536:
                    tail = tail.partition("\n")[2]  # Drop a possibly severed credential.
                return subprocess.CompletedProcess(args, code, stderr=tail)
            finally:
                if process.poll() is None:
                    self.terminate(process.pid)
                process.wait()
                process.stdout.close()


class H5AuditExecutor:
    def __init__(self, runner=None, *, session_factory=SessionLocal, repo=ROOT, python=sys.executable):
        self.runner = runner or ProcessRunner()
        self.sessions = session_factory
        self.repo = Path(repo).resolve()
        self.python = python
        self._guard = threading.Lock()
        self._thread = None
        self._wake_requested = False
        self._cancellations = {}

    def availability(self, spec_version):
        if not shutil.which("ego-browser"):
            return False, "PATH 中未找到 ego-browser"
        missing = [name for name in SCRIPTS if not (self.repo / "scripts" / name).is_file()]
        return (False, "缺少审核脚本：" + "、".join(missing)) if missing else (True, None)

    def _source(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("catalog_dir 必须是 data/ 下的目录")
        path = Path(value)
        if not path.is_absolute():
            path = self.repo / path if path.parts and path.parts[0] == "data" else self.repo / "data" / path
        path = path.resolve()
        if not path.is_relative_to(self.repo / "data"):
            raise ValueError("catalog_dir 必须位于仓库 data/ 下")
        if not all((path / file).is_file() for file in ("catalog.json", "identity-verification.json")):
            raise ValueError("catalog_dir 缺少 catalog.json 或 identity-verification.json")
        return path

    @staticmethod
    def _url(value):
        from urllib.parse import urlsplit

        try:
            url = urlsplit(value if isinstance(value, str) else "")
            valid = (url.scheme == "https" and url.hostname == "yx.jd.com" and
                     url.port in (None, 443) and not url.username and not url.password and
                     value.startswith("https://yx.jd.com/"))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("catalog_url 必须是 https://yx.jd.com/ 下的链接")
        return value

    def start(self, db, job):
        data = job.input_json
        if not isinstance(data, dict) or bool(data.get("catalog_url")) == bool(data.get("catalog_dir")):
            raise ValueError("请提供 catalog_url 或 catalog_dir，二选一")
        if data.get("catalog_url"):
            self._url(data["catalog_url"])
        else:
            self._source(data["catalog_dir"])
        ids = data.get("venue_ids")
        if ids is not None and (not isinstance(ids, list) or any(not isinstance(v, str) or not v for v in ids)):
            raise ValueError("venue_ids 必须是会场 ID 数组")
        job.executor_ref_json = {"work_dir": str(self.repo / "data" / "audit-jobs" / str(job.id)),
                                 "step": "preflight", "space_id": None, "pid": None}
        ahead = db.query(models.AuditJob).filter(models.AuditJob.carrier == "h5",
                    models.AuditJob.status.in_(["queued", "running", "ingesting"]), models.AuditJob.id != job.id).count()
        job.status_detail = f"排队中，前面还有 {ahead} 个"
        self._after_commit(db)

    def resume(self, db, job):
        self._after_commit(db)

    def reconcile(self, db, job):
        self._after_commit(db)

    def _after_commit(self, db):
        # start/resume are called before the row is visible to a separate SessionLocal.
        rolled_back = False

        def rollback(session):
            nonlocal rolled_back
            rolled_back = True

        def commit(session):
            if not rolled_back:
                self._wake()

        event.listen(db, "after_rollback", rollback, once=True)
        event.listen(db, "after_commit", commit, once=True)

    def _wake(self):
        with self._guard:
            self._wake_requested = True
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, name="h5-audit", daemon=True)
                self._thread.start()

    def _cancel_event(self, job_id):
        with self._guard:
            return self._cancellations.setdefault(job_id, threading.Event())

    def cancel(self, db, job):
        self._cancel_event(job.id).set()
        ref = job.executor_ref_json or {}
        if ref.get("pid"):
            self.runner.terminate(ref["pid"])
        self._finish(job.id, ref.get("space_id"))
        job.executor_ref_json = {**ref, "pid": None}

    def on_startup(self):
        spaces = []
        with self.sessions() as db:
            ids = [row.id for row in db.query(models.AuditJob).filter_by(carrier="h5").filter(
                models.AuditJob.status.in_(["running", "ingesting"])).order_by(models.AuditJob.id)]
            for job_id in ids:
                job = jobs._lock_job(db, job_id)
                if job.status in {"running", "ingesting"}:
                    jobs.transition_job(job, "failed", status_detail="执行中断：后端重启", error="执行中断：后端重启")
                    ref = job.executor_ref_json or {}
                    spaces.append((job.id, ref.get("space_id")))
                    job.executor_ref_json = {**ref, "pid": None}
                db.commit()
        for job_id, space_id in spaces:
            self._finish(job_id, space_id)
        self._wake()

    def _update(self, job_id, *, step=None, detail=None, status=None, **ref):
        with self.sessions() as db:
            job = jobs._lock_job(db, job_id)
            if job.status not in {"running", "ingesting"} or self._cancel_event(job_id).is_set():
                raise Stopped()
            if status and status != job.status:
                jobs.transition_job(job, status)
            if detail is not None:
                job.status_detail = detail
            job.executor_ref_json = {**(job.executor_ref_json or {}), **ref,
                                     **({"step": step} if step else {})}
            db.commit()

    def _work(self):
        try:
            while True:
                with self._guard:
                    self._wake_requested = False
                with self.sessions() as db:
                    pending = db.query(models.AuditJob).filter_by(carrier="h5").filter(
                        models.AuditJob.status.in_(["queued", "running"])).order_by(
                            models.AuditJob.created_at, models.AuditJob.id).all()
                    job_id = pending[0].id if pending else None
                    # Lock in UUID order, matching API list/project reads.
                    positions = {job.id: i for i, job in enumerate(pending)}
                    for pending_id in sorted(positions):
                        job = jobs._lock_job(db, pending_id)
                        if job.status == "queued":
                            job.status_detail = f"排队中，前面还有 {positions[pending_id]} 个"
                    db.commit()
                if job_id is None:
                    with self._guard:
                        if self._wake_requested:
                            continue
                        self._thread = None
                        return
                self._execute(job_id)
        except Exception:
            log.exception("H5 audit worker stopped")
        finally:
            # A commit racing with shutdown must still be able to start a worker.
            with self._guard:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _command(self, job_id, step, args, *, stdin=None, total=0):
        self._update(job_id, step=step, detail=STEP_LABELS[step])
        messages, seen = [], set()

        def on_json(message):
            messages.append(message)
            if message.get("space_id") is not None:
                self._update(job_id, space_id=message["space_id"])
            if message.get("stage") in {"captured", "audited", "failed"} and message.get("record_id"):
                seen.add(message["record_id"])
                self._update(job_id, detail=f"{STEP_LABELS[step]} {len(seen)}/{total}")
            if message.get("stage") == "replay_finished":
                self._update(job_id, detail=f"审核 {message['completed']}/{message['total']}")

        result = self.runner.run(args, cwd=self.repo, stdin=stdin,
            on_start=lambda pid: self._update(job_id, pid=pid), on_json=on_json,
            cancelled=self._cancel_event(job_id))
        self._update(job_id, pid=None)
        if result.returncode:
            raise RuntimeError(result.stderr or f"{step} 子进程退出：{result.returncode}")
        if any(m.get("stage") == "replay_finished" and m.get("failed", 0) for m in messages):
            raise RuntimeError("部分会场审核失败，请查看审核目录中的 audit-error.json")
        return messages

    def _preflight(self, job_id, url, space_id):
        # A space handed off for login must be taken back before reuse.
        opener = f"takeOverTaskSpace({json.dumps(space_id)})" if space_id else f"taskSpace({json.dumps('audit-job-' + str(job_id))})"
        script = f'''
const task = await {opener};
console.log(JSON.stringify({{space_id: task.spaceId}}));
const page = task.page("p1");
try {{ await page.goto({json.dumps(url)}); }} catch {{}}
let ready = false;
try {{
  await page.waitForFunction(() => [...document.querySelectorAll("table")].some(
    t => t.innerText.includes("会场名称/ID/通天塔项目ID")), undefined, {{timeout: 10000}});
  ready = await page.evaluate(() => [...document.querySelectorAll("table")].some(
    t => t.innerText.includes("会场名称/ID/通天塔项目ID")));
}} catch {{}}
if (!ready) await task.handOff();
console.log(JSON.stringify({{stage: "preflight", space_id: task.spaceId, ready}}));
'''
        messages = self._command(job_id, "preflight", ["ego-browser", "nodejs"], stdin=script)
        result = next(m for m in reversed(messages) if m.get("stage") == "preflight")
        if not result["ready"]:
            self._update(job_id, status="needs_action", detail=
                f"已在 Ego Lite 的 TaskSpace {result['space_id']} 打开提报列表，请登录后点继续")
            raise Stopped()
        return result["space_id"]

    def _capture(self, job_id, step, capture, space_id, records=None, total=0):
        options = {"VENUE_SPACE": space_id, "VENUE_ROOT": str(capture), "VENUE_PYTHON": self.python}
        if step == "catalog":
            options["VENUE_MODE"] = "catalog"
        if records:
            options["VENUE_RECORDS_FILE"] = str(records)
        script = "globalThis.venueCapture = " + json.dumps(options) + ";\n"
        script += (self.repo / "scripts/capture_venues.mjs").read_text(encoding="utf-8")
        self._command(job_id, step, ["ego-browser", "nodejs"], stdin=script, total=total)

    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _selection(self, source, venue_ids):
        venues = self._read(source / "catalog.json")["venues"]
        ids, records = set(), set()
        for venue in venues:
            record = venue["record_id"]
            if (venue["venue_id"] in ids or record in records or not re.fullmatch(r"[\w-]+", record)):
                raise ValueError("目录中有重复或无效的会场身份")
            ids.add(venue["venue_id"])
            records.add(record)
        unknown = sorted(set(venue_ids or []) - ids)
        if unknown:
            raise ValueError("不认识的会场 ID：" + "、".join(unknown))
        selected = [v for v in venues if not venue_ids or v["venue_id"] in venue_ids]
        if not selected:
            raise ValueError("目录中没有会场")
        return selected

    def _copy_capture(self, source, capture, selected):
        def copy(relative):
            relative = Path(relative)
            file = (source / relative).resolve()
            destination = capture / relative
            if (relative.is_absolute() or not file.is_relative_to(source) or
                    not destination.resolve().is_relative_to(capture.resolve())):
                raise ValueError("采集文件路径超出 catalog_dir")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)

        for file in ("catalog.json", "identity-verification.json"):
            copy(file)
        catalog = self._read(capture / "catalog.json")
        self._write(capture / "catalog.json", {**catalog, "venues": selected, "selected_venue_count": len(selected)})
        complete = True
        for venue in selected:
            if venue.get("qr_file"):
                copy(venue["qr_file"])
            relative = f"venues/{venue['record_id']}/capture.json"
            if not (source / relative).is_file():
                complete = False
                continue
            copy(relative)
            for screen in self._read(source / relative).get("screens", []):
                copy(screen["file"])
        return complete

    def _execute(self, job_id):
        try:
            with self.sessions() as db:
                job = jobs._lock_job(db, job_id)
                if job.status not in {"queued", "running"} or self._cancel_event(job_id).is_set():
                    return
                if job.status == "queued":
                    jobs.transition_job(job, "running")
                data = dict(job.input_json)
                ref = dict(job.executor_ref_json)
                version = {"rules_json": job.spec_version.rules_json, "source_json": job.spec_version.source_json}
                db.commit()
            work = self.repo / "data/audit-jobs" / str(job_id)
            work.mkdir(parents=True, exist_ok=True)
            capture, output = work / "capture", work / "audit"
            space_id = ref.get("space_id")
            if data.get("catalog_dir"):
                source = self._source(data["catalog_dir"])
                selected = self._selection(source, data.get("venue_ids"))
                complete = self._copy_capture(source, capture, selected)
                url = None if complete else self._url(self._read(capture / "catalog.json").get("source_url"))
            else:
                complete = False
                url = self._url(data["catalog_url"])
            if not complete:
                space_id = self._preflight(job_id, url, space_id)
                if not data.get("catalog_dir"):
                    self._capture(job_id, "catalog", capture, space_id)
                selected = self._selection(capture, data.get("venue_ids"))
            records = work / "records.json"
            self._write(records, {"record_ids": [v["record_id"] for v in selected]})
            if not complete:
                self._capture(job_id, "capture", capture, space_id, records, len(selected))
            spec_input, profile = work / "spec-version.json", work / "profile.json"
            self._write(spec_input, version)
            self._command(job_id, "profile", [self.python, "scripts/audit_spec_profile.py",
                                              "--input", str(spec_input), "--output", str(profile)])
            self._command(job_id, "audit", [self.python, "scripts/rerun_venue_audit.py", "--fresh",
                "--spec", str(profile), "--source", str(capture), "--output", str(output),
                "--records-file", str(records), "--concurrency", "6"], total=len(selected))
            self._command(job_id, "report", [self.python, "scripts/build_venue_recheck_report.py", "--output", str(output)])
            packet = self._read(output / "results.json")
            results = packet.get("results", [])
            if (len(results) != len(selected) or
                    {r["venue"]["record_id"] for r in results} != {v["record_id"] for v in selected} or
                    any(not r.get("audit") or r.get("status") == "pending" for r in results)):
                raise ValueError("审核结果不完整，未收录")
            self._update(job_id, step="ingest", status="ingesting", detail="正在收录")
            with self.sessions() as db:
                job = jobs._lock_job(db, job_id)
                if job.status != "ingesting" or self._cancel_event(job_id).is_set():
                    raise Stopped()
                run = create_h5_run(db, (output / "results.json").read_bytes(), "results.json", job.spec_version,
                    job.name, phase=job.phase, project=db.get(models.AuditProject, job.project_id) if job.project_id else None,
                    user_id=job.created_by, evidence_source=DirectoryEvidenceSource(output))
                jobs.complete_with_run(db, job, run)
                db.commit()
        except Stopped:
            pass
        except Exception as exc:
            with self.sessions() as db:
                job = jobs._lock_job(db, job_id)
                if job.status in jobs.ACTIVE_STATUSES:
                    jobs.transition_job(job, "failed", status_detail="执行失败", error=safe_error(str(exc)))
                    job.executor_ref_json = {**(job.executor_ref_json or {}), "pid": None}
                db.commit()
        finally:
            with self.sessions() as db:
                job = db.get(models.AuditJob, job_id)
                if job is not None and job.status in jobs.TERMINAL_STATUSES:
                    self._finish(job_id, (job.executor_ref_json or {}).get("space_id"))
            with self._guard:
                self._cancellations.pop(job_id, None)

    def _finish(self, job_id, space_id):
        # Lookup by name also covers cancellation before preflight reports its ID.
        script = f'''
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.id === {json.dumps(space_id)} || s.name === {json.dumps('audit-job-' + str(job_id))});
if (existing) {{ const task = await taskSpace(existing.id); await task.finish({{keep: []}}); }}
'''
        try:
            result = self.runner.run(["ego-browser", "nodejs"], cwd=self.repo, stdin=script)
            if result.returncode:
                log.warning("H5 TaskSpace cleanup failed for %s: %s", job_id, safe_error(result.stderr or ""))
        except Exception as exc:
            log.warning("H5 TaskSpace cleanup failed for %s: %s", job_id, safe_error(str(exc)))


_executor = None


def register(**kwargs):
    global _executor
    if _executor is None:
        _executor = H5AuditExecutor(**kwargs)
    jobs.register_executor("h5", _executor)
    return _executor


def on_startup():
    register().on_startup()
