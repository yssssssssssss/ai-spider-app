import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_audit_evidence(tmp_path_factory, monkeypatch):
    # Ingest paths (e.g. H5 jobs) must never write into the real data/audit-evidence.
    monkeypatch.setattr(settings, "AUDIT_EVIDENCE_ROOT", str(tmp_path_factory.mktemp("audit-evidence")))
