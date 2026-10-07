---
doc: spec
status: approved
---

# New Venture Fit Analysis — Technical Specification

## How This Works, In Plain Language
The founder supplies venture answers and confirms the summary. The program compares specific confirmed fields with reviewed investor criteria and explains the resulting fit label. It saves a copy of the confirmed answers, results, evidence, rules, and committed email drafts. Reopening reads that saved copy rather than evaluating again. Changed answers can produce a new assessment while the previous assessment remains available.

This retains the existing local Python, Streamlit, and SQLite approach; it does not introduce accounts, hosting, automatic outreach, or ARenvision integration.
Implements prd.md > The Core Journey and approved scope.md > The POC Boundary.

## The Core Journey Through the System
1. app.py collects form answers and displays the summary.
2. Confirmation marks the profile ready; validation checks required structure and values.
3. evaluation.py reads the latest demonstration research observations and the reviewed matching_rules.json rulebook.
4. Each investor criterion compares a particular founder value with its permitted category, minimum threshold, or required yes/no value. The engine records alignment, mismatch, or unknown with evidence references.
5. The classification logic returns a label and explanation; app.py displays the results.
6. save_current_assessment writes the complete snapshot to SQLite in one transaction. Changed content appends a version; an identical save can reuse the latest version for that venture.
7. reopen_assessment reads the stored snapshot and restores answers, results, rules, and drafts without recomputing fit. Outreach is displayed from the latest separately saved events.
Implements prd.md > Venture Intake and Confirmation, Explainable Funding Fit, and Saved Assessments.

## Stack
- Python: existing project verification used Python 3.12.14; environment compatibility remains part of final verification. Documentation: https://docs.python.org/3/.
- Streamlit: existing requirements.txt pins 1.64.0. Provides the local form and results interface. Documentation: https://docs.streamlit.io/.
- SQLite through Python sqlite3: local persistence, transactions, foreign keys, and saved history. Documentation: https://docs.python.org/3/library/sqlite3.html and https://sqlite.org/foreignkeys.html.
- jsonschema: existing requirements.txt pins 4.26.0; validates research shape. Documentation: https://python-jsonschema.readthedocs.io/.
- ReportLab: existing PDF function imports it; requirements.txt includes reportlab==4.4.9 for PDF generation. Documentation: https://docs.reportlab.com/.
- Python csv: existing shortlist export; no spreadsheet service or extra library needed.
Established stack is retained. This review did not perform a fresh package-version or maintenance check.

## Where It Runs and How Someone Tries It
Windows working directory: C:\contest. Keep runtime files beside app.py and preserve the user's current demo.db.
Launch: python -m streamlit run app.py.
Use the browser address shown by Streamlit. A local recording suffices for the contest demonstration. The narrated working video is complete and approved at approximately 2 minutes 42 seconds. Public source repository publication and a reviewer-accessible video link remain submission tasks; hosting is deferred.
Load the labeled synthetic example, confirm, evaluate, inspect reasons, change a relevant input, reconfirm, and evaluate again. Use Saved assessments to reopen the original version. Do not replace the user's current database with an older uploaded copy.

## Look and Feel
Retain the approved dark presentation, separate slate/card sections, compact summaries, readable organization cards, and plain-language labels. No redesign or new comparison screen.
Implements prd.md > Look and Feel and Screens and Layout.

## Components

### Intake and Confirmation
app.py: collect_profile, form, show_profile, confirm, and clear_result collect and confirm answers and clear stale results. evaluation.py: validate_profile and number_answer validate structured inputs. Unknown numbers and booleans remain unknown; future goals are not achieved traction.
Implements prd.md > Venture Intake and Confirmation.

### Research Contract and Importer
researchprompt.txt and research.schema.json define research payloads and provenance. import_research.py validates structural and semantic constraints before atomic import. Stable application-assigned identities and import hashes prevent repeated imports from duplicating observations. New observations append history. Ambiguous identity stops the import rather than guessing a merge.
Validation does not prove source truth. Demo and real research scopes cannot be mixed in one database. Demo import requires --demo; real importer defaults to venturefit.db. The current matching interface is demonstration-only; importer real-mode support does not constitute a real matching workflow.
Implements prd.md > Research and Evidence.

### Evaluation and Business Cause and Effect
evaluation.py: _reviewed_rules checks rulebook review status, organization domain, exact research-profile hash, and referenced findings. _matches compares a founder value with a reviewed rule; a missing value returns unknown.
evaluate processes stage, sector, geography, amount, traction, and restrictions, plus funding-route/equity preferences, current investing status, portfolio restrictions, and unresolved constraints. evaluate_pool orders the results and records coverage.
Current classification precedence:
- Known hard mismatch: Poor Fit.
- Otherwise, unknown funding stage or missing supported coverage of stage, sector, or geography: Insufficient Evidence.
- Otherwise, remaining uncertainty or conditions: Conditional Fit.
- Otherwise: Strong Fit.
The engine does not calculate funding probability. A rulebook hash match verifies correspondence, not the semantic truth of a criterion; criteria require human evidence review.
Learning example: where a reviewed investor has a full-time founder requirement, changing the relevant commitment answer can cause a hard mismatch. Inspect the actual demo rule and result during the walkthrough before claiming a particular observed label transition.
Implements prd.md > Explainable Funding Fit and Cause-and-Effect Demonstration.

