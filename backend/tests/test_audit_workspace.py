import copy
import hashlib
import os
import time
from unittest.mock import patch
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
from app.services import audit_workspace as service
from app.services.audit_workspace import aggregate_app_findings, compare, parse_h5_results
from app.services.inspection import Specification, build_inspection


FIXTURE = Path(__file__).parent / "fixtures" / "audit_workspace_h5.json"
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


class H5ParsingTests(unittest.TestCase):
    def test_statuses_capture_reasons_and_original_detail(self):
        data = h5_fixture()
        original = copy.deepcopy(data)
        venues = parse_h5_results(data)
        self.assertEqual([v.outcome for v in venues], ["issues", "needs_confirmation", "partial",
                         *(["capture_failed"] * 4), "clean", "issues", "needs_confirmation"])
        self.assertEqual([v.capture_reason for v in venues[3:7]], list(service.CAPTURE_REASONS))
        for parsed, raw in zip(venues[3:7], data["results"][3:7]):
            self.assertEqual(parsed.summary["capture_detail"], {
                "page_state": raw["audit"].get("page_state"), "page_warnings": raw["audit"].get("page_warnings")})
        self.assertEqual(venues[0].summary["fail"], 1)
        self.assertEqual(venues[1].summary["uncertain"], 1)
        self.assertEqual(venues[0].summary["disabled"], 1)
        self.assertEqual(venues[0].findings[0]["observed"], "未露出")
        self.assertEqual(venues[0].findings[0]["evidence"], {"kind": "h5_report", "image_ids": []})
        self.assertEqual(data, original)

    def test_subset_empty_and_unknown_venues(self):
        for ids, expected in (({"partial"}, ["partial"]), ({"partial", "unknown"}, ["partial"]),
                              (set(), []), ({"unknown"}, [])):
            with self.subTest(ids=ids):
                self.assertEqual([v.venue_id for v in parse_h5_results(h5_fixture(), ids)], expected)
        self.assertEqual(parse_h5_results({"results": []}), [])

    def test_invalid_results_are_rejected(self):
        for data in ({}, {"results": {}}, {"results": [None]}, {"results": [{"venue": {}}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_h5_results(data)
        data = h5_fixture()
        data["results"][0]["audit"]["checks"][0]["status"] = "oops"
        with self.assertRaisesRegex(ValueError, "Unknown H5"):
            parse_h5_results(data)


def rule(rule_id="OV-009", enabled=True, carriers=None, duplicate_of=None):
    return {"rule_id": rule_id, "enabled": enabled, "carriers": carriers or ["h5", "app"],
            "duplicate_of": duplicate_of}


def target(findings, rules, carrier="h5", version_id=None):
    version = SimpleNamespace(id=version_id or uuid4(), spec_id=uuid4(), rules_json=rules)
    run = SimpleNamespace(spec_version=version, carrier=carrier)
    return SimpleNamespace(run=run, findings_json=findings)


class ComparisonApplicabilityTests(unittest.TestCase):
    def test_all_v1_transitions_remain_with_applicable_versions(self):
        statuses = ("fail", "pass", "uncertain", "not_applicable", "disabled", None)
        for before in statuses:
            for after in statuses:
                with self.subTest(before=before, after=after):
                    pre = target([finding(before)] if before else [], [rule()])
                    post = target([finding(after)] if after else [], [rule()], "app")
                    expected = compare(pre.findings_json, post.findings_json, pre_spec=SPEC, post_spec=SPEC)
                    result = service.compare_targets(pre, post)
                    self.assertEqual(result["rules"], expected["rules"])
                    self.assertEqual(result["counts"], expected["counts"])
                    self.assertTrue(result["spec_mismatch"])

    def test_missing_disabled_or_wrong_carrier_overrides_fail_and_uncertain(self):
        for before, after in (("fail", "pass"), ("uncertain", "fail")):
            for side in ("pre", "post"):
                for invalid in ([], [rule(enabled=False)], [rule(carriers=["app" if side == "pre" else "h5"]) ]):
                    with self.subTest(before=before, side=side, invalid=invalid):
                        pre = target([finding(before)], invalid if side == "pre" else [rule()])
                        post = target([finding(after)], invalid if side == "post" else [rule()], "app")
                        result = service.compare_targets(pre, post)
                        self.assertEqual(result["rules"][0]["category"], "not_comparable")
                        self.assertEqual(result["counts"]["not_comparable"], 1)

    def test_duplicates_kept_in_detail_excluded_from_every_category(self):
        for side in ("pre", "post"):
            for before, after in (("fail", "pass"), ("uncertain", "uncertain"), ("disabled", "disabled")):
                pre = target([finding(before)], [rule(duplicate_of="OV-005" if side == "pre" else None)])
                post = target([finding(after)], [rule(duplicate_of="OV-005" if side == "post" else None)])
                result = service.compare_targets(pre, post)
                self.assertEqual(len(result["rules"]), 1)
                self.assertEqual(sum(result["counts"].values()), 0)

    def test_same_version_is_not_a_mismatch_and_inputs_are_unchanged(self):
        pre = target([finding("pass")], [rule()])
        post = target([finding("fail")], [rule()])
        post.run.spec_version = pre.run.spec_version
        before = copy.deepcopy(pre.findings_json)
        result = service.compare_targets(pre, post)
        self.assertFalse(result["spec_mismatch"])
        self.assertEqual(result["counts"]["regressed"], 1)
        self.assertEqual(pre.findings_json, before)


class AuditWorkspaceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database import engine, init_db
        if "test" not in (engine.url.database or ""):
            raise unittest.SkipTest("Integration tests require a disposable test database")
        init_db()

    def setUp(self):
        from app.database import SessionLocal
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.user_id = uuid4()
        self.project = models.AuditProject(name="审核项目", created_by=self.user_id)
        self.spec = models.AuditSpec(key=f"spec-{uuid4()}", name="官方会场")
        self.db.add_all([self.project, self.spec])
        self.db.flush()
        self.h5_version = service.import_spec_version(self.db, self.spec, self.spec_bytes(), "h5", self.user_id)

    def spec_bytes(self, version=5):
        return (ROOT / f"docs/specifications/official-venue-review/h5-v{version}.json").read_bytes()

    def version(self, scope="app"):
        spec = models.AuditSpec(key=f"other-{uuid4()}", name="其他规范")
        self.db.add(spec)
        return service.import_spec_version(self.db, spec, self.spec_bytes(), scope, self.user_id)

    def h5_run(self, name="H5审核", phase="pre", project=None, venue_ids=None):
        return service.create_h5_run(self.db, FIXTURE.read_bytes(), "results.json", self.h5_version,
                                     name, phase, venue_ids, project, self.user_id)

    def app_source(self, statuses=None):
        task = models.Task(name="App审核")
        skill = models.AnalysisSkill(name="截图规范", prompt="巡查", skill_type="inspection")
        self.db.add_all([task, skill])
        self.db.flush()
        run = models.TaskRun(task_id=task.id, attempt_no=1, status="completed")
        self.db.add(run)
        self.db.flush()
        for status_map in statuses or []:
            image = models.Image(file_path="fixture.png", task_id=task.id, task_run_id=run.id)
            self.db.add(image)
            self.db.flush()
            analysis = inspection_analysis(status_map, image.id)
            analysis.skill_id = skill.id
            self.db.add(analysis)
        self.db.flush()
        return run, skill

    def test_real_spec_versions_labels_enabled_duplicates_and_public_format(self):
        spec = models.AuditSpec(key=f"versions-{uuid4()}", name="版本库")
        self.db.add(spec)
        versions = [service.import_spec_version(self.db, spec, self.spec_bytes(v), "h5", self.user_id)
                    for v in range(2, 6)]
        self.assertEqual([v.version for v in versions], [1, 2, 3, 4])
        self.assertEqual([sum(r["enabled"] for r in v.rules_json) for v in versions], [14, 13, 13, 13])
        for v, number in zip(versions, range(2, 6)):
            raw = json.loads(self.spec_bytes(number))
            self.assertEqual(v.label, raw["version"])
            self.assertEqual(v.source_json, raw)
            self.assertEqual(v.sha256, hashlib.sha256(self.spec_bytes(number)).hexdigest())
            for normalized, original in zip(v.rules_json, raw["rules"]):
                self.assertEqual(normalized["title"], original["title"])
                self.assertEqual(normalized["clause"], original["sources"][0]["clause"])
                self.assertEqual(normalized["duplicate_of"], original.get("duplicate_of"))
                self.assertEqual(normalized["carriers"], ["h5"])
                self.assertEqual(normalized["method"], original["verification_method"])
                self.assertEqual(normalized["strength"], {"conditional_mandatory": "conditional", "recommendation": "recommended"}.get(original["strength"], original["strength"]))
        raw = (ROOT / "docs/specifications/dual-entry-inspection.json").read_bytes()
        public = service.import_spec_version(self.db, self.spec, raw, "app", self.user_id)
        self.assertEqual(len(public.rules_json), 1)
        item = public.rules_json[0]
        self.assertEqual(item["title"], item["clause"])
        self.assertEqual((item["strength"], item["enabled"], item["carriers"]), ("mandatory", True, ["app"]))
        self.assertIs(service.import_spec_version(self.db, self.spec, raw, "both", None), public)
        self.assertEqual(public.carrier_scope, "app")

    def test_rule_carriers_override_scope_and_rule_version_label(self):
        raw = json.dumps({"rule_version": "custom", "rules": [
            {"id": "a", "clause": "条款", "expected": "yes"},
            {"id": "b", "clause": "条款", "expected": "yes", "carriers": ["app"]}]}).encode()
        version = service.import_spec_version(self.db, self.spec, raw, "both", None)
        self.assertEqual(version.label, "custom")
        self.assertEqual([r["carriers"] for r in version.rules_json], [["h5", "app"], ["app"]])

    def test_versions_immutable_and_existing_runs_keep_snapshot(self):
        run = self.h5_run()
        original = copy.deepcopy(self.h5_version.rules_json)
        next_version = service.import_spec_version(self.db, self.spec, self.spec_bytes(4), "both", None)
        self.assertNotEqual(next_version.id, run.spec_version_id)
        self.assertEqual(run.spec_version.rules_json, original)
        for field, value in (("label", "changed"), ("carrier_scope", "both"), ("rules_json", []), ("source_json", {})):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "immutable"), self.db.begin_nested():
                    setattr(self.h5_version, field, value)
                    self.db.flush()
                self.db.refresh(self.h5_version)
        self.assertEqual(self.h5_version.rules_json, original)

    def test_spec_unique_constraints_and_invalid_import(self):
        for fields in ({"version": self.h5_version.version, "sha256": "f" * 64},
                       {"version": 99, "sha256": self.h5_version.sha256}):
            with self.assertRaises(IntegrityError), self.db.begin_nested():
                self.db.add(models.AuditSpecVersion(spec_id=self.spec.id, label="bad", carrier_scope="h5",
                            rules_json=[], source_json={}, **fields))
                self.db.flush()
        with self.assertRaises(IntegrityError), self.db.begin_nested():
            self.db.add(models.AuditSpec(key=self.spec.key, name="duplicate"))
            self.db.flush()
        for raw in (b"no json", b"[]", b"{}", b'{"rules": [null]}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                service.import_spec_version(self.db, self.spec, raw, "h5", None)
        with self.assertRaisesRegex(ValueError, "scope"):
            service.import_spec_version(self.db, self.spec, b"{}", "desktop", None)

    def test_h5_import_summary_source_subset_and_one_decode(self):
        raw = FIXTURE.read_bytes()
        with patch.object(service.json, "loads", wraps=json.loads) as decode:
            run = service.create_h5_run(self.db, raw, "results.json", self.h5_version, " H5 ")
            self.assertEqual(decode.call_count, 1)
        self.assertEqual(run.name, "H5")
        self.assertIsNone(run.project_id)
        self.assertEqual(run.summary_json, {"targets": 10, "outcomes": {
            "issues": 2, "needs_confirmation": 2, "partial": 1, "clean": 1, "capture_failed": 4},
            "capture_reasons": dict.fromkeys(service.CAPTURE_REASONS, 1)})
        self.assertEqual(run.source_ref_json["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(run.targets[0].summary_json["fail"], 1)
        self.assertEqual(len(run.targets[0].findings_json), 3)
        selected = self.h5_run(venue_ids={"partial", "unknown"}, project=self.project)
        self.assertEqual([t.business_key for t in selected.targets], ["partial"])
        self.assertEqual(selected.project_id, self.project.id)
        empty = self.h5_run(venue_ids=set())
        self.assertEqual(empty.summary_json["targets"], 0)

    def test_h5_rejects_wrong_scope_invalid_phase_name_and_file(self):
        args = (self.db, FIXTURE.read_bytes(), "results.json")
        with self.assertRaisesRegex(ValueError, "include h5"):
            service.create_h5_run(*args, self.version(), "H5")
        for name, phase in ((" ", "pre"), ("H5", "bad")):
            with self.assertRaises(ValueError):
                service.create_h5_run(*args, self.h5_version, name, phase)
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            service.create_h5_run(self.db, b"bad", "bad.json", self.h5_version, "H5")
        self.assertEqual(self.db.query(models.AuditRun).filter_by(spec_version_id=self.h5_version.id).count(), 0)

    def test_app_multi_image_merge_scope_selected_skill_and_outcome(self):
        source, skill = self.app_source([{"OV-005": "pass", "OV-009": "uncertain"},
                                         {"OV-005": "fail", "OV-009": "pass", "OV-023": "fail"}])
        version = self.version()
        pre = self.h5_run(project=self.project, venue_ids={"issues"})
        run = service.create_app_run(self.db, source.id, skill.id, version, "App", " 会场 ", " issues ",
                                     project=self.project, user_id=self.user_id)
        self.assertEqual((run.carrier, run.phase, run.source_kind), ("app", "post", "app_task_run"))
        item = run.targets[0]
        self.assertEqual((item.name, item.business_key, item.outcome), ("会场", "issues", "issues"))
        self.assertEqual(item.baseline_target_id, pre.targets[0].id)
        self.assertEqual(item.summary_json["fail"], 1)
        self.assertEqual({f["rule_id"]: f["status"] for f in item.findings_json},
                         {"OV-005": "fail", "OV-009": "pass", "OV-023": "fail"})
        self.assertEqual(run.source_ref_json, {"task_run_id": str(source.id), "skill_id": str(skill.id)})
        for checks, outcome in (({"OV-009": "uncertain"}, "needs_confirmation"), ({"OV-009": "pass"}, "clean")):
            source, skill = self.app_source([checks])
            run = service.create_app_run(self.db, source.id, skill.id, version, "App", "会场", " ")
            self.assertIsNone(run.targets[0].business_key)
            self.assertEqual(run.targets[0].outcome, outcome)

    def test_app_rejections_leave_no_partial_runs(self):
        source, skill = self.app_source()
        other_source, other_skill = self.app_source([{"OV-005": "fail"}])
        version = self.version()
        for source_id, skill_id, spec_version, target_name, error in (
            (source.id, skill.id, version, "会场", "no inspection results"),
            (other_source.id, skill.id, version, "会场", "no inspection results"),
            (other_source.id, other_skill.id, self.h5_version, "会场", "include app"),
            (uuid4(), skill.id, version, "会场", "not found"),
            (source.id, uuid4(), version, "会场", "Skill not found"),
            (source.id, skill.id, version, " ", "Target name"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                service.create_app_run(self.db, source_id, skill_id, spec_version, "App", target_name)
        source.status = "running"
        with self.assertRaisesRegex(ValueError, "completed"):
            service.create_app_run(self.db, source.id, skill.id, version, "App", "会场")
        self.assertEqual(self.db.query(models.AuditRun).filter_by(spec_version_id=version.id).count(), 0)

    def test_assignment_uses_latest_pre_only_and_preserves_manual_on_noop(self):
        from datetime import timedelta
        old = self.h5_run(project=self.project, venue_ids={"issues"})
        latest = self.h5_run(project=self.project, venue_ids={"issues"})
        old.created_at = latest.created_at - timedelta(days=1)
        post = self.h5_run(phase="post", venue_ids={"issues", "partial"})
        service.assign_run(self.db, post, self.project)
        targets = {t.business_key: t for t in post.targets}
        self.assertEqual(targets["issues"].baseline_target_id, latest.targets[0].id)
        self.assertIsNone(targets["partial"].baseline_target_id)
        service.set_target_baseline(self.db, targets["issues"], old.targets[0])
        service.assign_run(self.db, post, self.project)
        self.assertEqual(targets["issues"].baseline_target_id, old.targets[0].id)
        self.assertIsNone(old.targets[0].baseline_target_id)
        service.set_target_baseline(self.db, targets["issues"], None)
        self.assertIsNone(targets["issues"].baseline_target_id)
        # Unkeyed objects stay independent even when a pre object is also unkeyed.
        latest.targets[0].business_key = None
        unkeyed = self.h5_run(phase="post", venue_ids={"issues"})
        unkeyed.targets[0].business_key = None
        service.assign_run(self.db, unkeyed, self.project)
        self.assertIsNone(unkeyed.targets[0].baseline_target_id)

    def test_manual_baseline_constraints_do_not_change_findings(self):
        pre = self.h5_run(project=self.project)
        post = self.h5_run(phase="post", project=self.project)
        another_project = models.AuditProject(name="其他项目")
        self.db.add(another_project)
        foreign = self.h5_run(project=another_project)
        independent = self.h5_run(phase="post")
        t = post.targets[0]
        original = copy.deepcopy(t.findings_json)
        baseline_id = t.baseline_target_id
        for item, baseline, error in ((pre.targets[0], pre.targets[1], "Only post"),
                                     (t, post.targets[0], "pre target"),
                                     (t, foreign.targets[0], "same project"),
                                     (t, pre.targets[1], "business_key"),
                                     (independent.targets[0], pre.targets[0], "same project")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                service.set_target_baseline(self.db, item, baseline)
        pre.targets[0].business_key = t.business_key = None
        with self.assertRaisesRegex(ValueError, "nonempty"):
            service.set_target_baseline(self.db, t, pre.targets[0])
        self.assertEqual(t.findings_json, original)
        self.assertEqual(t.baseline_target_id, baseline_id)

    def test_detach_and_move_cleanup_incoming_and_outgoing_baselines(self):
        pre = self.h5_run(project=self.project, venue_ids={"issues"})
        post = self.h5_run(phase="post", project=self.project, venue_ids={"issues"})
        self.assertEqual(post.targets[0].baseline_target_id, pre.targets[0].id)
        service.assign_run(self.db, post, None)
        self.assertIsNone(post.targets[0].baseline_target_id)
        service.assign_run(self.db, post, self.project)
        service.assign_run(self.db, pre, None)
        self.assertIsNone(post.targets[0].baseline_target_id)
        service.assign_run(self.db, pre, self.project)
        other = models.AuditProject(name="新项目")
        self.db.add(other)
        other_pre = self.h5_run(project=other, venue_ids={"issues"})
        service.assign_run(self.db, post, other)
        self.assertEqual(post.targets[0].baseline_target_id, other_pre.targets[0].id)
        service.assign_run(self.db, other_pre, self.project)
        self.assertIsNone(post.targets[0].baseline_target_id)

    def test_delete_fk_behaviors_loaded_and_unloaded(self):
        for loaded in (False, True):
            project = models.AuditProject(name="待删除")
            self.db.add(project)
            pre = self.h5_run(project=project, venue_ids={"issues"})
            post = self.h5_run(phase="post", project=project, venue_ids={"issues"})
            pre_id, target_id, post_id = pre.id, pre.targets[0].id, post.targets[0].id
            if loaded:
                self.assertEqual(len(project.runs), 2)
            else:
                self.db.expire(pre, ["targets"])
                self.db.expire(project, ["runs"])
            self.db.delete(pre)
            self.db.flush()
            self.db.expire_all()
            self.assertIsNone(self.db.get(models.AuditRun, pre_id))
            self.assertIsNone(self.db.get(models.AuditTarget, target_id))
            self.assertIsNone(self.db.get(models.AuditTarget, post_id).baseline_target_id)
            self.db.delete(project)
            self.db.flush()
            self.db.expire_all()
            self.assertIsNone(self.db.get(models.AuditRun, post.id).project_id)
            self.assertIsNotNone(self.db.get(models.AuditTarget, post_id))
        with self.assertRaises(IntegrityError), self.db.begin_nested():
            self.db.delete(self.h5_version)
            self.db.flush()

    @unittest.skipUnless(os.environ.get("AUDIT_REAL_RESULTS"), "Set AUDIT_REAL_RESULTS to the 408 results.json")
    def test_real_408_results(self):
        raw = Path(os.environ["AUDIT_REAL_RESULTS"]).read_bytes()
        start = time.monotonic()
        run = service.create_h5_run(self.db, raw, "results.json", self.h5_version, "真实408会场")
        duration = time.monotonic() - start
        self.assertEqual(len(run.targets), 408)
        self.assertEqual(run.summary_json["outcomes"], {"issues": 95, "needs_confirmation": 78,
                         "partial": 29, "capture_failed": 206, "clean": 0})
        self.assertEqual(run.summary_json["capture_reasons"]["offline"], 195)
        print(f"408 import: {json.dumps(run.summary_json, ensure_ascii=False)}; {duration:.3f}s", flush=True)
