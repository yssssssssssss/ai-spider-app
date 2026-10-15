"""Use the real spec importer/parser without permitting database connections."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
H5_PROFILE = ROOT / "docs/specifications/official-venue-review/h5-v5.json"


@pytest.fixture
def audit_workspace(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("script tests must not connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.syspath_prepend(str(ROOT / "backend"))
    return importlib.import_module("app.services.audit_workspace")


@pytest.fixture
def spec_version(audit_workspace):
    # Exercise the actual v2 normalization, with all persistence calls mocked.
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    db.query.return_value.filter_by.return_value.scalar.return_value = 0
    version = audit_workspace.import_spec_version(db, SimpleNamespace(id=uuid4()), H5_PROFILE.read_bytes(), "h5")
    db.add.assert_called_once_with(version)
    return version
