"""Request-time analytics over fully loaded audit objects; no database access.

Only enabled, carrier-applicable, canonical rules contribute issue counts.
Strips retain spec order: x suppresses disabled/inapplicable/duplicate rules;
- means missing coverage or not applicable. Outcome filters leave composition
unfiltered so it can continue to serve as the filter's denominator.

Stages and systemic clusters describe current pages. Comparison clusters and
flow describe every linked post; target IDs identify repeated page occurrences.
Independent evidence gaps are counted separately from comparison uncertainty.
Matrix columns use the latest pre version, grouped by first-seen clause order;
delta follows the latest post's actual baseline, which may be an older pre.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations

from app.services.audit_workspace import CAPTURE_REASONS, COMPARE_CATEGORIES, OUTCOMES, compare_targets

STAGES = ("review", "recheck", "baseline", "post", "closed")
STATUS_CODES = {"fail": "F", "uncertain": "U", "pass": "P", "not_applicable": "-", "disabled": "x"}
DELTA_CODES = {"fixed": "F", "still_open": "O", "regressed": "R", "new_issue": "N",
               "kept": "K", "needs_confirmation": "U", "not_comparable": "-"}


def effective_status(status, review=None):
    """Human decisions affect closure without overwriting the captured finding."""
    verdict = review.get("verdict") if review else None
    corrected = review.get("corrected_status") if review else None
    if verdict == "confirmed" and status == "uncertain":
        status = "fail"
    elif verdict == "false_positive":
        status = corrected or "pass"
    elif verdict == "false_negative":
        status = corrected or "fail"
    elif verdict == "exception":
        status = "pass"
    return {"effective_status": status, "excepted": verdict == "exception",
            "needs_recapture": verdict == "recapture"}


def latest_reviews(target):
    latest = {}
    for review in sorted(getattr(target, "reviews", ()), key=lambda r: (r.created_at, str(r.id))):
        latest[review.rule_id] = {
            "id": str(review.id), "target_id": str(review.target_id), "rule_id": review.rule_id,
            "verdict": review.verdict, "corrected_status": review.corrected_status, "note": review.note,
            "created_by": str(review.created_by) if review.created_by else None, "created_at": review.created_at,
        }
    return latest


def reviewed_findings(target):
    reviews = latest_reviews(target)
    findings = list(target.findings_json)
    known = {f["rule_id"] for f in findings}
    # A missed rule may have no source finding. Preserve it in detail and analytics.
    findings += [{"rule_id": r["rule_id"], "title": r["title"], "status": "not_applicable",
                  "observed": "", "reason": "原始审核未覆盖，人工补记", "uncovered": True,
                  "evidence": {"image_ids": [], "kind": "h5_report"}}
                 for r in target.run.spec_version.rules_json if r["rule_id"] in reviews and r["rule_id"] not in known]
    return [{**f, "review": reviews.get(f["rule_id"]),
             **effective_status(f["status"], reviews.get(f["rule_id"]))} for f in findings]


def effective_findings(target):
    return [{**f, "status": f["effective_status"]} for f in reviewed_findings(target)]


def rule_quality(version, targets):
    verdicts = ("confirmed", "false_positive", "false_negative", "exception", "recapture")

    def finish(counts):
        reviewed = sum(counts[v] for v in verdicts)
        return {**{v: counts[v] for v in verdicts}, "reviewed": reviewed,
                "fp_rate": counts["flagged_fp"] / counts["flagged_reviewed"] if counts["flagged_reviewed"] else None,
                "fn_rate": counts["false_negative"] / (reviewed - counts["recapture"]) if reviewed > counts["recapture"] else None,
                "uncertain_rate": counts["uncertain"] / counts["findings"] if counts["findings"] else None,
                "findings": counts["findings"], "insufficient": reviewed < 10}

    buckets = defaultdict(lambda: defaultdict(Counter))
    for target in targets:
        if target.outcome == "capture_failed":
            continue  # gated pages carry placeholder findings, not model judgements
        source_ids = {f["rule_id"] for f in target.findings_json}
        for finding in reviewed_findings(target):
            method = (finding.get("evidence") or {}).get("method") or finding.get("method", "model")
            method = method if method in {"dom", "pixel"} else "model"
            counts = buckets[finding["rule_id"]][method]
            if finding["rule_id"] in source_ids:
                counts["findings"] += 1
                counts["uncertain"] += finding["status"] == "uncertain"
            review = finding["review"]
            if review:
                verdict = review["verdict"]
                counts[verdict] += 1
                if (finding.get("model_status") or finding["status"]) == "fail" and verdict in {"confirmed", "false_positive"}:
                    counts["flagged_reviewed"] += 1
                    counts["flagged_fp"] += verdict == "false_positive"
    rows = []
    for rule in version.rules_json:
        methods = buckets[rule["rule_id"]]
        total = Counter()
        for counts in methods.values():
            total.update(counts)
        rows.append({"rule_id": rule["rule_id"], "title": rule["title"], **finish(total),
                     "by_method": {m: finish(methods[m]) for m in ("model", "dom", "pixel")}})
    return {"spec_version_id": str(version.id), "rules": rows}


def _active(rule, carrier):
    return rule["enabled"] and carrier in rule["carriers"] and not rule.get("duplicate_of")


def _statuses(target):
    return {f["rule_id"]: f["effective_status"] for f in reviewed_findings(target)}


def _counts(target):
    statuses = _statuses(target)
    return Counter(statuses.get(r["rule_id"]) for r in target.run.spec_version.rules_json
                   if _active(r, target.run.carrier))


def effective_outcome(target):
    if target.outcome == "capture_failed" or not getattr(target, "reviews", ()):
        return target.outcome
    counts = _counts(target)
    return "issues" if counts["fail"] else "needs_confirmation" if counts["uncertain"] else "partial" if target.outcome == "partial" else "clean"


def effective_summary(target):
    counts = _counts(target)
    return {**target.summary_json, **{s: counts[s] for s in ("fail", "pass", "uncertain", "not_applicable", "disabled")}}


def _severity(target):
    counts = _counts(target)
    return (-counts["fail"], -counts["uncertain"], target.name.casefold(), str(target.id))


def _brief(target):
    counts = _counts(target)
    return {"id": str(target.id), "name": target.name, "business_key": target.business_key,
            "outcome": effective_outcome(target), "fail": counts["fail"], "uncertain": counts["uncertain"],
            "capture_reason": target.capture_reason, "baseline_target_id": target.baseline_target_id}


def _strip(target, rules):
    if target is None or target.outcome == "capture_failed":
        return "-" * len(rules)
    own_rules = {r["rule_id"]: r for r in target.run.spec_version.rules_json}
    statuses = _statuses(target)
    return "".join(STATUS_CODES.get(statuses.get(r["rule_id"]), "-")
                   if r["rule_id"] in own_rules and _active(own_rules[r["rule_id"]], target.run.carrier)
                   else "x" for r in rules)


def _validate_outcome(outcome):
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError("Unknown outcome")


def target_list(targets, *, page=1, page_size=20, search=None, outcome=None, sort="fail"):
    _validate_outcome(outcome)
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError("Page must be positive; page_size must be between 1 and 100")
    if sort not in {"fail", "uncertain", "name"}:
        raise ValueError("Sort must be fail, uncertain or name")
    needle = (search or "").strip().casefold()
    selected = [t for t in targets if (outcome is None or effective_outcome(t) == outcome)
                and (not needle or needle in t.name.casefold() or needle in (t.business_key or "").casefold())]
    rows = [_brief(t) for t in selected]
    rows.sort(key=lambda r: ((-r[sort],) if sort != "name" else ()) + (r["name"].casefold(), r["id"]))
    start = (page - 1) * page_size
    return {"total": len(rows), "page": page, "page_size": page_size, "items": rows[start:start + page_size]}


def run_cockpit(run, outcome=None):
    _validate_outcome(outcome)
    targets = list(run.targets)
    selected = [t for t in targets if outcome is None or effective_outcome(t) == outcome]
    rules = run.spec_version.rules_json
    active = [r for r in rules if _active(r, run.carrier)]
    order = {r["rule_id"]: i for i, r in enumerate(rules)}
    outcomes = Counter(effective_outcome(t) for t in targets)
    reasons = Counter(t.capture_reason or "other" for t in targets if t.outcome == "capture_failed")
    fails, uncertain, pairs, gaps = Counter(), Counter(), Counter(), Counter()
    batches = defaultdict(list)
    focus, strips = [], []
    shared = Counter()
    for target in sorted(selected, key=_severity):
        if target.outcome == "capture_failed":
            continue
        statuses = _statuses(target)
        failed = [r["rule_id"] for r in active if statuses.get(r["rule_id"]) == "fail"]
        pending = [r["rule_id"] for r in active if statuses.get(r["rule_id"]) == "uncertain"]
        fails.update(failed)
        uncertain.update(pending)
        pairs.update(combinations(failed, 2))
        for rule in rules:
            if rule.get("duplicate_of") and statuses.get(rule["rule_id"]) == statuses.get(rule["duplicate_of"]) == "fail":
                shared[(rule["duplicate_of"], rule["rule_id"])] += 1
        strips.append({"id": str(target.id), "name": target.name, "outcome": effective_outcome(target), "s": _strip(target, rules)})
        if len(failed) >= 3:
            focus.append({"id": str(target.id), "name": target.name, "fail": len(failed), "uncertain": len(pending)})
        if len(failed) == 1:
            batches[failed[0]].append(str(target.id))
        if effective_outcome(target) == "needs_confirmation":
            gaps.update(pending)
    pareto = [{"rule_id": r["rule_id"], "title": r["title"], "fail": fails[r["rule_id"]],
               "uncertain": uncertain[r["rule_id"]]} for r in active]
    pareto.sort(key=lambda row: (-row["fail"], order[row["rule_id"]]))
    recapture = Counter(t.capture_reason or "other" for t in selected if t.outcome == "capture_failed")
    return {
        "rule_order": [r["rule_id"] for r in rules], "status_codes": STATUS_CODES,
        "composition": {"total": len(targets), "outcomes": {k: outcomes[k] for k in OUTCOMES},
                        "capture_reasons": {k: reasons[k] for k in CAPTURE_REASONS}},
        "pareto": pareto,
        "cooccurrence": {"pairs": [{"rules": list(pair), "count": count} for pair, count in pairs.most_common(5)],
                         "shared_evidence": [{"rules": list(pair), "count": count} for pair, count in shared.most_common()],
                         "note": "共享证据已合并"},
        "strips": strips,
        "triage": {"focus": focus,
                   "batches": [{"rule_id": key, "count": len(ids), "target_ids": ids}
                               for key, ids in sorted(batches.items(), key=lambda item: (-len(item[1]), order[item[0]]))],
                   "evidence_gaps": [{"rule_id": key, "count": count} for key, count in gaps.most_common(5)],
                   "recapture": {"total": sum(recapture.values()), "offline": recapture["offline"],
                                 "by_reason": {k: recapture[k] for k in CAPTURE_REASONS if k != "offline"}}},
    }


def _time_key(target):
    return (target.run.created_at, str(target.run.id), str(target.id))


def _pages(runs):
    pages = defaultdict(list)
    for run in runs:
        for target in run.targets:
            pages[target.business_key or f"t:{target.id}"].append(target)
    return {key: sorted(targets, key=_time_key) for key, targets in sorted(pages.items())}


def _latest(targets, phase):
    return next((t for t in reversed(targets) if t.run.phase == phase), None)


def _stage(targets):
    post = _latest(targets, "post")
    if post is not None:
        counts = _counts(post)
        return "closed" if post.baseline_target_id and not (counts["fail"] or counts["uncertain"]) else "post"
    pre = _latest(targets, "pre")
    counts = _counts(pre)
    if counts["fail"] or counts["uncertain"]:
        return "recheck" if sum(t.run.phase == "pre" for t in targets) > 1 else "review"
    return "baseline"


def _page_brief(key, targets):
    latest = targets[-1]
    return {"id": key, "name": latest.name, "outcome": effective_outcome(latest)}


def _comparison(pre, post):
    result = compare_targets(pre, post)
    duplicates = {r["rule_id"] for t in (pre, post) for r in t.run.spec_version.rules_json if r.get("duplicate_of")}
    return {**result, "rules": [r for r in result["rules"] if r["rule_id"] not in duplicates]}


def project_cockpit(runs):
    runs = list(runs)
    pages = _pages(runs)
    targets_by_id = {t.id: t for targets in pages.values() for t in targets}
    stages = {stage: {"count": 0, "pages": []} for stage in STAGES}
    systemic, carried, fixed = defaultdict(list), defaultdict(list), defaultdict(list)
    regressed, evidence_pages = [], []
    edges, counts = Counter(), Counter(dict.fromkeys(COMPARE_CATEGORIES, 0))
    linked_posts = 0
    for key, targets in pages.items():
        brief = _page_brief(key, targets)
        stages[_stage(targets)]["pages"].append(brief)
        latest = targets[-1]
        if latest.outcome != "capture_failed":
            statuses = _statuses(latest)
            for rule in latest.run.spec_version.rules_json:
                if _active(rule, latest.run.carrier) and statuses.get(rule["rule_id"]) == "fail":
                    systemic[rule["rule_id"]].append(brief)
        compared_gaps = 0
        # Flow and comparison clusters use every linked post, not just the latest.
        for post in targets:
            pre = targets_by_id.get(post.baseline_target_id)
            if post.run.phase != "post" or pre is None:
                continue
            linked_posts += 1
            result = _comparison(pre, post)
            counts.update(result["counts"])
            for row in result["rules"]:
                category = row["category"]
                if category != "not_comparable":
                    origin = row["pre_status"] if row["pre_status"] in {"fail", "pass", "uncertain"} else "uncovered"
                    edges[(origin, category)] += 1
                occurrence = {**brief, "target_id": str(post.id), "baseline_target_id": str(pre.id),
                              "pre_status": row["pre_status"], "post_status": row["post_status"]}
                if category == "regressed":
                    regressed.append({"rule_id": row["rule_id"], "page": occurrence})
                elif category == "still_open":
                    carried[row["rule_id"]].append(occurrence)
                elif category == "fixed":
                    fixed[row["rule_id"]].append(occurrence)
                elif category == "needs_confirmation":
                    compared_gaps += 1
        # Unlinked pages still need evidence work. Keep that contribution explicit
        # so linked uncertainty reconciles exactly with compare_targets/flow.
        independent_gaps = 0
        if latest.outcome != "capture_failed" and not latest.baseline_target_id:
            independent_gaps = _counts(latest)["uncertain"]
        if compared_gaps or independent_gaps:
            evidence_pages.append({**brief, "count": compared_gaps + independent_gaps,
                                   "comparison_count": compared_gaps, "independent_count": independent_gaps})
    for stage in stages.values():
        stage["count"] = len(stage["pages"])
    stage_specs = {}
    for phase in ("pre", "post"):
        versions = {str(r.spec_version.id): r.spec_version for r in sorted(runs, key=lambda r: (r.created_at, str(r.id))) if r.phase == phase}
        stage_specs[phase] = [{"id": key, "spec_id": str(v.spec_id), "label": v.label} for key, v in versions.items()]
    return {"page_count": len(pages), "run_count": len(runs), "stages": stages, "stage_specs": stage_specs,
            "clusters": {
                "regressed": {"total": counts["regressed"], "items": regressed},
                "systemic": [{"rule_id": rule_id, "count": len(items), "pages": items}
                             for rule_id, items in sorted(systemic.items())
                             if len(items) >= 3 or len(items) * 10 >= len(pages) * 3],
                "carried": {"total": counts["still_open"], "rules": [
                    {"rule_id": key, "count": len(items), "pages": items, "fixed_pages": fixed[key]}
                    for key, items in sorted(carried.items())]},
                "evidence_gaps": {"total": sum(p["count"] for p in evidence_pages),
                                  "comparison_total": counts["needs_confirmation"],
                                  "independent_total": sum(p["independent_count"] for p in evidence_pages),
                                  "pages": evidence_pages}},
            "flow": {"edges": [{"from": a, "to": b, "count": count} for (a, b), count in sorted(edges.items())],
                     "counts": dict(counts), "not_comparable": counts["not_comparable"], "linked_posts": linked_posts}}


def project_matrix(runs):
    runs = list(runs)
    pre_runs = sorted((r for r in runs if r.phase == "pre"), key=lambda r: (r.created_at, str(r.id)))
    version = pre_runs[-1].spec_version if pre_runs else None
    by_clause = defaultdict(list)
    for rule in version.rules_json if version else []:
        if rule["enabled"]:
            by_clause[rule["clause"]].append(rule)
    rules = [r for group in by_clause.values() for r in group]
    distributions = {r["rule_id"]: Counter(dict.fromkeys(("fail", "pass", "uncertain", "uncovered"), 0)) for r in rules}
    rows = []
    for key, targets in _pages(runs).items():
        pre, post = _latest(targets, "pre"), _latest(targets, "post")
        # Delta follows the actual baseline, even if a newer pre exists.
        baseline = next((t for t in targets if post and t.id == post.baseline_target_id), None)
        comparison = _comparison(baseline, post) if baseline else {"rules": []}
        categories = {r["rule_id"]: r["category"] for r in comparison["rules"]}
        pre_string = _strip(pre, rules)
        for rule, code in zip(rules, pre_string):
            distributions[rule["rule_id"]][{"F": "fail", "P": "pass", "U": "uncertain"}.get(code, "uncovered")] += 1
        rows.append({**_page_brief(key, targets), "pre": pre_string, "post": _strip(post, rules),
                     "pre_target_id": str(pre.id) if pre else None, "post_target_id": str(post.id) if post else None,
                     "baseline_target_id": str(baseline.id) if baseline else None,
                     "delta": "".join(DELTA_CODES[categories.get(r["rule_id"], "not_comparable")] for r in rules)})
    return {"spec_version_id": str(version.id) if version else None, "rules": rules,
            "clauses": [{"clause": clause, "rule_ids": [r["rule_id"] for r in group]}
                        for clause, group in by_clause.items()],
            "pages": rows, "pre_distribution": {key: dict(value) for key, value in distributions.items()},
            "delta_codes": DELTA_CODES, "status_codes": STATUS_CODES}


def page_lifeline(runs, page_key):
    targets = _pages(runs).get(page_key)
    if targets is None:
        raise LookupError("Page not found in project")
    timeline = [{**_brief(t), "run_id": str(t.run.id), "run_name": t.run.name, "phase": t.run.phase,
                 "carrier": t.run.carrier, "spec_version_id": str(t.run.spec_version.id),
                 "spec_label": t.run.spec_version.label, "date": t.run.created_at,
                 "audited_at": t.run.source_ref_json.get("generated_at") or t.run.created_at,
                 "summary": effective_summary(t),
                 "demo": bool(t.run.source_ref_json.get("demo"))} for t in targets]
    # Inputs can mix ISO report timestamps with naive database datetimes (UTC).
    # Python's stable sort retains the existing _time_key order for ties.
    def audit_time(item):
        value = item["audited_at"]
        date = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date

    timeline.sort(key=audit_time)
    post = _latest(targets, "post")
    baseline = next((t for t in targets if post and t.id == post.baseline_target_id), None)
    comparison = _comparison(baseline, post) if baseline else None
    groups = {"need_action": [], "needs_confirmation": [], "closed": []}
    if comparison:
        for row in comparison["rules"]:
            if row["category"] in {"regressed", "still_open", "new_issue"}:
                groups["need_action"].append(row)
            elif row["category"] == "needs_confirmation":
                groups["needs_confirmation"].append(row)
            elif row["category"] in {"fixed", "kept"}:
                groups["closed"].append(row)
    return {"id": page_key, "name": targets[-1].name, "stage": _stage(targets), "timeline": timeline,
            "independent_check": bool(post and baseline is None), "comparison": comparison, "groups": groups}
