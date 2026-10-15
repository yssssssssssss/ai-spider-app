import json
from contextlib import redirect_stdout
from io import StringIO

import pytest

from scripts.replay_capture_gate import replay


@pytest.mark.parametrize("status,code", [("page_error", 0), ("partial_inspection", 1)])
def test_replay_exits_nonzero_only_when_a_valid_venue_is_blocked(tmp_path, status, code):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"results": [
        {"venue": {"venue_id": "RA1"}, "status": status, "capture": {"page_title": "挑好物逛京东"}},
        {"venue": {"venue_id": "RA2"}, "status": "partial_inspection", "capture": {}},
    ]}))
    stream = StringIO()
    with redirect_stdout(stream):
        assert replay(path) == code
    output = stream.getvalue()
    assert '"venue_lost": 1' in output
    assert ("FALSE POSITIVE: RA1" in output) is bool(code)