### Saving and Software Cause and Effect
app.py: save_current_assessment serializes the complete assessment and committed drafts into summary_json, inserts the confirmed profile and result rows, and commits together. A failure rolls back the transaction. Identical latest content for that venture reuses its saved version; changed content appends a version.
reopen_assessment reads summary_json and restores it into the interface. It does not run the current rulebook again. Therefore changing inputs or importing new research does not rewrite the original saved fit result.
Email edits must commit by leaving their field; remember_email saves committed changes. Save assessment offers an explicit save/retry. Unevaluated answers remain session-only.
Implements prd.md > Saved Assessments and Contacts and Email Drafts.

### Outreach
app.py: record_outreach appends an event only on explicit Save outreach update. outreach_history and latest_outreach_status expose recorded events and latest status. Saving an assessment does not submit an outreach form; outreach never changes fit classification.
Implements prd.md > Manual Outreach History.

### Exports
Existing export_context, shortlist_csv, funding_brief_pdf, and export_panel are in app.py; a separate reports.py is not required. PDF includes all screened organizations; CSV includes shortlisted organizations. Both are prepared from the assessment plus one export-time snapshot of the latest outreach. Thus saved fit remains historical while outreach in a new export can be current. Email text download remains available.
Implements prd.md > Downloads.

## Data Model
schema.sql defines seven tables: organizations, investor_observations, ventures, venture_profiles, assessments, assessment_results, outreach_events. Organization and venture identities persist; research observations, confirmed profiles, assessments, results, and outreach history are appended. Foreign keys are enabled on connections. assessments.summary_json preserves full results, reviewed rules, and drafts; results reference exact investor observations. latest_outreach_status selects the latest recorded event per venture and organization.
Demo storage is demo.db beside app.py. VENTUREFIT_DEMO_DB permits isolated test storage. Do not use a user's working database for tests. No general migration framework is implemented.

## File Structure
The Windows working folder stays flat. A browser upload may keep the planning documents at the repository root. The development checkout uses devpost/; either placement keeps the required document filenames and does not change runtime behavior. No Windows folders need to be moved.

| File | Role |
| --- | --- |
| app.py | Interface, saving/reopening, outreach, drafts, and exports |
| evaluation.py | Validation and explainable fit rules |
| import_research.py | Validated, atomic research ingestion |
| schema.sql | SQLite definitions and history safeguards |
| researchprompt.txt, research.schema.json | Research instructions and data contract |
| matching_rules.json | Reviewed rules tied to research observations |
| demo_venture.json, demo_research.json | Clearly labeled synthetic fixtures |
| demo.db | User's persistent demonstration work; preserve |
| test_app.py, test_import_research.py, test_workflow.py | Verification |
| requirements.txt, README.md | Reconciled dependencies and startup instructions |
| learner-profile.md | Personal learning context; exclude from public commits |
| scope.md, prd.md, spec.md | Canonical planning documents |
| checklist.md, app-map.html | Completed build tracking and learning reference |

## External Services and Dependencies
The current app needs no live research API, paid AI service, accounts, or hosting. Research and criteria are supplied through reviewed local fixtures. No external email sending. Any small real-investor set remains undecided and requires scope-specific implementation and evidence review before use.

## Important Failure Modes
- Invalid/unconfirmed profile: explain the error and block evaluation.
- Missing, mismatched, or unsupported research/rules: show uncertainty; never invent fit.
- Save failure: rollback, retain prior records, and show retry guidance.
- ReportLab absent: explain PDF dependency; CSV remains independently available.

## What Was Simplified and Why
Use the existing labeled synthetic set to demonstrate the kernel instead of building a 50-investor research operation. Keep local storage instead of adding accounts or hosting. Use existing results and reassessment to show cause and effect instead of adding a comparison screen. Preserve completed supporting features without expanding them.

## Verification Plan
Use the existing relevant tests and isolated databases. Verify labeled classifications, meaningful-input effects, unknown handling, confirmation/stale-result behavior, identical-save reuse, changed-version preservation, restart/reopen, committed drafts, explicit outreach persistence, and export inclusion/counts. The final learner review must include actual app use and feedback.
October 6 verification passed 76 checks: 70 original and six focused persistence/outreach/draft/export checks. Stage 5 final review and learning recap were accepted October 6. The October 7 browser recording showed the full-time-founder answer change, changed fit result, and reopening of the original saved version. The learner approved the narrated video. This documentation update does not claim a new test run.

## Decisions and Open Issues
- Approved direction: local Streamlit/SQLite, narrowed demonstration, existing supporting features, no 50-investor pool for this phase.
- The completed learning recap covered both business criteria-to-result flow and software save/reopen flow; the video demonstrates both. No comprehension score or live code tour is claimed.
- ReportLab is included in requirements.txt; README matches the current workflow.
- Inspect actual Git history and build artifacts; do not invent prior commits or reviews.
- Keep the Windows folder flat; root-level planning documents are supported for browser upload.
- Contest required skill-use eligibility remains unresolved; current document approvals do not prove pre-build compliance.

## Review State
Reconciled with the approved scope and PRD and inspected source functions on October 6, 2026. The learner explicitly approved the technical plan on October 6, 2026, after confirming inclusion of email drafts and response tracking. This is a current technical review of an existing app, not a claim of pre-build specification approval.
