"""Funding behavior and Streamlit flow tests; synthetic fixtures only."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import evaluation as e
from import_research import ResearchError, import_research, load_research

ROOT = Path(__file__).resolve().parent


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "demo_venture.json").read_text())
        self.profile["confirmed"] = True
        self.research = load_research(ROOT / "demo_research.json")
        self.book = json.loads((ROOT / "matching_rules.json").read_text())
        self.records = [{"organization_id": str(i), "observation_id": str(i), "researched_at": self.research["researched_at"], "organization": org} for i, org in enumerate(self.research["organizations"])]

    def seed(self):
        return e.evaluate(self.profile, self.records[0], self.book["organizations"]["demo-seed.example"])

    def test_baseline_contribution_and_control(self):
        result = e.evaluate_pool(self.profile, self.records, self.book)
        self.assertEqual([r["classification"] for r in result["results"]], ["strong_fit", "conditional_fit", "poor_fit"])
        self.assertEqual(result["coverage"], {"pool_size": 3, "screened": 3, "shortlisted": 2, "out_of_scope": 1})
        c = result["results"][0]["contribution"]
        self.assertEqual((c["amount_usd"], c["percentage_min"], c["remaining_min_usd"]), (150000, 20, 600000))

    def test_part_time_hard_requirement_changes_fit(self):
        self.profile["all_founders_full_time"] = False
        result = self.seed()
        self.assertEqual(result["classification"], "poor_fit")
        self.assertTrue(any("full-time" in x for x in result["concerns"]))

    def test_unknown_commitment_conditional(self):
        self.profile["all_founders_full_time"] = None
        self.assertEqual(self.seed()["classification"], "conditional_fit")

    def test_idea_only_preference_not_rejection(self):
        self.profile.update(progress="Idea only", paying_customers=0, unpaid_pilots=0, monthly_revenue_usd=0)
        self.assertEqual(self.seed()["classification"], "conditional_fit")

    def test_unknown_essential_stage_insufficient(self):
        self.profile["funding_stage"] = "unknown"
        self.assertEqual(self.seed()["classification"], "insufficient_evidence")

    def test_unknown_revenue_never_zero(self):
        self.profile["monthly_revenue_usd"] = None
        result = self.seed()
        self.assertIsNone(self.profile["monthly_revenue_usd"])
        self.assertEqual(result["classification"], "strong_fit")  # no revenue minimum in this synthetic policy

    def test_no_rules_no_recommendation(self):
        result = e.evaluate(self.profile, self.records[0])
        self.assertEqual(result["classification"], "insufficient_evidence")
        self.assertFalse(result["shortlisted"])

    def test_no_source_evidence_never_shortlisted(self):
        org = self.records[0]["organization"]
        org.update(scope_status="unclear", scope_reason="No usable evidence", sources=[], contacts=[], approach_routes=[])
        org["criteria"] = {f: {"findings": [], "unknowns": ["Not verified"], "conflicts": []} for f in e.FACTORS}
        org["check_size"].update(currency=None, basis="unknown", minimum_usd=None, maximum_usd=None, typical_usd=None, source_ids=[])
        org["funding_status"].update(status="unknown", source_ids=[])
        result = e.evaluate(self.profile, self.records[0])
        self.assertEqual(result["classification"], "insufficient_evidence")
        self.assertFalse(result["shortlisted"])

    def test_changed_research_invalidates_rules(self):
        self.records[0]["organization"]["check_size"]["typical_usd"] = 200000
        self.assertEqual(self.seed()["classification"], "insufficient_evidence")

    def test_fabricated_rule_finding_rejected(self):
        self.book["organizations"]["demo-seed.example"]["criteria"][0]["finding_index"] = 999
        self.assertEqual(self.seed()["classification"], "insufficient_evidence")

    def test_no_equity_poor_fit(self):
        self.profile["equity_willing"] = False
        self.assertEqual(self.seed()["classification"], "poor_fit")

    def test_unconfirmed_profile_rejected(self):
        self.profile["confirmed"] = False
        with self.assertRaises(ResearchError): self.seed()

    def test_free_text_constraint_needs_review(self):
        self.profile["constraints"] = "Exclude investors with a hardware focus."
        self.assertEqual(self.seed()["classification"], "conditional_fit")

    def test_target_range_arithmetic(self):
        self.profile["target_max_usd"] = 1000000
        c = self.seed()["contribution"]
        self.assertEqual((c["percentage_min"], c["percentage_max"], c["remaining_max_usd"]), (15, 20, 850000))

    def test_unreviewed_portfolio_conditional(self):
        org = self.records[0]["organization"]
        org["portfolio_conflicts"].update(review_status="not_reviewed")
        self.book["organizations"]["demo-seed.example"]["profile_sha256"] = e.profile_hash(org)
        self.assertEqual(self.seed()["classification"], "conditional_fit")

    def test_conflicting_evidence_not_strong(self):
        org = self.records[0]["organization"]
        org["criteria"]["geography"]["conflicts"].append("Synthetic conflicting geography policy.")
        self.book["organizations"]["demo-seed.example"]["profile_sha256"] = e.profile_hash(org)
        self.assertEqual(self.seed()["classification"], "conditional_fit")

    def test_bad_profile_values_rejected(self):
        for key, value in (("monthly_revenue_usd", float("nan")), ("paying_customers", -1), ("paying_customers", 2.5), ("all_founders_full_time", "yes"), ("target_max_usd", 100)):
            with self.subTest(key=key, value=value):
                p = copy.deepcopy(self.profile)
                p[key] = value
                with self.assertRaises(ResearchError): e.validate_profile(p)

    def test_blank_numeric_unknown_and_zero_distinct(self):
        self.assertIsNone(e.number_answer("", "Revenue"))
        self.assertEqual(e.number_answer("0", "Revenue"), 0)
        self.assertEqual(e.number_answer("$750,000", "Target"), 750000)
        with self.assertRaises(ResearchError): e.number_answer("3.5", "Customers", whole=True)

    def test_empty_pool_no_padding(self):
        result = e.evaluate_pool(self.profile, [], self.book)
        self.assertEqual(result["coverage"]["screened"], 0)
        self.assertEqual(result["results"], [])

    def test_email_unknowns_not_invented(self):
        self.profile["target_min_usd"] = None
        text = e.email_draft(self.profile, self.seed())
        self.assertIn("[funding amount]", text)
        self.assertIn("[recipient name]", text)
        self.assertNotIn("30 paying customers", text)

    def test_latest_observation_refresh_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "demo.db"
            import_research(self.research, db, allow_demo=True)
            refreshed = copy.deepcopy(self.research)
            refreshed["organizations"] = [refreshed["organizations"][0]]
            refreshed["organizations"][0]["check_size"]["typical_usd"] = 999999
            import_research(refreshed, db, allow_demo=True)
            rows = e.latest_research(db)
            row = next(r for r in rows if r["organization"]["canonical_domain"] == "demo-seed.example")
            self.assertEqual(row["organization"]["check_size"]["typical_usd"], 999999)
            result = e.evaluate(self.profile, row, self.book["organizations"]["demo-seed.example"])
            self.assertEqual(result["classification"], "insufficient_evidence")


class StreamlitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"VENTUREFIT_DEMO_DB": str(Path(self.temp.name) / "demo.db")})
        env.start()
        self.addCleanup(env.stop)
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()

    def check_clean(self):
        self.assertEqual(len(self.app.exception), 0, str(self.app.exception))

    def demo_summary(self):
        self.app.button(key="load_demo").click().run()
        self.check_clean()
        self.app.button(key="review").click().run()
        self.check_clean()

    def evaluate(self):
        self.app.checkbox(key="confirm_checked").check()
        self.app.button(key="evaluate").click().run()
        self.check_clean()

    def test_blank_start_no_automatic_research(self):
        self.check_clean()
        self.assertFalse((Path(self.temp.name) / "demo.db").exists())
        self.assertEqual(self.app.text_input(key="f_name").value, "")

    def test_full_demo_flow(self):
        self.demo_summary()
        self.assertEqual(self.app.session_state["page"], "Confirm summary")
        self.evaluate()
        self.assertEqual(self.app.session_state["page"], "Funding fit results")
        self.assertEqual([m.value for m in self.app.metric], ["3", "3", "2"])
        self.assertEqual([r["classification"] for r in self.app.session_state["assessment"]["results"]], ["strong_fit", "conditional_fit", "poor_fit"])

    def test_confirmation_required(self):
        self.demo_summary()
        self.app.button(key="evaluate").click().run()
        self.check_clean()
        self.assertIn("Confirm the summary", self.app.error[0].value)
        self.assertNotIn("assessment", self.app.session_state)

    def test_edit_changes_fit_and_clears_old_result(self):
        self.demo_summary()
        self.evaluate()
        self.app.button(key="edit_results").click().run()
        self.check_clean()
        self.assertNotIn("assessment", self.app.session_state)
        self.app.selectbox(key="f_all_founders_full_time").select("No")
        self.app.button(key="review").click().run()
        self.evaluate()
        seed = next(r for r in self.app.session_state["assessment"]["results"] if r["name"] == "Demo Seed Partners")
        self.assertEqual(seed["classification"], "poor_fit")

    def test_bad_number_blocks_confirmation(self):
        self.app.button(key="load_demo").click().run()
        self.app.text_input(key="f_paying_customers").set_value("not-a-number")
        self.app.button(key="review").click().run()
        self.check_clean()
        self.assertEqual(self.app.session_state["page"], "Venture profile")
        self.assertIn("enter digits", self.app.error[0].value)

    def test_loading_demo_twice_keeps_three_firms(self):
        self.app.button(key="load_demo").click().run()
        self.app.button(key="load_demo").click().run()
        self.check_clean()
        rows = e.latest_research(Path(self.temp.name) / "demo.db")
        self.assertEqual(len(rows), 3)

    def test_non_us_profile_not_evaluated(self):
        self.app.button(key="load_demo").click().run()
        self.app.selectbox(key="f_operating_country").select("Other")
        self.app.button(key="review").click().run()
        self.evaluate()
        self.assertIn("United States", self.app.error[0].value)
        self.assertNotIn("assessment", self.app.session_state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
