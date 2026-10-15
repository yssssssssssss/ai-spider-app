import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.encoders import jsonable_encoder
from app.services import audit_analytics as analytics
from app.services.audit_workspace import compare_targets


def rule(rule_id, **changes):
    return {"rule_id": rule_id, "title": rule_id, "clause": "一", "expected": "符合规范",
            "enabled": True, "carriers": ["h5", "app"], "duplicate_of": None, **changes}


def version(rules):
    return SimpleNamespace(id=uuid4(), spec_id=uuid4(), label="测试-v1", rules_json=rules)


def run(rules, phase="pre", day=0, spec=None):
    return SimpleNamespace(id=uuid4(), name="审核", phase=phase, carrier="h5", spec_version=spec or version(rules),
                           created_at=datetime(2026, 10, 1) + timedelta(days=day), targets=[], source_ref_json={})


def target(run, statuses, key=None, name=None, outcome=None, baseline=None, reason=None):
    counts = {s: list(statuses.values()).count(s) for s in ("fail", "uncertain", "pass")}
    target = SimpleNamespace(id=uuid4(), run=run, business_key=key, name=name or key or "页面",
                             outcome=outcome or ("issues" if counts["fail"] else "needs_confirmation" if counts["uncertain"] else "clean"),
                             capture_reason=reason, baseline_target_id=baseline.id if baseline else None,
                             summary_json=counts, findings_json=[
                                 {"rule_id": k, "title": k, "status": v, "observed": f"{run.phase}: {k} {v}"}
                                 for k, v in statuses.items()])
    run.targets.append(target)
    return target


