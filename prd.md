---
doc: prd
status: draft
---
# New Venture Fit Analysis Product Requirements

Source: scope.md > The Core Loop and The POC Boundary. Define the customer-facing Funding Fit Brief first, then derive the research and implementation requirements.

## The Core Journey
1. Complete the accepted founder intake, allowing unknown and not-yet responses.
2. Read and correct a concise venture summary before evaluating.
3. Screen the available researched pool using six factors and display actual coverage.
4. Inspect a shortlist with reasons, concerns, evidence quality and next steps.
5. Open investor details, verified contacts, approach routes and an editable introduction email.
6. Save the assessment, download the brief/shortlist and reopen the saved result later.

## Screens and Layout
Venture Profile; Funding Fit Results with expandable investor details; Saved Assessments. Avoid a dense database table as the main results experience. No account flow for local single-user use.

## Look and Feel
Compact summary, clear fit labels, readable source links and plain language. User accepted the form questions and deferred formatting. Final colors and detailed layout remain open.

## Features and Behavior

### Founder Intake and Confirmation
Preserve the 12 questions in founder_intake.docx: identity/website; location/formation; product/customer/problem; AI role/advantage; progress; demand evidence; team; target/timing; use/milestone; past funding; funding preferences/equity; constraints. Optional unknowns are not zero or false. Confirm derived stage and sector tags when ambiguous. Future goals never become achieved traction. Market size and unit economics can be flagged for follow-up rather than invented.

### Funding Fit Brief
Show venture summary, coverage, prioritized shortlist, detailed six-factor assessments, verified contacts, next steps and evidence dates. Each displayed conclusion distinguishes founder-reported facts, sourced investor facts and analyst inference. Include Strong Fit, Conditional Fit, Poor Fit and Insufficient Evidence; explain classifications. Strong Fit is alignment with reviewed criteria, not a prediction of funding.

### Matching and Evidence
Hard requirements outweigh positive factors. Preferences and typical profiles are not universal eligibility rules. Unknown evidence earns no positive match. Keep fit classification separate from evidence quality. Use a useful contributing check rather than requiring every investor to fund the whole round; calculate illustrative contribution and remaining amount with no implication of commitment. Lead versus participant role is shown only when supported. Portfolio conflicts must be researched or labeled unreviewed; a related company is not automatically a conflict.

### Contacts and Approach Routes
Name and role of a relevant investment professional, why relevant, official source/date, optional company line and verified business email or official pitch form. A title alone does not establish final decision authority. Angel-group screening/application contacts are valid routes. No guessed emails, personal lines or LinkedIn sourcing. Use an official organizational route when an individual cannot be verified.

### Email Template
Populate a reusable introduction template with confirmed venture facts and supported investor relevance. Founder fills recipient/referral, signature and optional deck link, reviews and sends. Copy/download capability; no sending integration. Unknown or inferred material is not silently presented as verified personalization.

### Outreach History
Each venture–funding-organization pair has a manual dropdown: Not contacted; Contacted—awaiting response; Positive response; Negative response; Responded—follow-up needed; No response. Optional event date and short note. Default display is Not contacted if no event exists. Append changes so history survives a new assessment; do not infer outcomes from email or time elapsed. No response never changes fit or becomes rejection.

### Saved Assessments and Downloads
Save inputs, investor versions, conclusions, sources, method version and date together. Reopening reproduces the saved result even after new research is imported. A changed profile or new research creates a new assessment. Offer PDF brief and spreadsheet shortlist; file format details to settle in spec. Saved results are local, not multi-user access controlled.

## States and Boundaries
No match: explain known mismatches, missing evidence and coverage limits. Empty pool: prompt for research import, do not fabricate recommendations. Bad imports: explain errors and commit no partial records. Unknown firm mandate: preserve uncertainty. Out-of-scope growth firms may be test controls but are not shortlist candidates. Real private founder data must not enter a public repository.

## Product Decisions
U.S. focus, AI ventures, angel groups/VC, six accepted factors, intake and worked example accepted as initial direction. Local Streamlit with SQLite accepted in discussion. Approximately 50 firms is a starting target, not proof of complete coverage. Save/reopen and editable outreach templates are in scope.

## Acceptance Criteria
- Synthetic intake yields explainable classifications, including a contributing investor and a poor-fit control.
- Changing founder commitment changes a result where the investor publishes a full-time requirement.
- No-source investor becomes Insufficient Evidence; unknown revenue remains unknown.
- Saved assessment survives app restart and research refresh unchanged.
- Contact/email fields have official evidence or explicit unknown/placeholder status.
- Downloads match the displayed saved assessment and coverage counts.
- Outreach changes append history, survive reassessment and do not change the saved funding-fit result.

## Open Questions
Exact visual layout, freshness threshold, spreadsheet format, AI service choice and any external API costs remain open. Pre-researched pool is the proposed starting approach; live request-time research is not authorized by this draft. These do not block creating the research contract and database schema, but consequential choices must be settled before relevant app behavior is built.
