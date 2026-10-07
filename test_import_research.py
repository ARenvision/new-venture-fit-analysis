"""Behavior tests use only synthetic data and temporary databases."""
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import import_research as importer

ROOT = Path(__file__).resolve().parent
NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)


@contextmanager
def database_connection(path):
    """Commit/rollback the transaction AND close the handle before cleanup.

    sqlite3.Connection's own context manager does not close the connection.
    Keeping references alive must not prevent Windows deleting the test file.
    """
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.db"
        self.data = importer.load_research(ROOT / "demo_research.json")

    def run_import(self, data=None, db=None):
        return importer.import_research(self.data if data is None else data, db or self.db, allow_demo=True, now=NOW)

    def counts(self):
        with database_connection(self.db) as conn:
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("organizations", "investor_observations"))

    def rejected(self, change):
        change(self.data)
        with self.assertRaises(importer.ResearchError):
            self.run_import()
        self.assertFalse(self.db.exists())

    def test_import_survives_reopen(self):
        result = self.run_import()
        self.assertEqual(result["added"], 3)
        self.assertEqual(self.counts(), (3, 3))
        with database_connection(self.db) as conn:
            payloads = [json.loads(r[0]) for r in conn.execute("SELECT payload_json FROM investor_observations")]
            self.assertTrue(all(p["data_scope"] == "synthetic_demo" for p in payloads))
            self.assertEqual(sorted(p["organization"]["name"] for p in payloads), sorted(o["name"] for o in self.data["organizations"]))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        # Verify closure while a Python reference still exists, without relying
        # on garbage collection or Linux permitting unlink of open files.
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_repeat_import_is_noop(self):
        first = self.run_import()
        second = self.run_import()
        self.assertEqual((second["added"], second["duplicates_skipped"]), (0, 3))
        self.assertEqual([r["observation_id"] for r in first["results"]], [r["observation_id"] for r in second["results"]])
        self.assertEqual(self.counts(), (3, 3))

    def test_equivalent_timezone_is_duplicate(self):
        self.run_import()
        self.data["researched_at"] = "2026-10-04T14:00:00-04:00"
        self.assertEqual(self.run_import()["duplicates_skipped"], 3)

    def test_refresh_preserves_original_and_identity(self):
        first = self.run_import()
        with database_connection(self.db) as conn:
            original = conn.execute("SELECT payload_json FROM investor_observations WHERE observation_id=?", (first["results"][0]["observation_id"],)).fetchone()[0]
        updated = copy.deepcopy(self.data)
        updated["organizations"] = [updated["organizations"][0]]
        updated["researched_at"] = "2026-10-05T12:00:00Z"
        updated["organizations"][0]["check_size"]["typical_usd"] = None
        updated["organizations"][0]["check_size"]["note"] = "New synthetic snapshot has unknown check size."
        second = self.run_import(updated)
        self.assertEqual(first["results"][0]["organization_id"], second["results"][0]["organization_id"])
        self.assertEqual(self.counts(), (3, 4))
        with database_connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT payload_json FROM investor_observations WHERE observation_id=?", (first["results"][0]["observation_id"],)).fetchone()[0], original)

    def test_changed_content_same_date_appends_correction(self):
        self.run_import()
        self.data["organizations"][0]["open_questions"].append("Synthetic correction.")
        self.assertEqual(self.run_import()["added"], 1)
        self.assertEqual(self.counts(), (3, 4))

    def test_missing_source_rolls_back_entire_batch(self):
        self.rejected(lambda d: d["organizations"][2]["check_size"].update(source_ids=["S99"]))

    def test_identity_conflict_rolls_back_earlier_new_org(self):
        self.run_import()
        before = self.counts()
        new = copy.deepcopy(self.data["organizations"][0])
        new.update(name="Demo Newly Added", canonical_domain="new-demo.example")
        conflict = copy.deepcopy(self.data["organizations"][1])
        conflict["canonical_domain"] = "conflicting.example"
        batch = {**self.data, "organizations": [new, conflict]}
        with self.assertRaisesRegex(importer.ResearchError, "conflicts"):
            self.run_import(batch)
        self.assertEqual(self.counts(), before)

    def test_shared_domain_different_name_requires_review(self):
        self.run_import()
        self.data["organizations"] = [self.data["organizations"][0]]
        self.data["organizations"][0]["name"] = "Demo Unrelated Fund"
        with self.assertRaises(importer.ResearchError):
            self.run_import()
        self.assertEqual(self.counts(), (3, 3))

    def test_alias_can_confirm_same_identity(self):
        first = self.run_import()
        self.data["organizations"] = [self.data["organizations"][0]]
        self.data["organizations"][0].update(name="Demo Seed Renamed", aliases=["Demo Seed Partners"])
        second = self.run_import()
        self.assertEqual(first["results"][0]["organization_id"], second["results"][0]["organization_id"])

    def test_unknown_domain_does_not_erase_identity(self):
        self.run_import()
        self.data["organizations"] = [self.data["organizations"][0]]
        self.data["organizations"][0]["canonical_domain"] = None
        self.run_import()
        with database_connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT canonical_domain FROM organizations WHERE canonical_name='Demo Seed Partners'").fetchone()[0], "demo-seed.example")

    def test_type_change_requires_review(self):
        self.run_import()
        self.data["organizations"][0]["organization_type"] = "angel_group"
        with self.assertRaises(importer.ResearchError):
            self.run_import()
        self.assertEqual(self.counts(), (3, 3))

    def test_demo_requires_explicit_flag(self):
        with self.assertRaises(importer.ResearchError):
            importer.import_research(self.data, self.db, now=NOW)
        self.assertFalse(self.db.exists())

    def test_unrelated_database_is_not_modified(self):
        with database_connection(self.db) as conn:
            conn.execute("CREATE TABLE unrelated(value TEXT)")
            conn.execute("INSERT INTO unrelated VALUES ('keep')")
        with self.assertRaisesRegex(importer.ResearchError, "standalone"):
            self.run_import()
        with database_connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("unrelated",)])
            self.assertEqual(conn.execute("SELECT value FROM unrelated").fetchone()[0], "keep")

    def test_demo_real_mixing_rejected(self):
        self.run_import()
        data = {**self.data, "data_scope": "real_investor_research"}
        with self.assertRaisesRegex(importer.ResearchError, "mix"):
            self.run_import(data)
        self.assertEqual(self.counts(), (3, 3))

    def test_future_date(self):
        self.rejected(lambda d: d.update(researched_at="2099-10-05T12:00:00Z"))

    def test_timestamp_timezone_required(self):
        self.rejected(lambda d: d.update(researched_at="2026-10-04T18:00:00"))

    def test_source_date_after_research(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(checked_on="2026-10-05"))

    def test_invalid_calendar_date(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(checked_on="2026-02-30"))

    def test_publication_after_access(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(published_on="2026-10-05"))

    def test_check_bounds(self):
        self.rejected(lambda d: d["organizations"][0]["check_size"].update(minimum_usd=200000, maximum_usd=100000))

    def test_typical_outside_range(self):
        self.rejected(lambda d: d["organizations"][0]["check_size"].update(maximum_usd=100000))

    def test_missing_numeric_citation(self):
        self.rejected(lambda d: d["organizations"][0]["check_size"].update(source_ids=[]))

    def test_inferred_hard_requirement(self):
        self.rejected(lambda d: d["organizations"][0]["criteria"]["stage"]["findings"][0].update(evidence_status="inferred", rule_type="hard_requirement"))

    def test_duplicate_source_id(self):
        self.rejected(lambda d: d["organizations"][0]["sources"].append(copy.deepcopy(d["organizations"][0]["sources"][0])))

    def test_duplicate_route_id(self):
        self.rejected(lambda d: d["organizations"][0]["approach_routes"].append(copy.deepcopy(d["organizations"][0]["approach_routes"][0])))

    def test_contact_route_reference(self):
        self.rejected(lambda d: d["organizations"][0]["contacts"].append({"name":"Demo Analyst", "position":"Partner", "relevance":"Synthetic", "relevance_status":"verified", "decision_authority":"not_verified", "source_ids":["S1"], "route_ids":["R99"]}))

    def test_route_requires_official_provenance(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(source_type="independent_secondary"))

    def test_invalid_domain(self):
        self.rejected(lambda d: d["organizations"][0].update(canonical_domain="-bad.example"))

    def test_credential_url(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(url="https://user:password@demo.example/"))

    def test_no_linkedin(self):
        self.rejected(lambda d: d["organizations"][0]["sources"][0].update(url="https://www.linkedin.com/company/demo"))

    def test_blank_name(self):
        self.rejected(lambda d: d["organizations"][0].update(name="  "))

    def test_duplicate_batch_names(self):
        self.rejected(lambda d: d["organizations"][1].update(name=d["organizations"][0]["name"]))

    def test_extra_key(self):
        self.rejected(lambda d: d["organizations"][0].update(funding_probability=0.9))

    def test_growth_control_cannot_be_in_scope(self):
        self.rejected(lambda d: d["organizations"][2].update(scope_status="in_scope"))

    def test_nonfinite_api_number(self):
        self.rejected(lambda d: d["organizations"][0]["check_size"].update(typical_usd=float("nan")))

    def test_json_loader_rejects_duplicate_keys_and_nonfinite(self):
        for text in ('{"name":"first","name":"second"}', '{"value":NaN}', '{"value":Infinity}'):
            with self.subTest(text=text):
                path = Path(self.temp.name) / "invalid.json"
                path.write_text(text)
                with self.assertRaises(importer.ResearchError):
                    importer.load_research(path)

    def test_oversize_file(self):
        path = Path(self.temp.name) / "large.json"
        path.write_bytes(b" " * (importer.MAX_BYTES + 1))
        with self.assertRaises(importer.ResearchError):
            importer.load_research(path)

    def test_immutable_observations(self):
        self.run_import()
        with database_connection(self.db) as conn:
            for sql in ("UPDATE investor_observations SET researched_at='2099-01-01'", "DELETE FROM investor_observations"):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)
        self.assertEqual(self.counts(), (3, 3))
        # Error exits must close handles as well as roll back changes.
        with self.assertRaises(RuntimeError):
            with database_connection(self.db) as conn:
                raise RuntimeError("Exercise connection cleanup")
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_outreach_history_untouched_by_import(self):
        first = self.run_import()
        with database_connection(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT INTO ventures VALUES ('v1','Synthetic Founder',1,'2026-10-04T00:00:00Z')")
            for i, status in enumerate(("awaiting_response", "no_response")):
                conn.execute("INSERT INTO outreach_events(event_id,venture_id,organization_id,status,recorded_at) VALUES (?, 'v1', ?, ?, '2026-10-04T00:00:00Z')", (f"e{i}", first["results"][0]["organization_id"], status))
        self.run_import()
        with database_connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM outreach_events").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT status FROM latest_outreach_status").fetchone()[0], "no_response")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM assessment_results").fetchone()[0], 0)

    def test_cli_validate_only_creates_no_database(self):
        result = subprocess.run([sys.executable, str(ROOT / "import_research.py"), str(ROOT / "demo_research.json"), "--demo", "--validate-only", "--db", str(self.db)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.db.exists())
        self.assertEqual(json.loads(result.stdout)["organizations"], 3)

    def test_cli_import_and_repeat(self):
        args = [sys.executable, str(ROOT / "import_research.py"), str(ROOT / "demo_research.json"), "--demo", "--db", str(self.db)]
        for added in (3, 0):
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["added"], added)
        self.assertEqual(self.counts(), (3, 3))

    def test_cli_failure_returns_nonzero_without_db(self):
        path = Path(self.temp.name) / "invalid.json"
        path.write_text('{"bad":true}')
        result = subprocess.run([sys.executable, str(ROOT / "import_research.py"), str(path), "--db", str(self.db)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No batch records", result.stderr)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
