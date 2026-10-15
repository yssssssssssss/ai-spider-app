from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.audit_spec_profile import build_profile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_spec_profile.py"


def test_official_profile_round_trip(spec_version):
    profile = build_profile(spec_version.rules_json, spec_version.source_json)
    expected = deepcopy(spec_version.source_json)
    expected["rules"] = [r for r in expected["rules"] if r["enabled"]]
    assert profile == expected
    assert next(r for r in profile["rules"] if r["id"] == "OV-023")["duplicate_of"] == "OV-005"


def test_rules_json_controls_carriers_enabled_and_effective_fields(spec_version):
    rules = deepcopy(spec_version.rules_json)
    rules[0]["carriers"] = ["app"]
    rules[1]["enabled"] = False
    rules[2].update(title="新标题", expected="新要求", strength="recommended", method="h5_screenshot")
    profile = build_profile(rules, spec_version.source_json)
    by_id = {r["id"]: r for r in profile["rules"]}
    assert "OV-001" not in by_id
    assert "OV-002" not in by_id
    assert "OV-006" not in by_id
    assert by_id["OV-003"]["title"] == "新标题"
    assert by_id["OV-003"]["expected"] == "新要求"
    assert by_id["OV-003"]["strength"] == "recommendation"
    assert by_id["OV-003"]["verification_method"] == "h5_screenshot"
    assert by_id["OV-004"]["strength"] == "conditional_mandatory"
    assert spec_version.source_json["rules"][2]["title"] != "新标题"


@pytest.mark.parametrize("mode", [None, "app", "h5", "h5_v3"])
def test_rejects_other_audit_modes(spec_version, mode):
    source = {**spec_version.source_json, "audit_mode": mode}
    with pytest.raises(ValueError, match='audit_mode.*h5_v2'):
        build_profile(spec_version.rules_json, source)


@pytest.mark.parametrize("policy", ["spacing", "text_count", "frameworks", "result_policy", "policy_source"])
def test_missing_policy_is_an_error(spec_version, policy):
    source = deepcopy(spec_version.source_json)
    del source[policy]
    with pytest.raises(ValueError, match=policy):
        build_profile(spec_version.rules_json, source)


@pytest.mark.parametrize("policy,field", [("spacing", "min"), ("text_count", "max_characters")])
def test_incomplete_policy_is_an_error(spec_version, policy, field):
    source = deepcopy(spec_version.source_json)
    target = source[policy]["acceptable_range_px"] if policy == "spacing" else source[policy]
    del target[field]
    with pytest.raises(ValueError, match=field):
        build_profile(spec_version.rules_json, source)


def test_cli_accepts_files_and_stdin_and_explains_errors(spec_version, tmp_path):
    data = {"rules_json": spec_version.rules_json, "source_json": spec_version.source_json}
    payload = json.dumps(data)
    input_file, output_file = tmp_path / "version.json", tmp_path / "profile.json"
    input_file.write_text(payload)
    completed = subprocess.run([sys.executable, str(SCRIPT), "--input", str(input_file), "--output", str(output_file)],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    expected = build_profile(data["rules_json"], data["source_json"])
    assert json.loads(output_file.read_text()) == expected
    completed = subprocess.run([sys.executable, str(SCRIPT)], input=payload, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
    data["source_json"]["audit_mode"] = "app"
    completed = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(data), capture_output=True, text=True)
    assert completed.returncode != 0
    assert 'audit_mode must be "h5_v2"' in completed.stderr
    assert "Traceback" not in completed.stderr
