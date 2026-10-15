from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models
from app.database import engine, get_db, init_db
from app.routers import audit_workspace
from app.services.auth import create_access_token

FIXTURE = ROOT / "backend/tests/fixtures/audit_workspace_h5.json"


class AuditWorkspaceAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "test" not in (engine.url.database or ""):
            raise unittest.SkipTest("Integration tests require a disposable test database")
        init_db()

    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)
        self.addCleanup(self.db.close)
        app = FastAPI()
        app.include_router(audit_workspace.router, prefix="/api")

        def database():
            yield self.db

        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.users = {}
        for role in ("viewer", "operator"):
            user = models.User(username=f"{role}-{uuid4()}", password_hash="unused", role=role)
            self.db.add(user)
            self.db.flush()
            self.users[role] = {"Authorization": "Bearer " + create_access_token(user)}
        self.client.headers.update(self.users["operator"])

    def get(self, path, **kwargs):
        response = self.client.get("/api/" + path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, **kwargs):
        response = self.client.post("/api/" + path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def patch(self, path, data):
        response = self.client.patch("/api/" + path, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create_version(self, raw=None, scope="both"):
        spec = self.post("audit-specs", json={"key": "spec-" + uuid4().hex, "name": "测试规范"})
        if raw is None:
            raw = (ROOT / "docs/specifications/official-venue-review/h5-v5.json").read_bytes()
        version = self.post(f'audit-specs/{spec["id"]}/versions', files={"file": ("spec.json", raw, "application/json")},
                            data={"carrier_scope": scope})
        return spec, version

    def h5(self, version, **fields):
        return self.post("audit-runs/h5", files={"file": ("results.json", FIXTURE.read_bytes(), "application/json")},
                         data={"name": "H5审核", "spec_version_id": version["id"], **fields})

    def app_source(self, count=1):
        task = models.Task(name="截图任务", status="completed")
        skill = models.AnalysisSkill(name="截图规范", prompt="检查", skill_type="inspection")
        self.db.add_all([task, skill])
        self.db.flush()
        source = models.TaskRun(task_id=task.id, attempt_no=1, status="completed", completed_at=datetime(2026, 10, 15))
        self.db.add(source)
        self.db.flush()
        for index in range(count):
            image = models.Image(task_id=task.id, task_run_id=source.id, file_path=f"test-{index}.png")
            self.db.add(image)
            self.db.flush()
            self.db.add(models.Analysis(image_id=image.id, skill_id=skill.id, status="done", inspection_json={
                "checks": [{"rule_id": "OV-005", "clause": "首屏商品", "status": "pass", "observed": "上线后已露出",
                            "reason": "符合规范"}]}))
        self.db.flush()
        return source, skill

    def test_401_router_and_viewer_all_writes_forbidden(self):
        self.client.headers.clear()
        for path in ("audit-specs", "audit-runs", "audit-projects", "audit-app-candidates", f"audit-targets/{uuid4()}"):
            self.assertEqual(self.client.get("/api/" + path).status_code, 401)
        self.client.headers.update(self.users["viewer"])
        for path in ("audit-specs", "audit-runs", "audit-projects", "audit-app-candidates"):
            self.get(path)
        unknown = str(uuid4())
        writes = [
            ("post", "audit-specs", {"json": {"key": "blocked", "name": "禁止"}}),
            ("post", f"audit-specs/{unknown}/versions", {"files": {"file": ("x.json", b"{}")}, "data": {"carrier_scope": "h5"}}),
            ("post", "audit-runs/h5", {"files": {"file": ("x.json", b"{}")}, "data": {"name": "x", "spec_version_id": unknown}}),
            ("post", "audit-runs/app", {"json": {"task_run_id": unknown, "skill_id": unknown, "spec_version_id": unknown, "name": "x", "target_name": "x"}}),
            ("patch", f"audit-runs/{unknown}", {"json": {"name": "x"}}),
            ("delete", f"audit-runs/{unknown}", {}),
            ("patch", f"audit-targets/{unknown}", {"json": {"baseline_target_id": None}}),
            ("post", "audit-projects", {"json": {"name": "x"}}),
            ("patch", f"audit-projects/{unknown}", {"json": {"name": "x"}}),
            ("delete", f"audit-projects/{unknown}", {}),
        ]
        for method, path, kwargs in writes:
            with self.subTest(path=path, method=method):
                self.assertEqual(getattr(self.client, method)("/api/" + path, **kwargs).status_code, 403)

    def test_operator_full_flow_and_project_delete_preserves_runs(self):
        spec, version = self.create_version()
        self.assertEqual(self.get(f'audit-spec-versions/{version["id"]}')["rules_json"], version["rules_json"])
        repeated = self.post(f'audit-specs/{spec["id"]}/versions',
                             files={"file": ("spec.json", (ROOT / "docs/specifications/official-venue-review/h5-v5.json").read_bytes())},
                             data={"carrier_scope": "both"})
        self.assertEqual(repeated["id"], version["id"])
        pre = self.h5(version, venue_ids='["issues","uncertain"]')
        detail = self.get(f'audit-runs/{pre["id"]}')
        self.assertEqual(detail["composition"]["total"], 2)
        targets = self.get(f'audit-runs/{pre["id"]}/targets')["items"]
        baseline = next(t for t in targets if t["business_key"] == "issues")
        self.assertEqual(self.get(f'audit-targets/{baseline["id"]}')["findings_json"][0]["observed"], "未露出")
        filtered = self.get(f'audit-runs/{pre["id"]}/targets', params={"search": "issues", "outcome": "issues", "sort": "uncertain"})
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(self.get(f'audit-specs/{spec["id"]}')["latest_version"]["run_count"], 1)
        self.assertIn(spec["id"], [s["id"] for s in self.get("audit-specs")])
        project = self.post("audit-projects", json={"name": "生命周期"})
        project_id = project["id"]
        self.patch(f'audit-runs/{pre["id"]}', {"project_id": project_id, "name": "上线前"})
        source, skill = self.app_source(count=2)
        candidate = next(c for c in self.get("audit-app-candidates") if c["task_run_id"] == str(source.id))
        self.assertEqual([s["id"] for s in candidate["skills"]], [str(skill.id)])
        post = self.post("audit-runs/app", json={"task_run_id": str(source.id), "skill_id": str(skill.id),
                         "spec_version_id": version["id"], "name": "上线后", "target_name": "问题会场",
                         "business_key": "issues", "project_id": project_id})
        post_target = self.get(f'audit-runs/{post["id"]}/targets')["items"][0]
        self.assertEqual(post_target["baseline_target_id"], baseline["id"])
        project_detail = self.get(f"audit-projects/{project_id}")
        self.assertEqual(project_detail["page_count"], 2)
        self.assertEqual(project_detail["stages"]["closed"]["count"], 1)
        self.assertEqual(project_detail["flow"]["counts"]["fixed"], 1)
        self.assertEqual(len(self.get(f"audit-projects/{project_id}/matrix")["pages"]), 2)
        life = self.get(f"audit-projects/{project_id}/pages/issues")
        self.assertEqual(len(life["timeline"]), 2)
        self.assertEqual(life["groups"]["closed"][0]["post_observed"], "上线后已露出")
        self.client.headers.update(self.users["viewer"])
        self.get(f'audit-runs/{pre["id"]}')
        self.get(f'audit-targets/{post_target["id"]}')
        self.get(f"audit-projects/{project_id}/matrix")
        self.get(f"audit-projects/{project_id}/pages/issues")
        self.client.headers.update(self.users["operator"])
        self.assertEqual(len(self.get("audit-runs", params={"project_id": project_id})), 2)
        self.assertIn(post["id"], [r["id"] for r in self.get("audit-runs", params={"carrier": "app"})])
        self.assertEqual(next(p for p in self.get("audit-projects") if p["id"] == project_id)["run_count"], 2)
        self.patch(f'audit-targets/{post_target["id"]}', {"baseline_target_id": None})
        self.assertTrue(self.get(f"audit-projects/{project_id}/pages/issues")["independent_check"])
        self.patch(f'audit-targets/{post_target["id"]}', {"baseline_target_id": baseline["id"]})
        self.patch(f'audit-runs/{pre["id"]}', {"project_id": None})
        self.assertIsNone(self.get(f'audit-targets/{post_target["id"]}')["baseline_target_id"])
        self.assertIn(pre["id"], [r["id"] for r in self.get("audit-runs", params={"unassigned": True})])
        self.patch(f'audit-runs/{pre["id"]}', {"project_id": project_id})
        self.patch(f'audit-targets/{post_target["id"]}', {"baseline_target_id": baseline["id"]})
        self.patch(f"audit-projects/{project_id}", {"name": "新名称", "description": "说明"})
        self.assertEqual(self.client.delete(f"/api/audit-projects/{project_id}").status_code, 200)
        self.assertIsNone(self.get(f'audit-runs/{post["id"]}')["project_id"])
        self.assertIsNone(self.get(f'audit-targets/{post_target["id"]}')["baseline_target_id"])
        for record in (pre, post):
            self.assertEqual(self.client.delete(f'/api/audit-runs/{record["id"]}').status_code, 200)
            self.assertEqual(self.client.get(f'/api/audit-runs/{record["id"]}').status_code, 404)

    def test_unknown_and_cross_object_ids_404_and_value_errors_400(self):
        unknown = str(uuid4())
        for path in (f"audit-specs/{unknown}", f"audit-spec-versions/{unknown}", f"audit-runs/{unknown}",
                     f"audit-runs/{unknown}/targets", f"audit-targets/{unknown}", f"audit-projects/{unknown}",
                     f"audit-projects/{unknown}/matrix", f"audit-projects/{unknown}/pages/x"):
            self.assertEqual(self.client.get("/api/" + path).status_code, 404)
        _, version = self.create_version()
        one = self.post("audit-projects", json={"name": "一"})
        two = self.post("audit-projects", json={"name": "二"})
        pre = self.h5(version, project_id=one["id"], venue_ids="issues,uncertain")
        post = self.h5(version, project_id=two["id"], phase="post", venue_ids="issues")
        baseline = self.get(f'audit-runs/{pre["id"]}/targets')["items"][0]
        post_target = self.get(f'audit-runs/{post["id"]}/targets')["items"][0]
        self.assertEqual(self.client.patch(f'/api/audit-targets/{post_target["id"]}',
                         json={"baseline_target_id": baseline["id"]}).status_code, 404)
        self.assertEqual(self.client.get(f'/api/audit-projects/{two["id"]}/pages/uncertain').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/audit-runs/{pre["id"]}', json={"project_id": unknown}).status_code, 404)
        self.patch(f'audit-runs/{post["id"]}', {"project_id": one["id"]})
        other_page = next(t for t in self.get(f'audit-runs/{pre["id"]}/targets')["items"] if t["business_key"] == "uncertain")
        self.assertEqual(self.client.patch(f'/api/audit-targets/{post_target["id"]}',
                         json={"baseline_target_id": other_page["id"]}).status_code, 404)
        for path in (f'audit-runs/{pre["id"]}?outcome=bad', f'audit-runs/{pre["id"]}/targets?page_size=101',
                     "audit-runs?carrier=bad"):
            self.assertEqual(self.client.get("/api/" + path).status_code, 400)
        self.assertEqual(self.client.patch(f'/api/audit-runs/{pre["id"]}', json={"name": " "}).status_code, 400)
        self.assertEqual(self.client.post("/api/audit-specs", json={"key": "Bad Slug", "name": "x"}).status_code, 400)
        spec, _ = self.create_version()
        self.assertEqual(self.client.post(f'/api/audit-specs/{spec["id"]}/versions',
                         files={"file": ("bad.json", b"not json")}, data={"carrier_scope": "both"}).status_code, 400)
        self.assertEqual(self.client.post("/api/audit-runs/h5", files={"file": ("bad.json", b"{}")},
                         data={"name": "bad", "spec_version_id": version["id"]}).status_code, 400)
        self.assertEqual(self.client.post("/api/audit-runs/app", json={"task_run_id": unknown, "skill_id": unknown,
                         "spec_version_id": version["id"], "name": "x", "target_name": "x"}).status_code, 404)

    def test_candidates_latest_50_distinct_skills_and_eligibility(self):
        source, skill = self.app_source(count=2)
        task_id = source.task_id
        for i in range(1, 53):
            source_run = models.TaskRun(task_id=task_id, attempt_no=i + 1, status="running" if i == 51 else "completed",
                                       completed_at=datetime(2026, 10, 15) + timedelta(seconds=i))
            self.db.add(source_run)
            self.db.flush()
            image = models.Image(task_id=task_id, task_run_id=source_run.id, file_path="test.png")
            self.db.add(image)
            self.db.flush()
            self.db.add(models.Analysis(image_id=image.id, skill_id=skill.id, status="done",
                                       inspection_json={"checks": []} if i < 52 else None))
        self.db.flush()
        candidates = self.get("audit-app-candidates")
        self.assertEqual(len(candidates), 50)
        self.assertNotIn(str(source.id), [c["task_run_id"] for c in candidates])
        self.assertTrue(all(len(c["skills"]) == 1 for c in candidates))
        dates = [c["completed_at"] for c in candidates]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_independent_target_key_and_deleting_a_linked_pre_run(self):
        _, version = self.create_version()
        project = self.post("audit-projects", json={"name": "独立页面"})
        source, skill = self.app_source()
        post = self.post("audit-runs/app", json={"task_run_id": str(source.id), "skill_id": str(skill.id),
                         "spec_version_id": version["id"], "name": "独立审核", "target_name": "无业务键",
                         "project_id": project["id"]})
        post_target = self.get(f'audit-runs/{post["id"]}/targets')["items"][0]
        life = self.get(f'audit-projects/{project["id"]}/pages/t:{post_target["id"]}')
        self.assertTrue(life["independent_check"])
        self.assertEqual(life["timeline"][0]["carrier"], "app")
        pre = self.h5(version, project_id=project["id"], venue_ids="issues")
        linked = self.h5(version, project_id=project["id"], phase="post", venue_ids="issues")
        linked_target = self.get(f'audit-runs/{linked["id"]}/targets')["items"][0]
        self.assertIsNotNone(linked_target["baseline_target_id"])
        self.assertEqual(self.client.delete(f'/api/audit-runs/{pre["id"]}').status_code, 200)
        self.assertIsNone(self.get(f'audit-targets/{linked_target["id"]}')["baseline_target_id"])

    @unittest.skipUnless(os.environ.get("AUDIT_REAL_RESULTS"), "Set AUDIT_REAL_RESULTS to the 408 results.json")
    def test_real_408_via_api_payload_and_report(self):
        _, version = self.create_version(scope="h5")
        with Path(os.environ["AUDIT_REAL_RESULTS"]).open("rb") as source:
            record = self.post("audit-runs/h5", files={"file": ("results.json", source, "application/json")},
                               data={"name": "真实408会场", "spec_version_id": version["id"]})
        response = self.client.get(f'/api/audit-runs/{record["id"]}')
        self.assertEqual(response.status_code, 200, response.text[:1000])
        detail = response.json()
        self.assertLess(len(response.content), 200_000)
        self.assertEqual(detail["composition"]["outcomes"], {"issues": 95, "needs_confirmation": 78,
                         "partial": 29, "clean": 0, "capture_failed": 206})
        self.assertEqual(detail["composition"]["capture_reasons"]["offline"], 195)
        triage = detail["triage"]
        print("REAL_408_API " + json.dumps({"composition": detail["composition"], "top5": detail["pareto"][:5],
              "triage": {"focus": len(triage["focus"]), "batch_rules": len(triage["batches"]),
                         "batch_targets": sum(b["count"] for b in triage["batches"]),
                         "evidence_gaps": triage["evidence_gaps"], "recapture": triage["recapture"]},
              "payload_bytes": len(response.content)}, ensure_ascii=False))
