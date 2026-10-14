import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import crud, models
from app.database import engine, get_db, init_db
from app.main import app
from app.services import audit_projects as service
from app.services.auth import create_access_token, hash_password

FIXTURE = Path(__file__).parent / "fixtures" / "audit_projects_h5.json"


class AuditProjectAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "test" not in (engine.url.database or ""):
            raise unittest.SkipTest("Integration tests require a disposable test database")
        init_db()

    def setUp(self):
        # API commits release savepoints; the outer transaction removes every fixture.
        connection = engine.connect()
        transaction = connection.begin()
        self.db = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False)
        self.addCleanup(connection.close)
        self.addCleanup(transaction.rollback)
        self.addCleanup(self.db.close)
        overrides = app.dependency_overrides.copy()
        self.addCleanup(lambda: setattr(app, "dependency_overrides", overrides))

        def test_db():
            yield self.db

        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        password_hash = hash_password("secret-password")
        self.headers = {}
        self.users = {}
        for role in ("viewer", "operator"):
            user = crud.create_user(self.db, username=f"audit-api-{role}-{uuid4().hex}",
                                    password_hash=password_hash, role=role)
            self.users[role] = user
            self.headers[role] = {"Authorization": f"Bearer {create_access_token(user)}"}
        self.project = service.create_project(self.db, "审核项目", "说明", self.users["operator"].id)
        self.db.commit()
        self.project_id = str(self.project.id)

    def request(self, method, url, expected=200, role="operator", **kwargs):
        response = self.client.request(method, url, headers=self.headers.get(role, {}), **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def upload(self, raw=None, venue_ids=None, project_id=None, expected=200, **kwargs):
        data = {} if venue_ids is None else {"venue_ids": venue_ids}
        return self.request("POST", f"/api/audit-projects/{project_id or self.project_id}/imports/h5",
                            expected, files={"file": ("results.json", FIXTURE.read_bytes() if raw is None else raw,
                                                       "application/json")}, data=data, **kwargs)

    def imported_page(self):
        self.upload()
        page = self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"][0]
        return page["id"], page["latest_pre"]["id"]

    def app_run(self, statuses=None, status="completed", completed_at=None, skill=None):
        task = models.Task(name="App审核")
        skill = skill or models.AnalysisSkill(name="截图规范", prompt="巡查", skill_type="inspection", version=3)
        self.db.add_all([task, skill])
        self.db.flush()
        run = models.TaskRun(task_id=task.id, attempt_no=1, status=status,
                             completed_at=completed_at or datetime(2026, 10, 15, 8))
        self.db.add(run)
        self.db.flush()
        self.analysis(task, run, skill, statuses)
        self.db.commit()
        return task, run, skill

    def analysis(self, task, run, skill, statuses):
        image = models.Image(file_path="fixture.png", task_id=task.id, task_run_id=run.id)
        self.db.add(image)
        self.db.flush()
        inspection = None if statuses is None else {"checks": [
            {"rule_id": rule_id, "clause": f"条款 {rule_id}", "status": status,
             "observed": f"{rule_id}: {status}", "reason": f"依据: {status}"}
            for rule_id, status in statuses.items()
        ]}
        self.db.add(models.Analysis(image_id=image.id, skill_id=skill.id, status="done", inspection_json=inspection))
        self.db.flush()
        return image

    def add_record(self, page_id, run, skill, baseline=None, phase="post", expected=200):
        return self.request("POST", f"/api/audit-pages/{page_id}/records/app", expected,
                            json={"task_run_id": str(run.id), "skill_id": str(skill.id),
                                  "baseline_record_id": baseline, "phase": phase})

    def endpoints(self, page_id, record_id, run, skill):
        return [
            ("GET", "/api/audit-projects", {}),
            ("POST", "/api/audit-projects", {"json": {"name": "新项目"}}),
            ("GET", "/api/audit-projects/app-candidates", {}),
            ("GET", f"/api/audit-projects/{self.project_id}", {}),
            ("PATCH", f"/api/audit-projects/{self.project_id}", {"json": {"name": "修改"}}),
            ("DELETE", f"/api/audit-projects/{self.project_id}", {}),
            ("POST", f"/api/audit-projects/{self.project_id}/pages", {"json": {"name": "新页面"}}),
            ("POST", f"/api/audit-projects/{self.project_id}/imports/h5",
             {"files": {"file": ("results.json", FIXTURE.read_bytes(), "application/json")}}),
            ("GET", f"/api/audit-pages/{page_id}", {}),
            ("POST", f"/api/audit-pages/{page_id}/records/app",
             {"json": {"task_run_id": str(run.id), "skill_id": str(skill.id)}}),
            ("PATCH", f"/api/audit-records/{record_id}", {"json": {"note": "备注"}}),
            ("DELETE", f"/api/audit-records/{record_id}", {}),
            ("GET", f"/api/audit-records/{record_id}/compare", {}),
        ]

    def test_unauthenticated_all_endpoints_return_401(self):
        page_id, pre_id = self.imported_page()
        _, run, skill = self.app_run({"OV-009": "pass"})
        post = self.add_record(page_id, run, skill, pre_id)
        for method, url, kwargs in self.endpoints(page_id, post["id"], run, skill):
            with self.subTest(method=method, url=url):
                self.request(method, url, 401, role=None, **kwargs)

    def test_viewer_reads_all_endpoints_but_all_writes_return_403(self):
        page_id, pre_id = self.imported_page()
        _, run, skill = self.app_run({"OV-009": "pass"})
        post = self.add_record(page_id, run, skill, pre_id)
        for method, url, kwargs in self.endpoints(page_id, post["id"], run, skill):
            with self.subTest(method=method, url=url):
                self.request(method, url, 200 if method == "GET" else 403, role="viewer", **kwargs)

    def test_operator_full_flow(self):
        created = self.request("POST", "/api/audit-projects", json={"name": "  全流程  ", "description": "说明"})
        self.project_id = created["id"]
        self.assertEqual(created["name"], "全流程")
        self.assertEqual(created["created_by"], str(self.users["operator"].id))
        self.request("PATCH", f"/api/audit-projects/{self.project_id}", json={"description": None})
        manual = self.request("POST", f"/api/audit-projects/{self.project_id}/pages", json={"name": "手动页面"})
        self.assertEqual(self.upload(), {"created": 3, "skipped": 0, "pages_created": 3})
        self.assertEqual(self.upload(), {"created": 0, "skipped": 3, "pages_created": 0})
        listed = next(row for row in self.request("GET", "/api/audit-projects") if row["id"] == self.project_id)
        self.assertEqual(listed["page_count"], 4)
        self.assertEqual(listed["record_counts"], {"pre": 3, "post": 0, "h5": 3, "app": 0})
        matrix = self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"]
        empty = next(row for row in matrix if row["id"] == manual["id"])
        self.assertEqual((empty["latest_pre"], empty["latest_post"], empty["has_baseline"], empty["compare_counts"]),
                         (None, None, False, None))
        page = next(row for row in matrix if row["business_key"] == "RA092915121822266376")
        page_id, pre_id = page["id"], page["latest_pre"]["id"]
        timeline = self.request("GET", f"/api/audit-pages/{page_id}")
        self.assertIsNone(timeline["comparison"])
        pre = timeline["records"][0]
        self.assertEqual(pre["source_ref_json"]["sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(pre["findings_json"][1]["status"], "disabled")
        task, run, skill = self.app_run({"OV-009": "pass", "NEW": "pass"})
        failed_image = self.analysis(task, run, skill, {"NEW": "fail"})
        self.db.commit()
        candidates = self.request("GET", "/api/audit-projects/app-candidates")
        self.assertEqual(candidates[0], {"task_run_id": str(run.id), "task_name": task.name,
                                        "completed_at": run.completed_at.isoformat(),
                                        "skills": [{"id": str(skill.id), "name": skill.name, "version": 3}]})
        post = self.add_record(page_id, run, skill, pre_id)
        self.assertEqual(post["baseline_record_id"], pre_id)
        self.assertEqual(post["summary_json"]["fail"], 1)
        self.assertEqual(next(item for item in post["findings_json"] if item["rule_id"] == "NEW")["evidence"]["image_ids"],
                         [str(failed_image.id)])
        comparison = self.request("GET", f"/api/audit-records/{post['id']}/compare")
        self.assertEqual(comparison["counts"]["fixed"], 1)
        self.assertEqual(comparison["counts"]["new_issue"], 1)
        self.assertTrue(comparison["spec_mismatch"])
        timeline = self.request("GET", f"/api/audit-pages/{page_id}")
        self.assertEqual([record["id"] for record in timeline["records"]], [pre_id, post["id"]])
        self.assertEqual(timeline["comparison"], comparison)
        matrix = self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"]
        row = next(row for row in matrix if row["id"] == page_id)
        self.assertEqual(row["latest_post"]["id"], post["id"])
        self.assertTrue(row["has_baseline"])
        self.assertEqual(row["compare_counts"], {"fixed": 1, "still_open": 0, "regressed": 0, "new_issue": 1})
        alternative = self.add_record(page_id, run, skill, phase="pre")
        changed = self.request("PATCH", f"/api/audit-records/{post['id']}",
                               json={"baseline_record_id": alternative["id"], "note": "新基线"})
        self.assertEqual(changed["findings_json"], post["findings_json"])
        self.assertEqual(changed["note"], "新基线")
        self.assertEqual(self.request("GET", f"/api/audit-records/{post['id']}/compare")["counts"]["still_open"], 1)
        explicit = self.request("GET", f"/api/audit-records/{post['id']}/compare", params={"pre_id": pre_id})
        self.assertEqual(explicit, comparison)
        self.request("DELETE", f"/api/audit-records/{alternative['id']}")
        timeline = self.request("GET", f"/api/audit-pages/{page_id}")
        self.assertIsNone(timeline["records"][-1]["baseline_record_id"])
        self.assertIsNone(timeline["comparison"])
        self.request("GET", f"/api/audit-records/{post['id']}/compare", 400)
        self.request("DELETE", f"/api/audit-projects/{self.project_id}")
        self.request("GET", f"/api/audit-projects/{self.project_id}", 404)
        self.request("GET", f"/api/audit-pages/{page_id}", 404)
        self.request("PATCH", f"/api/audit-records/{post['id']}", 404, json={"note": "不存在"})
        self.assertIsNone(self.db.get(models.AuditRecord, UUID(pre_id)))

    def test_cross_project_records_return_404(self):
        page_id, pre_id = self.imported_page()
        other = service.create_project(self.db, "其他项目", None, self.users["operator"].id)
        service.import_h5_upload(self.db, other, FIXTURE.read_bytes(), "results.json", None, self.users["operator"].id)
        foreign_pre = self.db.query(models.AuditRecord).join(models.AuditPage).filter(
            models.AuditPage.project_id == other.id).first()
        self.db.commit()
        foreign_id = str(foreign_pre.id)
        _, run, skill = self.app_run({"OV-009": "pass"})
        post = self.add_record(page_id, run, skill, pre_id)
        self.add_record(page_id, run, skill, foreign_id, expected=404)
        self.request("PATCH", f"/api/audit-records/{post['id']}", 404, json={"baseline_record_id": foreign_id})
        self.request("GET", f"/api/audit-records/{post['id']}/compare", 404, params={"pre_id": foreign_id})
        with self.assertRaises(LookupError):
            service.get_project_record(self.db, self.project.id, UUID(foreign_id))

    def test_unknown_ids_return_404(self):
        page_id, pre_id = self.imported_page()
        _, run, skill = self.app_run({"OV-009": "pass"})
        post = self.add_record(page_id, run, skill, pre_id)
        unknown = str(uuid4())
        cases = [("GET", f"/api/audit-projects/{unknown}", {}),
                 ("PATCH", f"/api/audit-projects/{unknown}", {"json": {"name": "名字"}}),
                 ("DELETE", f"/api/audit-projects/{unknown}", {}),
                 ("POST", f"/api/audit-projects/{unknown}/pages", {"json": {"name": "页面"}}),
                 ("GET", f"/api/audit-pages/{unknown}", {}),
                 ("POST", f"/api/audit-pages/{unknown}/records/app",
                  {"json": {"task_run_id": str(run.id), "skill_id": str(skill.id)}}),
                 ("PATCH", f"/api/audit-records/{unknown}", {"json": {"note": "备注"}}),
                 ("DELETE", f"/api/audit-records/{unknown}", {}),
                 ("GET", f"/api/audit-records/{unknown}/compare", {})]
        for method, url, kwargs in cases:
            with self.subTest(method=method, url=url):
                self.request(method, url, 404, **kwargs)
        self.upload(project_id=unknown, expected=404)
        self.add_record(page_id, run, skill, unknown, expected=404)
        self.request("PATCH", f"/api/audit-records/{post['id']}", 404, json={"baseline_record_id": unknown})
        self.request("GET", f"/api/audit-records/{post['id']}/compare", 404, params={"pre_id": unknown})

    def test_invalid_baselines_return_400_and_preserve_records(self):
        page_id, pre_id = self.imported_page()
        other_pre = next(row["latest_pre"]["id"] for row in self.request(
            "GET", f"/api/audit-projects/{self.project_id}")["pages"] if row["id"] != page_id)
        _, run, skill = self.app_run({"OV-009": "pass"})
        post = self.add_record(page_id, run, skill, pre_id)
        for baseline in (other_pre, post["id"]):
            with self.subTest(baseline=baseline):
                self.add_record(page_id, run, skill, baseline, expected=400)
                self.request("PATCH", f"/api/audit-records/{post['id']}", 400, json={"baseline_record_id": baseline})
                self.request("GET", f"/api/audit-records/{post['id']}/compare", 400, params={"pre_id": baseline})
        self.add_record(page_id, run, skill, pre_id, phase="pre", expected=400)
        self.add_record(page_id, run, skill, phase="invalid", expected=400)
        self.request("PATCH", f"/api/audit-records/{pre_id}", 400, json={"baseline_record_id": pre_id})
        self.request("GET", f"/api/audit-records/{pre_id}/compare", 400, params={"pre_id": pre_id})
        timeline = self.request("GET", f"/api/audit-pages/{page_id}")
        self.assertEqual(len(timeline["records"]), 2)
        self.assertEqual(timeline["records"][-1]["baseline_record_id"], pre_id)
        self.assertEqual(timeline["records"][-1]["findings_json"], post["findings_json"])
        self.request("PATCH", f"/api/audit-records/{post['id']}", json={"note": "保留基线"})
        cleared = self.request("PATCH", f"/api/audit-records/{post['id']}", json={"baseline_record_id": None, "note": None})
        self.assertIsNone(cleared["baseline_record_id"])
        self.assertIsNone(cleared["note"])

    def test_bad_h5_uploads_return_400_without_partial_import(self):
        fixture = json.loads(FIXTURE.read_bytes())
        malformed = {**fixture, "results": [fixture["results"][0], {"venue": {}}]}
        bad_status = json.loads(FIXTURE.read_bytes())
        bad_status["results"][0]["audit"]["checks"][0]["status"] = "unknown"
        for raw in (b"not json", b"\xff", b"[]", b"{}", b'{"results":{}}',
                    json.dumps(malformed).encode(), json.dumps(bad_status).encode()):
            with self.subTest(raw=raw[:40]):
                self.upload(raw, expected=400)
                self.assertEqual(self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"], [])

    def test_h5_subset_uses_venue_ids_and_raw_byte_hash(self):
        data = json.loads(FIXTURE.read_bytes())
        venue_id = data["results"][0]["venue"]["venue_id"]
        self.assertEqual(self.upload(venue_ids=f"  {venue_id}, ,unknown "), {"created": 1, "skipped": 0, "pages_created": 1})
        self.assertEqual(self.upload(), {"created": 2, "skipped": 1, "pages_created": 2})
        self.assertEqual(self.upload(venue_ids=""), {"created": 0, "skipped": 3, "pages_created": 0})
        self.assertEqual(self.upload(venue_ids=data["results"][0]["venue"]["record_id"]),
                         {"created": 0, "skipped": 0, "pages_created": 0})

    def test_h5_30mb_upload_imports_408_venues(self):
        fixture = json.loads(FIXTURE.read_bytes())
        # Large source evidence must never be copied into persisted findings.
        results = []
        for index in range(408):
            result = json.loads(json.dumps(fixture["results"][0]))
            result["venue"]["venue_id"] = f"large-{index}"
            result["audit"]["checks"][0]["evidence"] = "x" * 75000
            results.append(result)
        raw = json.dumps({**fixture, "results": results}).encode()
        sha256 = hashlib.sha256(raw).hexdigest()
        self.assertGreater(len(raw), 30_000_000)
        self.assertEqual(self.upload(raw), {"created": 408, "skipped": 0, "pages_created": 408})
        records = self.db.query(models.AuditRecord).join(models.AuditPage).filter(
            models.AuditPage.project_id == self.project.id).all()
        self.assertEqual(len(records), 408)
        self.assertTrue(all(record.source_ref_json["sha256"] == sha256 for record in records))
        self.assertTrue(all(len(json.dumps(record.findings_json)) < 1000 for record in records))

    def test_app_without_selected_inspections_returns_service_message(self):
        page_id, _ = self.imported_page()
        _, run, skill = self.app_run()
        error = self.add_record(page_id, run, skill, expected=400)
        self.assertEqual(error["detail"], "Task run has no inspection results for the selected Skill")
        self.assertEqual(self.request("GET", "/api/audit-projects/app-candidates"), [])
        self.assertEqual(len(self.request("GET", f"/api/audit-pages/{page_id}")["records"]), 1)

    def test_latest_post_without_baseline_has_null_comparison(self):
        page_id, pre_id = self.imported_page()
        _, run, skill = self.app_run({"OV-009": "pass"})
        self.add_record(page_id, run, skill, pre_id)
        latest = self.add_record(page_id, run, skill)
        page = self.request("GET", f"/api/audit-pages/{page_id}")
        self.assertEqual(page["records"][-1]["id"], latest["id"])
        self.assertIsNone(page["comparison"])
        matrix = next(row for row in self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"]
                      if row["id"] == page_id)
        self.assertFalse(matrix["has_baseline"])
        self.assertIsNone(matrix["compare_counts"])
        self.request("GET", f"/api/audit-records/{latest['id']}/compare", 400)

    def test_service_project_list_counts_empty_and_mixed_projects(self):
        self.upload()
        page_id = self.request("GET", f"/api/audit-projects/{self.project_id}")["pages"][0]["id"]
        _, run, skill = self.app_run({"OV-009": "pass"})
        self.add_record(page_id, run, skill, phase="pre")
        self.add_record(page_id, run, skill)
        empty = service.create_project(self.db, "空项目", None, self.users["operator"].id)
        self.db.commit()
        rows = {row["id"]: row for row in service.list_projects(self.db)}
        self.assertEqual(rows[empty.id]["page_count"], 0)
        self.assertEqual(rows[empty.id]["record_counts"], {"pre": 0, "post": 0, "h5": 0, "app": 0})
        self.assertEqual(rows[self.project.id]["page_count"], 3)
        self.assertEqual(rows[self.project.id]["record_counts"], {"pre": 4, "post": 1, "h5": 3, "app": 2})

    def test_service_matrix_batches_records_and_compares_selected_baseline(self):
        self.upload()
        pages = self.db.query(models.AuditPage).filter_by(project_id=self.project.id).all()
        _, run, skill = self.app_run({"OV-009": "pass"})
        for page in pages:
            pre = self.db.query(models.AuditRecord).filter_by(page_id=page.id).first()
            service.add_app_record(self.db, page, run.id, skill.id, baseline_record_id=pre.id)
            service.add_app_record(self.db, page, run.id, skill.id, phase="pre")
        self.db.commit()
        project = self.db.get(models.AuditProject, self.project.id)
        queries = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        event.listen(self.db.bind, "before_cursor_execute", capture)
        try:
            detail = service.project_detail(self.db, project)
        finally:
            event.remove(self.db.bind, "before_cursor_execute", capture)
        self.assertEqual(len(queries), 2)
        first = next(row for row in detail["pages"] if row["business_key"] == "RA092915121822266376")
        self.assertEqual(first["latest_pre"].carrier, "app")
        self.assertEqual(first["compare_counts"]["fixed"], 1)
        self.assertTrue(all(row["has_baseline"] for row in detail["pages"]))

    def test_service_app_candidates_latest_50_distinct_skills_and_completed_only(self):
        task, old_run, skill = self.app_run({"OV-009": "pass"}, completed_at=datetime(2026, 1, 1))
        self.app_run({"OV-009": "pass"}, status="running")
        self.app_run()  # Completed, but no inspection JSON.
        runs = []
        for index in range(51):
            run = models.TaskRun(task_id=task.id, attempt_no=index + 2, status="completed",
                                 completed_at=datetime(2026, 10, 15) + timedelta(minutes=index))
            self.db.add(run)
            self.db.flush()
            self.analysis(task, run, skill, {"OV-009": "pass"})
            runs.append(run)
        other_skill = models.AnalysisSkill(name="其他规范", prompt="巡查", version=2)
        self.db.add(other_skill)
        self.db.flush()
        self.analysis(task, runs[-1], skill, {"OV-009": "fail"})
        self.analysis(task, runs[-1], other_skill, {"OV-015": "pass"})
        self.db.commit()
        candidates = service.app_candidates(self.db)
        self.assertEqual([row["task_run_id"] for row in candidates], [run.id for run in reversed(runs[1:])])
        self.assertNotIn(old_run.id, [row["task_run_id"] for row in candidates])
        self.assertEqual({item.id for item in candidates[0]["skills"]}, {skill.id, other_skill.id})
        self.assertEqual(len(candidates[0]["skills"]), 2)
        response = self.request("GET", "/api/audit-projects/app-candidates")
        self.assertEqual(len(response), 50)
        self.assertEqual(response[0]["task_run_id"], str(runs[-1].id))

    def test_names_and_duplicate_business_keys_return_400(self):
        self.request("POST", "/api/audit-projects", 400, json={"name": "  "})
        self.request("PATCH", f"/api/audit-projects/{self.project_id}", 400, json={"name": None})
        self.request("POST", f"/api/audit-projects/{self.project_id}/pages", 400, json={"name": " "})
        self.request("POST", f"/api/audit-projects/{self.project_id}/pages", json={"name": "页面", "business_key": "key"})
        self.request("POST", f"/api/audit-projects/{self.project_id}/pages", 400,
                     json={"name": "重复", "business_key": " key "})
        page = self.request("POST", f"/api/audit-projects/{self.project_id}/pages", json={"name": "无会场ID", "business_key": " "})
        self.assertIsNone(page["business_key"])


if __name__ == "__main__":
    unittest.main()
