"""Integration checks for saved history, committed drafts, outreach, and exports."""
import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app
from evaluation import evaluate_pool, latest_research
from import_research import import_research, load_research

ROOT = Path(__file__).parent


class SavedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'demo.db'
        import_research(load_research(ROOT / 'demo_research.json'), self.db, allow_demo=True)
        self.profile = json.loads((ROOT / 'demo_venture.json').read_text())
        self.profile['confirmed'] = True
        self.book = json.loads((ROOT / 'matching_rules.json').read_text())
        self.assessment = evaluate_pool(self.profile, latest_research(self.db), self.book)
        self.assessment['rulebook'] = copy.deepcopy(self.book)
        self.state = {'assessment': self.assessment}
        for p in (patch.object(app, 'DB', self.db), patch.object(app, 'st', SimpleNamespace(session_state=self.state))):
            p.start()
            self.addCleanup(p.stop)
        self.first = app.save_current_assessment()

    def count(self, table):
        with sqlite3.connect(self.db) as conn:
            return conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def seed(self):
        return next(r for r in self.state['assessment']['results'] if r['name'] == 'Demo Seed Partners')

    def test_identical_save_does_not_add_version(self):
        self.assertEqual(app.save_current_assessment(), self.first)
        self.assertEqual(self.count('assessments'), 1)

    def test_changed_input_appends_and_original_reopens_without_recalculation(self):
        p = copy.deepcopy(self.profile)
        p['all_founders_full_time'] = False
        changed = evaluate_pool(p, latest_research(self.db), self.book)
        changed['rulebook'] = copy.deepcopy(self.book)
        self.state['assessment'] = changed
        second = app.save_current_assessment()
        self.assertNotEqual(second, self.first)
        self.assertEqual(self.seed()['classification'], 'poor_fit')
        self.state.clear()  # Simulate a new browser session, preserving only SQLite.
        with patch.object(app, 'evaluate_pool', side_effect=AssertionError('Must not recompute on reopen')):
            app.reopen_assessment(self.first)
        self.assertEqual(self.seed()['classification'], 'strong_fit')
        self.assertTrue(self.state['assessment']['venture']['all_founders_full_time'])
        self.assertEqual(self.count('assessments'), 2)

    def test_committed_draft_survives_reopen(self):
        key = next(k for k in self.state['drafts'] if not k.endswith('_subject'))
        self.state[key] = 'Founder-edited demonstration introduction.'
        app.remember_email(key)
        version = self.state['saved_assessment_id']
        self.assertNotEqual(version, self.first)
        self.state.clear()
        app.reopen_assessment(version)
        self.assertEqual(self.state['drafts'][key], 'Founder-edited demonstration introduction.')

    def test_response_history_does_not_change_fit_and_follows_latest_recorded_event(self):
        venture = self.state['venture_id']
        org = self.seed()['organization_id']
        original = copy.deepcopy(self.state['assessment'])
        app.record_outreach(venture, org, self.first, 'awaiting_response', '2026-10-05', 'Sent demo introduction')
        app.record_outreach(venture, org, self.first, 'negative_response', '2026-10-04', 'Backdated response')
        self.assertEqual(self.count('outreach_events'), 2)
        self.state.clear()
        app.reopen_assessment(self.first)
        self.assertEqual(self.state['assessment'], original)
        events = app.outreach_history(venture, org)
        self.assertEqual(events[0]['status'], 'negative_response')
        self.assertEqual(events[1]['status'], 'awaiting_response')

    def test_invalid_outreach_cannot_add_event(self):
        with self.assertRaises(ValueError):
            app.record_outreach('other-venture', self.seed()['organization_id'], self.first, 'positive_response')
        self.assertEqual(self.count('outreach_events'), 0)

    def test_exports_keep_screened_shortlisted_rules_and_latest_response(self):
        seed = self.seed()
        app.record_outreach(self.state['venture_id'], seed['organization_id'], self.first, 'negative_response', note='Demo only')
        context = app.export_context(self.state['assessment'])
        rows = list(csv.DictReader(io.StringIO(app.shortlist_csv(context).decode('utf-8-sig'))))
        self.assertEqual(len(rows), 2)
        self.assertNotIn('Demo Growth Capital', [r['Organization'] for r in rows])
        self.assertEqual(next(r for r in rows if r['Organization'] == seed['name'])['Outreach status'], 'Negative response')
        pdf = app.funding_brief_pdf(context)
        self.assertTrue(pdf.startswith(b'%PDF'))
        try:
            from pypdf import PdfReader
        except ImportError:
            self.fail('pypdf is needed for this PDF-content verification check')
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        for name in ('Demo Seed Partners', 'Demo Valley Angels', 'Demo Growth Capital'):
            self.assertIn(name, text)
        self.assertIn('Negative response', text)


if __name__ == '__main__':
    unittest.main()
