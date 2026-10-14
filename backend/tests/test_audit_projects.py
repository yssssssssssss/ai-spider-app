import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import models
from app.services.audit_projects import add_app_record, aggregate_app_findings, compare, import_h5, parse_h5_results, set_baseline
from app.services.inspection import Specification, build_inspection


FIXTURE = Path(__file__).parent / "fixtures" / "audit_projects_h5.json"
SPEC = ("官方会场设计规范", "h5-v3")
CATEGORIES = ("fixed", "still_open", "regressed", "new_issue", "kept", "needs_confirmation", "not_comparable")


def h5_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def finding(status, rule_id="OV-009", observed="观察结果"):
    return {"rule_id": rule_id, "title": "楼层间距", "status": status, "observed": observed, "reason": "判定依据",
            "evidence": {"kind": "h5_report", "image_ids": []}}


def inspection_analysis(statuses, image_id=None):
    image = SimpleNamespace(id=image_id or uuid4(), source_app="京东", scenario="会场", task_run_id=None, device_id=None)
    spec = Specification.model_validate({
        "title": "截图规范", "version": "1", "source": "测试规范.md", "document": "检查楼层间距",
        "rules": [{"id": rule_id, "clause": f"条款 {rule_id}", "expected": "符合规范"} for rule_id in statuses],
    })
    checks = [{"rule_id": rule_id, "status": status, "observed": f"{rule_id}: {status}", "reason": f"依据: {status}",
               "bbox_norm": [0, 0, 500, 500] if status in {"pass", "fail"} else None}
              for rule_id, status in statuses.items()]
    inspection = build_inspection({"checks": checks}, spec, image, [], {"name": "截图规范", "version": 1}, (200, 400))
    return models.Analysis(image_id=image.id, inspection_json=inspection, status="done")


class CompareTests(unittest.TestCase):
    def test_compare_category_table(self):
        statuses = ("fail", "pass", "uncertain", "not_applicable", "disabled", None)
        expected = (
            ("still_open", "fixed", "needs_confirmation", "not_comparable", "not_comparable", "not_comparable"),
            ("regressed", "kept", "needs_confirmation", "not_comparable", "not_comparable", "not_comparable"),
            ("needs_confirmation",) * 6,
            ("new_issue", "not_comparable", "needs_confirmation", "not_comparable", "not_comparable", "not_comparable"),
            ("new_issue", "not_comparable", "needs_confirmation", "not_comparable", "not_comparable", "not_comparable"),
            ("new_issue", "not_comparable", "needs_confirmation", "not_comparable", "not_comparable", None),
        )
        for pre_index, pre_status in enumerate(statuses):
            for post_index, post_status in enumerate(statuses):
                with self.subTest(pre=pre_status, post=post_status):
                    pre = [finding(pre_status, observed="上线前观察")] if pre_status else []
                    post = [finding(post_status, observed="上线后观察")] if post_status else []
                    result = compare(pre, post, pre_spec=SPEC, post_spec=SPEC)
                    category = expected[pre_index][post_index]
                    self.assertEqual(result["counts"], {name: int(name == category) for name in CATEGORIES})
                    self.assertFalse(result["spec_mismatch"])
                    self.assertEqual(result["rules"], [{
                        "rule_id": "OV-009", "title": "楼层间距", "category": category,
                        "pre_status": pre_status, "pre_observed": "上线前观察" if pre else None,
                        "post_status": post_status, "post_observed": "上线后观察" if post else None,
                    }] if category else [])

    def test_compare_aligns_rule_ids_and_counts_all_categories(self):
        pairs = [("fail", "pass"), ("fail", "fail"), ("pass", "fail"), ("disabled", "fail"),
                 ("pass", "pass"), ("uncertain", "pass"), ("disabled", "disabled")]
        pre = [finding(before, f"rule-{index}") for index, (before, _) in enumerate(pairs)]
        post = [finding(after, f"rule-{index}") for index, (_, after) in enumerate(pairs)]
        result = compare(pre, list(reversed(post)), pre_spec=SPEC, post_spec=SPEC)
        self.assertEqual([row["category"] for row in result["rules"]], list(CATEGORIES))
        self.assertEqual(result["counts"], dict.fromkeys(CATEGORIES, 1))

    def test_compare_spec_mismatch_still_compares_shared_rules(self):
        for post_spec in (("其他规范", SPEC[1]), (SPEC[0], "h5-v4"), ("其他规范", "h5-v4")):
            with self.subTest(post_spec=post_spec):
                result = compare([finding("fail")], [finding("pass")], pre_spec=SPEC, post_spec=post_spec)
                self.assertTrue(result["spec_mismatch"])
                self.assertEqual(result["counts"]["fixed"], 1)

    def test_compare_empty_and_disjoint_findings(self):
        result = compare([], [], pre_spec=SPEC, post_spec=SPEC)
        self.assertEqual(result, {"rules": [], "counts": dict.fromkeys(CATEGORIES, 0), "spec_mismatch": False})
        result = compare([finding("fail", "pre-only")], [finding("pass", "post-only")], pre_spec=SPEC, post_spec=SPEC)
        self.assertEqual([row["rule_id"] for row in result["rules"]], ["pre-only", "post-only"])
        self.assertEqual(result["counts"]["not_comparable"], 2)


