import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "seed_audit_projects_demo", Path(__file__).resolve().parents[2] / "scripts/seed_audit_projects_demo.py",
)
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)


class DemoDatabaseGuardTests(unittest.TestCase):
    def test_accepts_only_test_or_demo_database_names(self):
        for url in ("postgresql://localhost/audit_test", "postgresql+psycopg2://localhost/DEMO_audit",
                    "postgresql://localhost/audit_%74est"):
            with self.subTest(url=url):
                self.assertTrue(seed_demo.is_demo_database_url(url))
        for url in ("postgresql://demo:test@localhost/production", "postgresql://test-host/production",
                    "postgresql://localhost/production?application_name=test", "postgresql://localhost/",
                    "sqlite:///test.db", "not a URL", "postgresql://[invalid/test"):
            with self.subTest(url=url):
                self.assertFalse(seed_demo.is_demo_database_url(url))
