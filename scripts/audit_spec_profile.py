"""Convert AuditSpecVersion rules_json/source_json to an H5 rerun profile."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


def require_fields(value, fields, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"{name} missing required fields: {', '.join(missing)}")


def build_profile(rules_json, source_json):
    if not isinstance(source_json, dict) or source_json.get("audit_mode") != "h5_v2":
        raise ValueError('source_json.audit_mode must be "h5_v2"')
    require_fields(source_json, ("version", "title", "source", "rules", "spacing", "text_count",
                                "frameworks", "result_policy", "policy_source"), "source_json")
    require_fields(source_json["source"], ("sha256",), "source_json.source")
    for policy in ("frameworks", "result_policy", "policy_source"):
        require_fields(source_json[policy], (), f"source_json.{policy}")
    require_fields(source_json["text_count"], ("scope", "max_characters", "counting"), "source_json.text_count")
    spacing = source_json["spacing"]
    require_fields(spacing, (), "source_json.spacing")
    if "acceptable_range_px" in spacing:
        require_fields(spacing["acceptable_range_px"], ("min", "max", "unit", "inclusive"),
                       "source_json.spacing.acceptable_range_px")
    else:
        require_fields(spacing, ("expected_px", "reference_viewport_height_px", "calibration_confirmed", "tolerance_px"),
                       "source_json.spacing")
    if not isinstance(rules_json, list) or not isinstance(source_json["rules"], list):
        raise ValueError("rules_json and source_json.rules must be lists")
    source_rules = {}
    for rule in source_json["rules"]:
        require_fields(rule, ("id",), "source_json rule")
        if rule["id"] in source_rules:
            raise ValueError(f"duplicate source rule: {rule['id']}")
        source_rules[rule["id"]] = rule
    strengths = {"mandatory": "mandatory", "conditional": "conditional_mandatory", "recommended": "recommendation"}
    rules, seen = [], set()
    for rule in rules_json:
        require_fields(rule, ("rule_id", "title", "expected", "strength", "enabled", "carriers"), "rules_json rule")
        rid = rule["rule_id"]
        if rid in seen:
            raise ValueError(f"duplicate rule_id: {rid}")
        seen.add(rid)
        if not isinstance(rule["enabled"], bool) or not isinstance(rule["carriers"], list):
            raise ValueError(f"invalid enabled/carriers for {rid}")
        if not rule["enabled"] or "h5" not in rule["carriers"]:
            continue
        if rid not in source_rules:
            raise ValueError(f"source_json.rules missing rule: {rid}")
        if rule["strength"] not in strengths:
            raise ValueError(f"unknown rule strength for {rid}: {rule['strength']}")
        restored = deepcopy(source_rules[rid])
        require_fields(restored, ("limits", "sources", "remediation", "rule_origin", "activation_reason"), f"source_json rule {rid}")
        restored.update(id=rid, title=rule["title"], expected=rule["expected"],
                        strength=strengths[rule["strength"]], enabled=True)
        if "method" in rule:
            restored["verification_method"] = rule["method"]
        if rule.get("duplicate_of"):
            restored["duplicate_of"] = rule["duplicate_of"]
        else:
            restored.pop("duplicate_of", None)
        rules.append(restored)
    if not rules:
        raise ValueError("rules_json contains no enabled H5 rules")
    profile = deepcopy(source_json)
    profile["rules"] = rules
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON object containing rules_json and source_json; '-' reads stdin")
    parser.add_argument("--output", default="-", help="profile JSON path; '-' writes stdout")
    args = parser.parse_args()
    try:
        data = json.loads(sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8"))
        require_fields(data, ("rules_json", "source_json"), "input")
        profile = build_profile(data["rules_json"], data["source_json"])
        payload = json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output == "-":
            sys.stdout.write(payload)
        else:
            Path(args.output).write_text(payload, encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