class H5ParsingTests(unittest.TestCase):
    def test_parse_h5_real_shape_normalizes_fields_and_preserves_disabled(self):
        data = h5_fixture()
        original = copy.deepcopy(data)
        venues = parse_h5_results(data)
        self.assertEqual(len(venues), 3)
        selected = json.loads((ROOT / "docs/examples/official-venue-pilot10-v3.json").read_text())["record_ids"]
        self.assertTrue(all(result["venue"]["record_id"] in selected for result in data["results"]))
        for parsed, raw in zip(venues, data["results"]):
            with self.subTest(venue=parsed.venue_id):
                self.assertEqual((parsed.venue_id, parsed.venue_name, parsed.project_id),
                                 tuple(raw["venue"][key] for key in ("venue_id", "venue_name", "project_id")))
                self.assertEqual((parsed.spec_key, parsed.spec_version), SPEC)
                for normalized, check in zip(parsed.findings, raw["audit"]["checks"]):
                    self.assertEqual(normalized, {**{key: check[key] for key in ("rule_id", "title", "status", "observed", "reason")},
                                                  "evidence": {"kind": "h5_report", "image_ids": []}})
        self.assertEqual(venues[0].summary, {"pass": 0, "fail": 1, "uncertain": 0, "not_applicable": 0, "disabled": 1})
        self.assertEqual(venues[0].findings[1]["status"], "disabled")
        self.assertEqual(data, original)

    def test_parse_h5_venue_ids_including_unknown_and_empty(self):
        data = h5_fixture()
        venue_id = data["results"][1]["venue"]["venue_id"]
        for ids, expected in (({venue_id}, [venue_id]), ({venue_id, "unknown"}, [venue_id]),
                              ({"unknown"}, []), (set(), []), ({data["results"][1]["venue"]["record_id"]}, [])):
            with self.subTest(venue_ids=ids):
                self.assertEqual([venue.venue_id for venue in parse_h5_results(data, venue_ids=ids)], expected)

    def test_parse_h5_empty_findings_and_missing_audit(self):
        data = h5_fixture()
        for audit in ({"checks": []}, None):
            with self.subTest(audit=audit):
                data["results"][0]["audit"] = audit
                venue = parse_h5_results(data)[0]
                self.assertEqual(venue.findings, [])
                self.assertTrue(all(count == 0 for count in venue.summary.values()))
        self.assertEqual(parse_h5_results({**data, "results": []}), [])