class RunCockpitTests(unittest.TestCase):
    def setUp(self):
        self.rules = [rule("B"), rule("A"), rule("C"), rule("D", duplicate_of="A"), rule("E", enabled=False),
                      rule("G", carriers=["app"])]
        self.run = run(self.rules)
        self.focus = target(self.run, {"A": "fail", "B": "fail", "C": "fail", "D": "fail", "E": "fail", "G": "fail"}, "focus")
        self.one = target(self.run, {"A": "fail", "D": "fail", "B": "uncertain", "C": "pass"}, "one")
        self.two = target(self.run, {"B": "fail", "C": "fail"}, "two")
        self.gap = target(self.run, {"B": "uncertain", "A": "uncertain", "D": "uncertain", "C": "not_applicable"}, "gap")
        self.partial = target(self.run, {"B": "pass", "A": "not_applicable"}, "partial", outcome="partial")
        for reason in ("offline", "offline", "expired", "login_required", "other"):
            target(self.run, {"A": "fail"}, reason, outcome="capture_failed", reason=reason)

    def test_composition_pareto_filter_and_no_duplicate_inflation(self):
        result = analytics.run_cockpit(self.run)
        self.assertEqual(result["composition"], {
            "total": 10, "outcomes": {"issues": 3, "needs_confirmation": 1, "partial": 1, "clean": 0, "capture_failed": 5},
            "capture_reasons": {"offline": 2, "expired": 1, "login_required": 1, "other": 1}})
        self.assertEqual(result["pareto"], [
            {"rule_id": "B", "title": "B", "fail": 2, "uncertain": 2},
            {"rule_id": "A", "title": "A", "fail": 2, "uncertain": 1},
            {"rule_id": "C", "title": "C", "fail": 2, "uncertain": 0}])
        filtered = analytics.run_cockpit(self.run, "needs_confirmation")
        self.assertEqual(sum(r["fail"] for r in filtered["pareto"]), 0)
        self.assertEqual(len(filtered["strips"]), 1)
        self.assertEqual(filtered["composition"], result["composition"])

    def test_cooccurrence_shared_evidence_and_top_five(self):
        result = analytics.run_cockpit(self.run)["cooccurrence"]
        self.assertEqual(result["pairs"][0], {"rules": ["B", "C"], "count": 2})
        self.assertEqual(result["shared_evidence"], [{"rules": ["A", "D"], "count": 2}])
        self.assertEqual(result["note"], "共享证据已合并")
        wide = run([rule(str(i)) for i in range(6)])
        target(wide, {str(i): "fail" for i in range(6)})
        self.assertEqual(len(analytics.run_cockpit(wide)["cooccurrence"]["pairs"]), 5)

    def test_strips_spec_order_severity_and_no_mutation(self):
        before = copy.deepcopy(self.focus.findings_json)
        result = analytics.run_cockpit(self.run)
        self.assertEqual([r["id"] for r in result["strips"]], [str(t.id) for t in (self.focus, self.two, self.one, self.gap, self.partial)])
        self.assertEqual([r["s"] for r in result["strips"]], ["FFFxxx", "F-Fxxx", "UFPxxx", "UU-xxx", "P--xxx"])
        self.assertTrue(all(set(r) == {"id", "name", "outcome", "s"} for r in result["strips"]))
        self.assertEqual(self.focus.findings_json, before)

    def test_strip_uncertainty_breaks_equal_fail_counts(self):
        source = run([rule("A"), rule("B")])
        lower = target(source, {"A": "fail", "B": "pass"}, "a")
        higher = target(source, {"A": "fail", "B": "uncertain"}, "z")
        self.assertEqual([r["id"] for r in analytics.run_cockpit(source)["strips"]],
                         [str(higher.id), str(lower.id)])

    def test_triage_all_four_groups(self):
        result = analytics.run_cockpit(self.run)["triage"]
        self.assertEqual(result["focus"], [{"id": str(self.focus.id), "name": "focus", "fail": 3, "uncertain": 0}])
        self.assertEqual(result["batches"], [{"rule_id": "A", "count": 1, "target_ids": [str(self.one.id)]}])
        self.assertEqual(result["evidence_gaps"], [{"rule_id": "B", "count": 1}, {"rule_id": "A", "count": 1}])
        self.assertEqual(result["recapture"], {"total": 5, "offline": 2,
                                               "by_reason": {"expired": 1, "login_required": 1, "other": 1}})
        wide = run([rule(str(i)) for i in range(7)])
        target(wide, {str(i): "uncertain" for i in range(7)})
        self.assertEqual(len(analytics.run_cockpit(wide)["triage"]["evidence_gaps"]), 5)

    def test_list_pagination_search_filters_and_sort(self):
        generated = run([rule("A"), rule("B")])
        for i in range(25):
            target(generated, {"A": "fail" if i % 2 else "uncertain", "B": "uncertain" if i == 3 else "pass"},
                   f"KEY-{i:02}", name=f"会场{i:02}")
        result = analytics.target_list(generated.targets)
        self.assertEqual((result["total"], len(result["items"]), result["page_size"]), (25, 20, 20))
        self.assertEqual(len(analytics.target_list(generated.targets, page=2)["items"]), 5)
        self.assertEqual(analytics.target_list(generated.targets, page=9)["items"], [])
        self.assertEqual(analytics.target_list(generated.targets, search="key-03")["total"], 1)
        self.assertEqual(analytics.target_list(generated.targets, search="会场0", outcome="issues")["total"], 5)
        self.assertEqual(analytics.target_list(generated.targets, sort="name")["items"][0]["name"], "会场00")
        self.assertEqual(analytics.target_list(generated.targets, sort="uncertain")["items"][0]["name"], "会场00")
        self.assertEqual(analytics.target_list(generated.targets, page_size=100)["total"], 25)
        for kwargs in ({"page": 0}, {"page_size": 101}, {"page_size": 0}, {"outcome": "bad"}, {"sort": "bad"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analytics.target_list(generated.targets, **kwargs)

    def test_generated_408_payload_budget(self):
        big = run([rule(f"OV-{i:03}") for i in range(23)])
        for i in range(408):
            target(big, {r["rule_id"]: ("fail", "uncertain", "pass")[i % 3] for r in big.spec_version.rules_json},
                   str(i), name=f"官方会场{i:03}：家电数码服饰百货")
            # Long observations must never leak into the cockpit payload.
            for finding in big.targets[-1].findings_json:
                finding["observed"] = "观测文字" * 1000
        payload = json.dumps(jsonable_encoder(analytics.run_cockpit(big)), ensure_ascii=False).encode()
        self.assertLess(len(payload), 200_000)
        print(f"Generated 408 cockpit payload: {len(payload)} bytes")


class ProjectCockpitTests(unittest.TestCase):
    def test_five_stages_latest_pre_post_and_null_keys(self):
        rules = [rule("A"), rule("D", duplicate_of="A")]
        pre = run(rules)
        target(pre, {"A": "uncertain"}, "review")
        target(pre, {"A": "fail"}, "recheck")
        target(pre, {"A": "pass", "D": "fail"}, "baseline", outcome="partial")
        base_post = target(pre, {"A": "fail"}, "post")
        base_closed = target(pre, {"A": "fail"}, "closed")
        target(pre, {"A": "pass"})
        target(pre, {"A": "pass"})
        recheck = run(rules, day=1)
        target(recheck, {"A": "uncertain"}, "recheck")
        post = run(rules, "post", day=2)
        target(post, {"A": "fail"}, "post", baseline=base_post)
        target(post, {"A": "pass", "D": "uncertain"}, "closed", baseline=base_closed)
        target(post, {"A": "pass"}, "independent")
        result = analytics.project_cockpit([pre, recheck, post])
        self.assertEqual({k: v["count"] for k, v in result["stages"].items()},
                         {"review": 1, "recheck": 1, "baseline": 3, "post": 2, "closed": 1})
        self.assertEqual(result["page_count"], sum(s["count"] for s in result["stages"].values()))
        self.assertTrue(all(s["count"] == len(s["pages"]) for s in result["stages"].values()))
        self.assertEqual(len(result["stage_specs"]["pre"]), 2)

    def test_systemic_absolute_and_percentage_boundaries(self):
        for total, failures, expected in ((10, 2, False), (10, 3, True), (7, 2, False), (6, 2, True),
                                          (100, 29, True), (100, 30, True)):
            # 29% and 30% both qualify via >=3. 2/7 vs 2/6 isolates the percentage branch.
            with self.subTest(total=total, failures=failures):
                source = run([rule("A")])
                for i in range(total):
                    target(source, {"A": "fail" if i < failures else "pass"}, str(i))
                result = analytics.project_cockpit([source])["clusters"]["systemic"]
                self.assertEqual(bool(result), expected)
                if expected:
                    self.assertEqual(result[0]["count"], failures)
                    self.assertEqual(len({p["id"] for p in result[0]["pages"]}), failures)

    def comparison_runs(self):
        rules = [rule(str(i), clause="一" if i < 4 else "二") for i in range(8)] + [rule("dup", duplicate_of="1")]
        rules[7]["enabled"] = False
        pre = run(rules)
        post = run(rules, "post", day=1)
        before = {"0": "fail", "1": "fail", "2": "pass", "3": "not_applicable", "4": "pass",
                  "5": "uncertain", "6": "disabled", "7": "pass", "dup": "fail"}
        after = {"0": "pass", "1": "fail", "2": "fail", "3": "fail", "4": "pass",
                 "5": "pass", "6": "disabled", "7": "fail", "dup": "fail"}
        baseline = target(pre, before, "page")
        target(post, after, "page", baseline=baseline)
        other = target(pre, {"1": "fail"}, "fixed")
        target(post, {"1": "pass"}, "fixed", baseline=other)
        # Multiple posts on one page must all reconcile with comparisons.
        newer = run(rules, "post", day=2)
        target(newer, after, "page", baseline=baseline)
        return pre, post, newer

    def test_flow_and_clusters_reconcile_with_every_compare_result(self):
        runs = self.comparison_runs()
        targets = {t.id: t for r in runs for t in r.targets}
        expected = dict.fromkeys(analytics.COMPARE_CATEGORIES, 0)
        for source in runs:
            for post in source.targets:
                if post.baseline_target_id:
                    comparison = compare_targets(targets[post.baseline_target_id], post)
                    for key, count in comparison["counts"].items():
                        expected[key] += count
        result = analytics.project_cockpit(runs)
        flow, clusters = result["flow"], result["clusters"]
        self.assertEqual(flow["counts"], expected)
        self.assertEqual(flow["linked_posts"], 3)
        for category in analytics.COMPARE_CATEGORIES:
            if category == "not_comparable":
                self.assertEqual(flow["not_comparable"], expected[category])
            else:
                self.assertEqual(sum(e["count"] for e in flow["edges"] if e["to"] == category), expected[category])
        self.assertEqual(sum(e["count"] for e in flow["edges"]) + flow["not_comparable"], sum(expected.values()))
        self.assertEqual({e["from"] for e in flow["edges"]}, {"fail", "pass", "uncertain", "uncovered"})
        self.assertEqual(clusters["regressed"]["total"], expected["regressed"])
        self.assertEqual(len(clusters["regressed"]["items"]), expected["regressed"])
        self.assertEqual(clusters["carried"]["total"], expected["still_open"])
        self.assertEqual(sum(r["count"] for r in clusters["carried"]["rules"]), expected["still_open"])
        gaps = clusters["evidence_gaps"]
        self.assertEqual(gaps["comparison_total"], expected["needs_confirmation"])
        self.assertEqual(sum(p["comparison_count"] for p in gaps["pages"]), expected["needs_confirmation"])
        self.assertEqual(gaps["total"], gaps["comparison_total"] + gaps["independent_total"])
        carried = clusters["carried"]["rules"][0]
        self.assertEqual(carried["rule_id"], "1")
        self.assertEqual([p["id"] for p in carried["fixed_pages"]], ["fixed"])
        self.assertFalse(any(r["rule_id"] == "dup" for r in clusters["systemic"]))

    def test_matrix_three_modes_distributions_and_lifeline_groups(self):
        runs = self.comparison_runs()
        matrix = analytics.project_matrix(runs)
        page = next(p for p in matrix["pages"] if p["id"] == "page")
        self.assertEqual(page["pre"], "FFP-xPUx")
        self.assertEqual(page["post"], "PFFFxPPx")
        self.assertEqual(page["delta"], "FORN-KU-")
        self.assertEqual(len(matrix["clauses"]), 2)
        for distribution in matrix["pre_distribution"].values():
            self.assertEqual(sum(distribution.values()), len(matrix["pages"]))
        life = analytics.page_lifeline(runs, "page")
        self.assertEqual([t["phase"] for t in life["timeline"]], ["pre", "post", "post"])
        self.assertEqual(len(life["groups"]["need_action"]), 3)
        self.assertEqual(len(life["groups"]["needs_confirmation"]), 1)
        self.assertEqual(len(life["groups"]["closed"]), 2)
        for group in life["groups"].values():
            for row in group:
                self.assertIn("pre:", row["pre_observed"])
                self.assertIn("post:", row["post_observed"])
        self.assertTrue(life["comparison"]["spec_mismatch"])
        with self.assertRaises(LookupError):
            analytics.page_lifeline(runs, "foreign")

    def test_matrix_uses_latest_pre_columns_and_actual_post_baseline(self):
        rules = [rule("A", clause="一"), rule("B", clause="二"), rule("C", clause="一")]
        pre = run(rules)
        baseline = target(pre, {"A": "fail", "B": "pass", "C": "pass"}, "page")
        post = run(rules, "post", day=1)
        target(post, {"A": "pass", "B": "pass", "C": "pass"}, "page", baseline=baseline)
        newer = run([*rules, rule("D", clause="二")], day=2)
        latest = target(newer, {"A": "pass", "B": "pass", "C": "pass", "D": "fail"}, "page")
        result = analytics.project_matrix([newer, post, pre])
        self.assertEqual(result["spec_version_id"], str(newer.spec_version.id))
        self.assertEqual([r["rule_id"] for r in result["rules"]], ["A", "C", "B", "D"])
        self.assertEqual(result["pages"][0]["pre"], "PPPF")
        self.assertEqual(result["pages"][0]["delta"], "FKK-")
        self.assertEqual(result["pages"][0]["pre_target_id"], str(latest.id))
        self.assertEqual(result["pages"][0]["baseline_target_id"], str(baseline.id))
        self.assertEqual(analytics.page_lifeline([newer, pre, post], "page")["stage"], "closed")

    def test_evidence_gaps_comparisons_and_independent_lifeline(self):
        pre = run([rule("A"), rule("B"), rule("D", duplicate_of="A")])
        t = target(pre, {"A": "uncertain", "B": "uncertain", "D": "uncertain"}, "old")
        post = run(pre.spec_version.rules_json, "post", day=1)
        target(post, {"A": "pass"}, "old", baseline=t)
        target(post, {"A": "uncertain", "D": "uncertain"}, "independent")
        post.source_ref_json = {"demo": True}
        gaps = analytics.project_cockpit([pre, post])["clusters"]["evidence_gaps"]
        self.assertEqual(gaps["total"], 3)
        self.assertEqual(gaps["comparison_total"], 2)
        self.assertEqual(gaps["independent_total"], 1)
        self.assertEqual(sum(p["count"] for p in gaps["pages"]), 3)
        life = analytics.page_lifeline([pre, post], "independent")
        self.assertTrue(life["independent_check"])
        self.assertIsNone(life["comparison"])
        self.assertTrue(life["timeline"][0]["demo"])
        self.assertEqual(analytics.project_matrix([post])["rules"], [])
        self.assertEqual(analytics.project_cockpit([])["page_count"], 0)
