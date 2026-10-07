# New Venture Fit Analysis

Local Python/Streamlit demonstration for U.S. AI venture funding fit. It compares a confirmed founder profile with reviewed criteria and explains alignment, mismatches, conditions, and unknowns. Three fictional investors and reserved `.example` sources are clearly labeled. No live search, automatic outreach, accounts, funding predictions, or ARenvision integration.

## Setup on Windows

Use Python 3.12; prior verification used 3.12.14. Keep runtime files directly in `C:\contest`: app.py, evaluation.py, import_research.py, schema.sql, research.schema.json, matching_rules.json, demo_venture.json, demo_research.json, and requirements.txt.

```powershell
cd C:\contest
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the address printed by Streamlit. ReportLab is included for PDF generation. Planning documents may be kept at the repository root for a flat browser upload, or under devpost/ as in the development checkout. Their filenames stay scope.md, prd.md, spec.md, and checklist.md. Documentation placement does not affect the app.

## Try the core journey

1. Load synthetic example, then Review venture summary.
2. Check confirmation and Evaluate funding fit.
3. Inspect Demo Seed Partners (Strong), Demo Valley Angels (Conditional), and Demo Growth Capital (Poor/outside scope).
4. Edit the profile: change Are all founders full-time? to No. Review, confirm, and evaluate again. Demo Seed Partners becomes Poor because its synthetic hard requirement fails.
5. Use Saved assessments to select the earlier version and correct venture copy, then Reopen assessment. The original results restore without recomputing.

Unknown figures stay unknown. Future milestones are not current traction. Fit means criteria alignment, not funding probability or commitment. Fictional organizations are not contact prospects.

## Preserve work and use supporting features

Keep your current demo.db beside app.py when updating code. Stop Streamlit before copying it for backup. Never replace it with an older uploaded database.

- Evaluation saves a complete assessment; changed content appends a version, while identical latest content may reuse its version.
- Restore through Saved assessments > select version/venture copy > Reopen assessment.
- Load synthetic example and Start a blank profile begin separate venture copies on evaluation; they are not restore actions.
- Unevaluated answers are session-only.
- Email edits commit when you leave the field. Save assessment explicitly saves/retries committed drafts. Review and send externally; the app sends nothing.
- Outreach requires Save outreach update. Save assessment does not submit an outreach form.
- Response history follows the same venture and organization across assessment versions and never changes fit.
- Funding fit results > Download funding brief & shortlist > Prepare downloads provides PDF (all screened) and CSV (shortlisted only). Both include the latest outreach captured at preparation time alongside the selected assessment's historical fit. Email text download is also available.

## Verification

```powershell
python -m unittest test_app test_import_research
```

On October 6, 2026, 70 original checks passed on current saved app version 8. Six additional integration checks in test_workflow.py passed: identical-save reuse, changed-input history, committed draft reopening, response-history independence, cross-venture rejection, and PDF/CSV contents.

```powershell
python -m pip install pypdf
python -m unittest test_workflow
```

pypdf is only needed for PDF-content verification, not running the app. Tests use temporary databases. Harmless ScriptRunContext warnings may appear. The learner accepted the final review and closed Stage 5 on October 6, 2026. On October 7, the recorded browser workflow completed on Windows and showed reassessment and reopening the original saved assessment. The learner approved the narrated video, demo_final.mp4, at approximately 2 minutes 42 seconds.

## Research import

```powershell
python import_research.py demo_research.json --demo --validate-only
python import_research.py demo_research.json --demo
```

Validation writes no database. A fresh import adds 3 organizations; exact repeats skip 3 observations. Changed research appends history and preserves stable identities. The demo button safely imports fixtures automatically.

researchprompt.txt defines separately researched real payloads. Real imports default to venturefit.db; demo and real scopes cannot mix. Current interface matching is demonstration-only. Real importer support does not complete real matching. The 50-investor pool and continuous updates are deferred.

Reviewed structured rules bind to exact research hashes and cited findings. Import validation checks shape and references, not source truth. Human review is required before using real evidence. No API credentials are required.

## Planning and learning records

Scope, PRD, and spec were approved October 6, 2026 after the initial build. The checklist records completed build verification, final review, and the learning wrap-up. app-map.html is an offline source reference; the development checkout keeps it under devpost/.

The learner profile, credentials, and working databases are excluded from commits. No public push, hosting, investor contact, or contest submission is part of these checks. The narrated demo video is complete and approved. Public repository publication, a reviewer-accessible video link, and the Devpost submission remain shipping tasks. Planning approval dates are preserved as recorded.