class AppAggregationTests(unittest.TestCase):
    def test_aggregate_app_precedence_and_contributing_images(self):
        combinations = ((["not_applicable", "uncertain", "pass", "fail", "fail"], "fail"),
                        (["not_applicable", "uncertain", "pass", "pass"], "pass"),
                        (["not_applicable", "uncertain", "uncertain"], "uncertain"),
                        (["not_applicable", "not_applicable"], "not_applicable"))
        for statuses, expected in combinations:
            with self.subTest(statuses=statuses):
                analyses = [inspection_analysis({"OV-009": status}) for status in statuses]
                original = copy.deepcopy([analysis.inspection_json for analysis in analyses])
                result = aggregate_app_findings(analyses)
                self.assertEqual(result, [{
                    "rule_id": "OV-009", "title": "条款 OV-009", "status": expected,
                    "observed": f"OV-009: {expected}", "reason": f"依据: {expected}",
                    "evidence": {"kind": "app_images", "image_ids": [str(analysis.image_id) for analysis, status in zip(analyses, statuses) if status == expected]},
                }])
                self.assertEqual([analysis.inspection_json for analysis in analyses], original)
                self.assertEqual(aggregate_app_findings(list(reversed(analyses)))[0]["status"], expected)

    def test_aggregate_app_independent_rules_keep_all_winning_observations(self):
        first = inspection_analysis({"OV-009": "fail", "OV-015": "pass"})
        second = inspection_analysis({"OV-009": "fail", "OV-015": "uncertain", "OV-018": "not_applicable"})
        second.inspection_json["checks"][0].update(observed="另一个间距错误", reason="另一个判定依据")
        findings = {item["rule_id"]: item for item in aggregate_app_findings([first, second, first])}
        self.assertEqual(findings["OV-009"]["observed"], "OV-009: fail\n另一个间距错误")
        self.assertEqual(findings["OV-009"]["reason"], "依据: fail\n另一个判定依据")
        self.assertEqual(findings["OV-009"]["evidence"]["image_ids"], [str(first.image_id), str(second.image_id)])
        self.assertEqual(findings["OV-015"]["status"], "pass")
        self.assertEqual(findings["OV-015"]["evidence"]["image_ids"], [str(first.image_id)])
        self.assertEqual(findings["OV-018"]["status"], "not_applicable")

    def test_aggregate_app_empty_or_non_inspection_results(self):
        for analyses in ([], [models.Analysis(image_id=uuid4(), inspection_json=None)],
                         [models.Analysis(image_id=uuid4(), inspection_json={"checks": []})]):
            with self.subTest(analyses=analyses):
                self.assertEqual(aggregate_app_findings(analyses), [])


class AuditProjectDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database import engine, init_db
        if "test" not in engine.url.database and not engine.url.database.endswith("_round1"):
            raise unittest.SkipTest("Integration tests require a disposable test database")
        init_db()

    def setUp(self):
        from app.database import SessionLocal
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.user_id = uuid4()
        self.project = models.AuditProject(name="审核项目", created_by=self.user_id)
        self.db.add(self.project)
        self.db.flush()

    def page(self, name="会场", business_key=None, project=None):
        page = models.AuditPage(project_id=(project or self.project).id, name=name, business_key=business_key)
        self.db.add(page)
        self.db.flush()
        return page

    def record(self, page, phase="pre"):
        record = models.AuditRecord(page_id=page.id, phase=phase, carrier="h5" if phase == "pre" else "app",
                                   source_kind="h5_import" if phase == "pre" else "app_task_run", spec_key=SPEC[0], spec_version=SPEC[1],
                                   findings_json=[finding("fail")], summary_json={"fail": 1}, created_by=self.user_id)
        self.db.add(record)
        self.db.flush()
        return record

    def app_run(self):
        task = models.Task(name="App审核")
        skill = models.AnalysisSkill(name="截图规范", prompt="巡查", skill_type="inspection", version=3)
        self.db.add_all([task, skill])
        self.db.flush()
        run = models.TaskRun(task_id=task.id, attempt_no=1, status="completed")
        self.db.add(run)
        self.db.flush()
        return task, run, skill

    def add_analysis(self, task, run, skill, statuses=None):
        image = models.Image(file_path="fixture.png", task_id=task.id, task_run_id=run.id)
        self.db.add(image)
        self.db.flush()
        analysis = inspection_analysis(statuses, image.id) if statuses else models.Analysis(image_id=image.id, status="done", result_json={"report": "普通分析"})
        analysis.skill_id = skill.id
        self.db.add(analysis)
        self.db.flush()
        return image

    def import_data(self, data, sha256, venue_ids=None, project=None, file_name="results.json"):
        return import_h5(self.db, project or self.project, data, file_name, sha256, venue_ids=venue_ids, user_id=self.user_id)

    def test_import_h5_reuses_pages_across_two_files_and_skips_repeat(self):
        data = h5_fixture()
        first, second = {**data, "results": data["results"][:2]}, {**data, "results": data["results"][1:]}
        hashes = [hashlib.sha256(json.dumps(part).encode()).hexdigest() for part in (first, second)]
        self.assertEqual(self.import_data(first, hashes[0]), {"created": 2, "skipped": 0, "pages_created": 2})
        self.assertEqual(self.import_data(second, hashes[1]), {"created": 2, "skipped": 0, "pages_created": 1})
        self.assertEqual(self.import_data(first, hashes[0], file_name="renamed.json"), {"created": 0, "skipped": 2, "pages_created": 0})
        pages = self.db.query(models.AuditPage).filter_by(project_id=self.project.id).all()
        self.assertEqual(len(pages), 3)
        duplicate = next(page for page in pages if page.business_key == data["results"][1]["venue"]["venue_id"])
        self.assertEqual(len(duplicate.records), 2)
        first_page = next(page for page in pages if page.business_key == data["results"][0]["venue"]["venue_id"])
        record = self.db.query(models.AuditRecord).filter_by(page_id=first_page.id).first()
        self.assertEqual((record.phase, record.carrier, record.source_kind), ("pre", "h5", "h5_import"))
        self.assertEqual(record.source_ref_json, {"file_name": "results.json", "sha256": hashes[0], "generated_at": data["generated_at"],
                                                "venue_id": first_page.business_key, "project_id": data["results"][0]["venue"]["project_id"]})
        self.assertEqual(record.findings_json, parse_h5_results(first)[0].findings)
        self.assertEqual(record.summary_json, parse_h5_results(first)[0].summary)
        self.assertEqual((record.spec_key, record.spec_version), SPEC)
        self.assertEqual(record.created_by, self.user_id)

    def test_import_h5_subset_then_same_file_remaining_venues_and_other_project(self):
        data = h5_fixture()
        venue_id = data["results"][0]["venue"]["venue_id"]
        sha256 = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(self.import_data(data, sha256, {venue_id, "unknown"}), {"created": 1, "skipped": 0, "pages_created": 1})
        self.assertEqual(self.import_data(data, sha256), {"created": 2, "skipped": 1, "pages_created": 2})
        self.assertEqual(self.import_data(data, sha256, {"unknown"}), {"created": 0, "skipped": 0, "pages_created": 0})
        self.assertEqual(self.import_data(data, sha256, set()), {"created": 0, "skipped": 0, "pages_created": 0})
        other = models.AuditProject(name="另一项目")
        self.db.add(other)
        self.db.flush()
        self.assertEqual(self.import_data(data, sha256, project=other), {"created": 3, "skipped": 0, "pages_created": 3})

    def test_import_h5_duplicate_venue_within_file_is_skipped(self):
        data = h5_fixture()
        data["results"].append(copy.deepcopy(data["results"][0]))
        self.assertEqual(self.import_data(data, "same-file"), {"created": 3, "skipped": 1, "pages_created": 3})

    def test_page_business_key_unique_per_project_and_allows_null(self):
        self.page(business_key="venue-1")
        self.page()
        self.page()
        other = models.AuditProject(name="另一项目")
        self.db.add(other)
        self.db.flush()
        self.page(business_key="venue-1", project=other)
        with self.db.begin_nested():
            self.db.add(models.AuditPage(project_id=self.project.id, name="重复会场", business_key="venue-1"))
            with self.assertRaises(IntegrityError):
                self.db.flush()

    def test_add_app_record_limits_run_and_skill_and_uses_skill_spec(self):
        page = self.page()
        pre = self.record(page)
        task, run, skill = self.app_run()
        passed = self.add_analysis(task, run, skill, {"OV-009": "pass"})
        failed = self.add_analysis(task, run, skill, {"OV-009": "fail"})
        other_skill = models.AnalysisSkill(name="其他规范", prompt="巡查", skill_type="inspection")
        other_run = models.TaskRun(task_id=task.id, attempt_no=2, status="completed")
        self.db.add_all([other_skill, other_run])
        self.db.flush()
        self.add_analysis(task, run, other_skill, {"other-skill": "fail"})
        self.add_analysis(task, other_run, skill, {"other-run": "fail"})
        record = add_app_record(self.db, page, run.id, skill.id, baseline_record_id=pre.id, user_id=self.user_id)
        self.assertEqual((record.phase, record.carrier, record.source_kind), ("post", "app", "app_task_run"))
        self.assertEqual((record.spec_key, record.spec_version), (skill.name, "3"))
        self.assertEqual(record.source_ref_json, {"task_run_id": str(run.id), "skill_id": str(skill.id)})
        self.assertEqual(record.baseline_record_id, pre.id)
        self.assertEqual(record.created_by, self.user_id)
        self.assertEqual(record.findings_json, [{
            "rule_id": "OV-009", "title": "条款 OV-009", "status": "fail", "observed": "OV-009: fail", "reason": "依据: fail",
            "evidence": {"kind": "app_images", "image_ids": [str(failed.id)]},
        }])
        self.assertNotIn(str(passed.id), record.findings_json[0]["evidence"]["image_ids"])
        self.assertEqual(record.summary_json, {"pass": 0, "fail": 1, "uncertain": 0, "not_applicable": 0, "disabled": 0})
        independent = add_app_record(self.db, page, run.id, skill.id, phase="pre")
        self.assertIsNone(independent.baseline_record_id)

    def test_add_app_record_rejects_run_without_selected_skill_results(self):
        page = self.page()
        task, run, skill = self.app_run()
        other_skill = models.AnalysisSkill(name="其他规范", prompt="巡查", skill_type="inspection")
        self.db.add(other_skill)
        self.db.flush()
        self.add_analysis(task, run, other_skill, {"OV-009": "fail"})
        self.add_analysis(task, run, skill)
        with self.assertRaisesRegex(ValueError, "no inspection results for the selected Skill"):
            add_app_record(self.db, page, run.id, skill.id)
        self.assertEqual(self.db.query(models.AuditRecord).filter_by(page_id=page.id).count(), 0)

    def test_baseline_constraints_and_reassignment_preserve_findings(self):
        page, other_page = self.page(), self.page("其他页面")
        pre, another_pre, post = self.record(page), self.record(page), self.record(page, "post")
        foreign_pre = self.record(other_page)
        before = copy.deepcopy(post.findings_json)
        set_baseline(self.db, post, pre.id)
        cases = ((pre, another_pre.id, "Only post"), (post, foreign_pre.id, "same page"),
                 (post, post.id, "pre record"), (post, uuid4(), "not found"))
        for record, baseline_id, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                set_baseline(self.db, record, baseline_id)
            self.assertEqual(record.baseline_record_id, pre.id if record is post else None)
        for baseline_id in (pre.id, another_pre.id, None):
            set_baseline(self.db, post, baseline_id)
            self.db.flush()
            self.db.refresh(post)
            self.assertEqual(post.baseline_record_id, baseline_id)
            self.assertEqual(post.findings_json, before)

    def test_add_app_record_enforces_baseline_constraints(self):
        page, other_page = self.page(), self.page("其他页面")
        pre, post, foreign_pre = self.record(page), self.record(page, "post"), self.record(other_page)
        task, run, skill = self.app_run()
        self.add_analysis(task, run, skill, {"OV-009": "pass"})
        cases = (("pre", pre.id, "Only post"), ("post", post.id, "pre record"),
                 ("post", foreign_pre.id, "same page"), ("post", uuid4(), "not found"), ("invalid", None, "Phase"))
        for phase, baseline_id, message in cases:
            with self.subTest(phase=phase, message=message), self.assertRaisesRegex(ValueError, message):
                add_app_record(self.db, page, run.id, skill.id, phase, baseline_id, self.user_id)
        self.assertEqual(self.db.query(models.AuditRecord).filter_by(page_id=page.id).count(), 2)

    def test_deleting_pre_nulls_baselines_without_deleting_posts(self):
        page = self.page()
        pre = self.record(page)
        posts = [self.record(page, "post"), self.record(page, "post")]
        for post in posts:
            set_baseline(self.db, post, pre.id)
        self.db.flush()
        self.db.delete(pre)
        self.db.flush()
        for post in posts:
            self.db.refresh(post)
            self.assertIsNone(post.baseline_record_id)
            self.assertIsNone(post.baseline_record)
            self.assertEqual(post.findings_json, [finding("fail")])

    def test_deleting_project_cascades_pages_and_records(self):
        for load_relationships in (False, True):
            with self.subTest(load_relationships=load_relationships):
                project = models.AuditProject(name="待删除项目")
                self.db.add(project)
                self.db.flush()
                page = self.page(project=project)
                pre, post = self.record(page), self.record(page, "post")
                set_baseline(self.db, post, pre.id)
                self.db.flush()
                page_id, record_ids = page.id, [pre.id, post.id]
                if load_relationships:
                    self.assertEqual(project.pages, [page])
                    self.assertEqual(len(page.records), 2)
                self.db.delete(project)
                self.db.flush()
                self.db.expire_all()
                self.assertIsNone(self.db.get(models.AuditPage, page_id))
                for record_id in record_ids:
                    self.assertIsNone(self.db.get(models.AuditRecord, record_id))


if __name__ == "__main__":
    unittest.main()
