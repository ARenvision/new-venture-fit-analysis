"""Local prototype: revised founder form -> confirmation -> funding-fit results."""
from __future__ import annotations

import copy
import csv
from io import BytesIO, StringIO
from html import escape
import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from uuid import uuid4
from pathlib import Path

import streamlit as st

from evaluation import (BOOL_FIELDS, FACTORS, LABELS, NUM_FIELDS, PROGRESS, SECTORS, STAGES,
                        email_draft, evaluate_pool, latest_research, number_answer, validate_profile)
from import_research import ResearchError, import_research, load_research

ROOT = Path(__file__).resolve().parent
# Tests may point at an isolated temporary database. No user-facing path editor.
DB = Path(os.environ.get("VENTUREFIT_DEMO_DB", str(ROOT / "demo.db")))
PREFS = ["Angel investors", "Venture capital", "Accelerators", "Grants", "Unsure / Open to guidance"]
OUTREACH_LABELS = {
    "not_contacted": "Not contacted",
    "awaiting_response": "Contacted—awaiting response",
    "positive_response": "Positive response",
    "negative_response": "Negative response",
    "follow_up_needed": "Responded—follow-up needed",
    "no_response": "No response",
}
STAGE_LABELS = {"unknown": "Unknown / undecided", "pre_seed": "Pre-seed", "seed": "Seed", "series_a": "Series A", "later": "Later stage"}
SECTOR_LABELS = {"unknown": "Unknown / undecided", "b2b_software": "B2B software", "consumer_software": "Consumer software", "healthtech": "Health technology", "hardware": "Hardware", "other": "Other"}


def demo_profile():
    return json.loads((ROOT / "demo_venture.json").read_text(encoding="utf-8"))


def blank_profile():
    p = demo_profile()
    for key, value in p.items():
        if isinstance(value, str):
            p[key] = ""
    for key in NUM_FIELDS + BOOL_FIELDS:
        p[key] = None
    p.update(schema_version="1.0", confirmed=False, is_synthetic=True, progress="Unknown", operating_country="United States", funding_stage="unknown", sector="unknown", preferences=[])
    return p


def clear_result():
    for key in ["pending_profile", "assessment", "confirm_checked", "selected_funder", "drafts", "saved_assessment_id", "save_error", "outreach_focus", "prepared_exports", *[k for k in st.session_state if k.startswith("email_")]]:
        st.session_state.pop(key, None)


def set_fields(p):
    values = {}
    for key, value in p.items():
        if key in ("confirmed", "schema_version", "is_synthetic"):
            continue
        if key in NUM_FIELDS:
            value = "" if value is None else f"{value:g}"
        elif key in BOOL_FIELDS:
            value = "Unknown" if value is None else "Yes" if value else "No"
        st.session_state["f_" + key] = value
        values["f_" + key] = value
    st.session_state["form_values"] = values
    clear_result()
    st.session_state.pop("venture_id", None)


def load_demo():
    try:
        info = import_research(load_research(ROOT / "demo_research.json"), DB, allow_demo=True)
        set_fields(demo_profile())
        st.session_state["page"] = "Venture profile"
        st.session_state["notice"] = f"Demo ready: {info['added']} research observations added, {info['duplicates_skipped']} repeats skipped."
    except (ResearchError, OSError, sqlite3.Error) as exc:
        st.session_state["load_error"] = str(exc)


def input_text(label, field, *, area=False, help=None):
    widget = st.text_area if area else st.text_input
    return widget(label, key="f_" + field, help=help)


def yn(label, field):
    return st.selectbox(label, ("Unknown", "Yes", "No"), key="f_" + field)


def collect_profile():
    p = blank_profile()
    for field in p:
        key = "f_" + field
        if key not in st.session_state:
            continue
        value = st.session_state[key]
        if field in NUM_FIELDS:
            value = number_answer(value, field.replace("_", " "), whole=field in ("paying_customers", "unpaid_pilots", "active_users", "founder_count"))
        elif field in BOOL_FIELDS:
            value = {"Unknown": None, "Yes": True, "No": False}[value]
        elif isinstance(value, str):
            value = value.strip()
        p[field] = value
    return validate_profile(p, require_confirmed=False)


def form():
    for key, value in st.session_state["form_values"].items():
        if key not in st.session_state:
            st.session_state[key] = value
    st.subheader("1 · Venture profile")
    st.caption("Short answers are fine. Leave figures blank for unknown. No confidential technical details or founder names required.")
    with st.form("venture_intake"):
        with st.container(border=False, key="intake_overview"):
            section_heading('Venture overview & formation', 'blue')
            cols = st.columns(2)
            with cols[0]: input_text("Q1 · Venture name", "name")
            with cols[1]: input_text("Website (optional)", "website")
            cols = st.columns(3)
            with cols[0]: input_text("Q2 · Operating city", "operating_city")
            with cols[1]: input_text("Operating state", "operating_state", help="Two-letter state code, for example TN.")
            with cols[2]: st.selectbox("Operating country", ("United States", "Other", "Unknown"), key="f_operating_country")
            input_text("Company formation", "formation", help="Country/state of incorporation, or not formed yet.")
        with st.container(border=False, key="intake_business"):
            section_heading('Business proposition & AI advantage', 'purple')
            input_text("Q3 · What are you building?", "product")
            cols = st.columns(2)
            with cols[0]: input_text("Who would pay for it?", "customer")
            with cols[1]: input_text("What problem does it solve?", "problem")
            input_text("Q4 · How does AI help deliver the product?", "ai_role", area=True)
            input_text("Why would a customer choose your solution?", "advantage")
        with st.container(border=False, key="intake_demand"):
            section_heading('Progress & evidence of demand', 'green')
            st.selectbox("Q5 · Furthest progress reached", PROGRESS, key="f_progress")
            st.caption("Q6 · Current demand: achieved figures only. Future customer goals belong under Q9.")
            cols = st.columns(4)
            with cols[0]: input_text("Paying customers", "paying_customers")
            with cols[1]: input_text("Unpaid pilots", "unpaid_pilots")
            with cols[2]: input_text("Active users", "active_users")
            with cols[3]: input_text("Monthly revenue (USD)", "monthly_revenue_usd")
            input_text("Key customer signal", "demand_signal", area=True)
        with st.container(border=False, key="intake_team"):
            section_heading('Team capability', 'blue')
            cols = st.columns(2)
            with cols[0]: input_text("Q7 · Number of founders", "founder_count")
            with cols[1]: yn("Are all founders full-time?", "all_founders_full_time")
            input_text("Relevant industry, technical and sales experience", "team_experience", area=True)
        with st.container(border=False, key="intake_funding"):
            section_heading('Funding target & preferences', 'blue')
            cols = st.columns(3)
            with cols[0]: input_text("Q8 · Target amount / range minimum (USD)", "target_min_usd")
            with cols[1]: input_text("Range maximum (optional, USD)", "target_max_usd")
            with cols[2]: input_text("Target raise timing", "raise_timing")
            input_text("Q9 · Main uses of funding", "funding_uses")
            cols = st.columns(2)
            with cols[0]: input_text("Specific milestone to achieve", "milestone")
            with cols[1]: input_text("Milestone timeframe", "milestone_timeframe")
            input_text("Q10 · Previous funding: amount, approximate date and type", "previous_funding", area=True)
            st.multiselect("Q11 · Funding routes you would consider", PREFS, key="f_preferences")
            st.caption("This prototype evaluates angel and venture-capital funding. Grants and accelerators are recorded as preferences only.")
            yn("Would you consider giving up equity?", "equity_willing")
        with st.container(border=False, key="intake_constraints"):
            section_heading('Constraints & next steps', 'amber')
            yn("Q12 · Would you relocate for funding?", "relocation_willing")
            input_text("Other constraints, exclusions or important context (optional)", "constraints", area=True, help="Free-text constraints remain flagged for human review.")
        with st.container(border=False, key="intake_matching"):
            section_heading('Fields to confirm for matching', 'green')
            st.caption("Choose these explicitly. Product progress alone does not determine your funding stage or sector.")
            cols = st.columns(2)
            with cols[0]: st.selectbox("Funding stage", STAGES, format_func=STAGE_LABELS.get, key="f_funding_stage")
            with cols[1]: st.selectbox("Primary sector", SECTORS, format_func=SECTOR_LABELS.get, key="f_sector")
        submitted = st.form_submit_button("Review venture summary", type="primary", key="review")
    if submitted:
        clear_result()
        try:
            st.session_state["pending_profile"] = collect_profile()
            st.session_state["form_values"] = {key: st.session_state[key] for key in st.session_state["form_values"]}
            st.session_state["next_page"] = "Confirm summary"
            st.rerun()
        except ResearchError as exc:
            st.error(str(exc))


def section_heading(title, tone="blue"):
    paths = {
        "blue": '<rect x="5" y="7" width="14" height="13" rx="2"/><path d="M9 7V4h6v3M5 12h14M10 12v3h4v-3"/>',
        "green": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
        "purple": '<path d="M4 21h16M6 21V9l6-5 6 5v12M10 21v-7h4v7M9 10h.01M15 10h.01"/>',
        "amber": '<path d="M12 3 2 20h20L12 3Z M12 9v5M12 17h.01"/>',
        "red": '<path d="m12 3 3 6 6 1-4 5 1 6-6-3-6 3 1-6-4-5 6-1 3-6Z"/>',
    }
    glyph = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths.get(tone, paths["blue"]) + '</svg>'
    st.markdown('<div class="section-heading"><span class="module-icon ' + tone + '">' + glyph + '</span><h4>' + escape(title) + '</h4></div>', unsafe_allow_html=True)


def detail_box(title, value, note=""):
    """Render supplied text safely; founder and research text never become HTML."""
    st.markdown(
        '<div class="detail-box"><div class="detail-label">' + escape(str(title)) +
        '</div><div class="detail-value">' + escape(str(value)) + '</div>' +
        ('<div class="detail-note">' + escape(str(note)) + '</div>' if note else '') + '</div>',
        unsafe_allow_html=True,
    )


def display_answer(value):
    if value is None or value == "" or value == []:
        return "Unknown / not provided"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def show_profile(p):
    with st.container(border=True):
        st.markdown("### " + p["name"])
        st.write(p["product"])
        cols = st.columns(3)
        with cols[0]:
            detail_box("Location & formation", ", ".join(x for x in (p["operating_city"], p["operating_state"], p["operating_country"]) if x) or "Unknown", p["formation"] or "Formation unknown")
        with cols[1]:
            detail_box("Stage & sector", STAGE_LABELS[p["funding_stage"]] + " · " + SECTOR_LABELS[p["sector"]], "Product progress: " + p["progress"])
        with cols[2]:
            value = f"${p['target_min_usd']:,.0f}" if p["target_min_usd"] is not None else "Undecided"
            if p["target_max_usd"] is not None: value += f"–${p['target_max_usd']:,.0f}"
            detail_box("Funding target", value, p["raise_timing"] or "Timing unknown")
        cols = st.columns(3)
        for col, field, label in zip(cols, ("paying_customers", "unpaid_pilots", "monthly_revenue_usd"), ("Paying customers", "Unpaid pilots", "Monthly revenue")):
            value = "Unknown" if p[field] is None else (f"${p[field]:,.0f}" if field == "monthly_revenue_usd" else f"{p[field]:g}")
            with col: detail_box(label, value)
        st.caption("Founder-reported information. Milestones describe future goals, not achieved traction.")
        with st.expander("Check all answers"):
            groups = (
                ("Venture overview & formation", ("name", "website", "operating_city", "operating_state", "operating_country", "formation")),
                ("Business proposition & AI advantage", ("product", "customer", "problem", "ai_role", "advantage")),
                ("Progress & evidence of demand", ("progress", "paying_customers", "unpaid_pilots", "active_users", "monthly_revenue_usd", "demand_signal")),
                ("Team capability", ("founder_count", "all_founders_full_time", "team_experience")),
                ("Funding target & preferences", ("target_min_usd", "target_max_usd", "raise_timing", "funding_uses", "milestone", "milestone_timeframe", "previous_funding", "preferences", "equity_willing")),
                ("Constraints & matching fields", ("relocation_willing", "constraints", "funding_stage", "sector")),
            )
            for title, fields in groups:
                with st.container(border=True):
                    st.markdown("#### " + title)
                    cols = st.columns(2)
                    for j, field in enumerate(fields):
                        value = p.get(field)
                        if field == "funding_stage": value = STAGE_LABELS.get(value, value)
                        if field == "sector": value = SECTOR_LABELS.get(value, value)
                        with cols[j % 2]: detail_box(field.replace("_", " ").capitalize(), display_answer(value))


def confirm():
    p = st.session_state.get("pending_profile")
    if not p:
        st.info("Complete the venture profile first.")
        return
    st.subheader("2 · Confirm venture summary")
    show_profile(p)
    if st.button("Edit answers", key="edit_summary"):
        clear_result()
        st.session_state["next_page"] = "Venture profile"
        st.rerun()
    with st.form("confirm_form"):
        agreed = st.checkbox("I checked the summary and matching fields; these reflect the venture.", key="confirm_checked")
        go = st.form_submit_button("Evaluate funding fit", type="primary", key="evaluate")
    if go:
        if not agreed:
            st.error("Confirm the summary before evaluating.")
            return
        try:
            if p["operating_country"] != "United States":
                raise ResearchError("This prototype serves ventures operating in the United States. Correct the country or keep this profile outside the evaluation.")
            records = latest_research(DB)
            if not records:
                raise ResearchError("The research pool is empty. Use Load synthetic example to prepare the demonstration.")
            p = copy.deepcopy(p)
            p["confirmed"] = True
            book = json.loads((ROOT / "matching_rules.json").read_text(encoding="utf-8"))
            st.session_state["assessment"] = evaluate_pool(p, records, book)
            st.session_state["assessment"]["rulebook"] = copy.deepcopy(book)
            save_current_assessment()
            st.session_state["next_page"] = "Funding fit results"
            st.rerun()
        except (ResearchError, OSError, ValueError, sqlite3.Error) as exc:
            st.error(str(exc))


def remember_email(key):
    st.session_state.setdefault("drafts", {})[key] = st.session_state[key]
    try:
        save_current_assessment()
    except (OSError, ValueError, sqlite3.Error) as exc:
        st.session_state["save_error"] = True
        st.session_state["load_error"] = "Draft is still in this session, but could not be saved: " + str(exc)



def database_connection():
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    except Exception:
        conn.close()
        raise
    return conn


def assessment_drafts(assessment):
    drafts = dict(st.session_state.get("drafts", {}))
    for i, result in enumerate(assessment["results"]):
        if not result["shortlisted"]: continue
        subject, body = clean_email(assessment["venture"], result).split("\n\n", 1)
        key = f"email_{i}_{result['observation_id']}"
        for widget_key, default in ((key, body), (key + "_subject", subject.removeprefix("Subject: "))):
            drafts[widget_key] = st.session_state.get(widget_key, drafts.get(widget_key, default))
    return drafts


def save_current_assessment():
    """Append a complete snapshot atomically; identical saves reuse the last version."""
    assessment = st.session_state.get("assessment")
    if not assessment: return None
    venture = assessment["venture"]
    validate_profile(venture)
    venture_id = st.session_state.get("venture_id") or str(uuid4())
    drafts = assessment_drafts(assessment)
    snapshot = json.dumps({"assessment": assessment, "drafts": drafts}, sort_keys=True, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    conn = database_connection()
    try:
        with conn:
            previous = conn.execute("SELECT assessment_id, summary_json FROM assessments WHERE venture_id=? ORDER BY generated_at DESC, rowid DESC LIMIT 1", (venture_id,)).fetchone()
            if previous and previous[1] == snapshot:
                assessment_id = previous[0]
            else:
                assessment_id, profile_id = str(uuid4()), str(uuid4())
                conn.execute("INSERT OR IGNORE INTO ventures VALUES (?,?,?,?)", (venture_id, venture["name"], int(venture["is_synthetic"]), now))
                conn.execute("INSERT INTO venture_profiles VALUES (?,?,?,?,?)", (profile_id, venture_id, now, venture["schema_version"], json.dumps(venture, ensure_ascii=False)))
                coverage = assessment["coverage"]
                conn.execute("INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?)", (assessment_id, venture_id, profile_id, now, assessment["method"], coverage["pool_size"], coverage["screened"], coverage["shortlisted"], json.dumps(coverage), snapshot))
                for order, result in enumerate(assessment["results"], 1):
                    conn.execute("INSERT INTO assessment_results VALUES (?,?,?,?,?,?,?,?,?)", (str(uuid4()), assessment_id, result["organization_id"], result["observation_id"], result["classification"], result["evidence_quality"], int(result["shortlisted"]), order, json.dumps(result, ensure_ascii=False)))
        st.session_state["venture_id"] = venture_id
        st.session_state["saved_assessment_id"] = assessment_id
        st.session_state.pop("save_error", None)
        st.session_state["drafts"] = drafts
        return assessment_id
    finally:
        conn.close()


def reopen_assessment(assessment_id):
    conn = database_connection()
    try:
        row = conn.execute("SELECT venture_id, summary_json FROM assessments WHERE assessment_id=?", (assessment_id,)).fetchone()
        outreach_target = conn.execute("SELECT r.observation_id,r.organization_id FROM outreach_events e JOIN assessment_results r ON r.organization_id=e.organization_id AND r.assessment_id=? WHERE e.venture_id=? ORDER BY e.event_sequence DESC LIMIT 1", (assessment_id, row[0])).fetchone() if row else None
    finally:
        conn.close()
    if not row: raise ValueError("Saved assessment was not found.")
    snapshot = json.loads(row[1])
    assessment = snapshot["assessment"]
    set_fields(assessment["venture"])
    st.session_state["pending_profile"] = copy.deepcopy(assessment["venture"])
    st.session_state["assessment"] = assessment
    st.session_state["drafts"] = snapshot["drafts"]
    st.session_state["venture_id"] = row[0]
    st.session_state["saved_assessment_id"] = assessment_id
    st.session_state["confirm_checked"] = True
    if outreach_target:
        st.session_state["selected_funder"] = outreach_target[0]
        st.session_state["outreach_focus"] = outreach_target[1]
    st.session_state["next_page"] = "Funding fit results"


def saved_assessments():
    st.subheader("Saved assessments")
    st.caption("Reopen a saved version with its original answers, funding findings, research and email drafts.")
    if not DB.exists():
        st.info("No assessments saved yet. Complete and evaluate a venture profile first.")
        return
    try:
        conn = database_connection()
        try:
            rows = conn.execute("SELECT a.assessment_id, a.generated_at, a.summary_json, a.venture_id FROM assessments a ORDER BY a.generated_at DESC, a.rowid DESC").fetchall()
        finally:
            conn.close()
        if not rows:
            st.info("No assessments saved yet. Complete and evaluate a venture profile first.")
            return
        labels = {}
        copies = {}
        names = {}
        for assessment_id, saved_at, payload, venture_id in reversed(rows):
            name = json.loads(payload)["assessment"]["venture"]["name"]
            group = names.setdefault(name, [])
            if venture_id not in group: group.append(venture_id)
            copies[venture_id] = group.index(venture_id) + 1
        for version, (assessment_id, saved_at, payload, venture_id) in enumerate(rows):
            assessment = json.loads(payload)["assessment"]
            name = assessment["venture"]["name"]
            copy_label = " · Venture copy " + str(copies[venture_id]) if len(names[name]) > 1 else ""
            labels[assessment_id] = name + copy_label + " · " + datetime.fromisoformat(saved_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") + " · Save " + str(len(rows) - version)
        chosen = st.selectbox("Saved version (newest first)", list(labels), format_func=labels.get, key="saved_selection")
        selected_row = next(row for row in rows if row[0] == chosen)
        selected = json.loads(selected_row[2])["assessment"]
        show_profile(selected["venture"])
        st.caption(f"{selected['coverage']['screened']} organizations screened · {selected['coverage']['shortlisted']} shortlisted. Each saved change keeps the earlier version.")
        name = selected["venture"]["name"]
        if len(names[name]) > 1:
            st.caption("Separate copies of this venture have separate outreach histories. Choose the copy you updated.")
        conn = database_connection()
        try:
            outreach = conn.execute("SELECT o.canonical_name,e.status,e.occurred_on,e.note FROM latest_outreach_status e JOIN organizations o ON o.organization_id=e.organization_id WHERE e.venture_id=? ORDER BY e.event_sequence DESC", (selected_row[3],)).fetchall()
        finally:
            conn.close()
        st.markdown("**Current saved outreach for this venture**")
        if outreach:
            st.dataframe([{"Organization": name, "Status": OUTREACH_LABELS[status], "Contact / response date": occurred_on or "Not specified", "Notes": note or ""} for name, status, occurred_on, note in outreach], hide_index=True, use_container_width=True)
        else:
            st.caption("No outreach updates saved for this venture.")
        if st.button("Reopen assessment", key="reopen_saved", type="primary"):
            reopen_assessment(chosen)
            st.rerun()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        st.error("Could not open saved assessments: " + str(exc))



def outreach_history(venture_id, organization_id):
    conn = database_connection()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT * FROM outreach_events WHERE venture_id=? AND organization_id=? ORDER BY event_sequence DESC",
            (venture_id, organization_id))]
    finally:
        conn.close()


def record_outreach(venture_id, organization_id, assessment_id, status, occurred_on=None, note=""):
    """Latest RECORDED event is current; backdated events never rewrite history."""
    if status not in OUTREACH_LABELS: raise ValueError("Choose a valid outreach status.")
    if occurred_on is not None:
        occurred_on = date.fromisoformat(str(occurred_on)).isoformat()
    note = note.strip() or None
    if note and len(note) > 2000: raise ValueError("Outreach notes must be 2,000 characters or fewer.")
    conn = database_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM assessments a JOIN assessment_results r ON r.assessment_id=a.assessment_id WHERE a.assessment_id=? AND a.venture_id=? AND r.organization_id=?", (assessment_id, venture_id, organization_id)).fetchone():
                raise ValueError("Save an assessment containing this venture and organization before recording outreach.")
            latest = conn.execute("SELECT event_id, status, occurred_on, note FROM outreach_events WHERE venture_id=? AND organization_id=? ORDER BY event_sequence DESC LIMIT 1", (venture_id, organization_id)).fetchone()
            if latest and latest[1:] == (status, occurred_on, note): return latest[0]
            event_id = str(uuid4())
            conn.execute("INSERT INTO outreach_events (event_id,venture_id,organization_id,assessment_id,status,occurred_on,recorded_at,note) VALUES (?,?,?,?,?,?,?,?)", (event_id, venture_id, organization_id, assessment_id, status, occurred_on, datetime.now(timezone.utc).isoformat(), note))
            return event_id
    finally:
        conn.close()


def show_outreach(result):
    venture_id = st.session_state.get("venture_id")
    assessment_id = st.session_state.get("saved_assessment_id")
    if not venture_id or not assessment_id:
        st.caption("Save this assessment to start outreach tracking.")
        return
    try:
        history = outreach_history(venture_id, result["organization_id"])
    except (OSError, sqlite3.Error) as exc:
        st.error("Could not load outreach history: " + str(exc))
        return
    current = history[0] if history else {"status": "not_contacted", "occurred_on": None, "note": None, "event_sequence": 0}
    with st.expander("Outreach tracking · " + OUTREACH_LABELS[current["status"]], expanded=st.session_state.get("outreach_focus") == result["organization_id"]):
        st.caption("Current status for this venture and organization, shared across assessment versions. Updating it keeps all earlier entries.")
        if result["organization"]["canonical_domain"].endswith(".example"):
            st.caption("Demo tracking exercise only; no email is sent.")
        if history:
            saved_at = datetime.fromisoformat(current["recorded_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            st.caption("Saved status: " + OUTREACH_LABELS[current["status"]] + " · Saved " + saved_at)
        prefix = f"outreach_{venture_id}_{result['organization_id']}"
        version = prefix + "_" + str(current["event_sequence"])
        with st.form(prefix + "_form"):
            cols = st.columns(2)
            with cols[0]:
                status = st.selectbox("Outreach status", list(OUTREACH_LABELS), index=list(OUTREACH_LABELS).index(current["status"]), format_func=OUTREACH_LABELS.get, key=version + "_status")
            with cols[1]:
                occurred_on = st.date_input("Contact / response date (optional)", value=date.fromisoformat(current["occurred_on"]) if current["occurred_on"] else None, key=version + "_date")
            note = st.text_area("Outreach notes (optional)", value=current["note"] or "", max_chars=2000, height=100, key=version + "_note", placeholder="For example: introduction sent; requested a deck; follow up next week.")
            submitted = st.form_submit_button("Save outreach update", type="primary", key=prefix + "_save")
        st.caption("No response means no reply has been recorded; it does not mean rejection and does not change funding fit.")
        if submitted:
            try:
                event_id = record_outreach(venture_id, result["organization_id"], assessment_id, status, occurred_on, note)
                saved = outreach_history(venture_id, result["organization_id"])
                if not saved or saved[0]["event_id"] != event_id:
                    raise ValueError("Could not confirm the outreach update in the database. Retry the save.")
                st.session_state["outreach_focus"] = result["organization_id"]
                st.session_state.pop("prepared_exports", None)
                st.session_state["notice"] = "Outreach update saved for " + result["name"] + "."
                st.rerun()
            except (OSError, ValueError, sqlite3.Error) as exc:
                st.error("Could not save outreach update: " + str(exc))
        if history:
            st.markdown("**History · newest recorded first**")
            st.dataframe([
                {"Status": OUTREACH_LABELS[event["status"]], "Contact / response date": event["occurred_on"] or "Not specified", "Notes": event["note"] or "", "Saved": datetime.fromisoformat(event["recorded_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")}
                for event in history
            ], hide_index=True, use_container_width=True)
        else:
            st.caption("No outreach updates recorded yet.")


def readable(text):
    text = str(text)
    for raw, label in {**STAGE_LABELS, **SECTOR_LABELS}.items():
        if raw not in ("unknown", "later"):
            text = re.sub(r"(?<![\w-])" + re.escape(raw) + r"(?![\w-])", lambda match: label, text)
    text = text.replace("Founder value: later", "Founder value: Later stage")
    text = text.replace("Founder value:", "Your answer:")
    text = re.sub(r"\bTrue\b", "Yes", text)
    text = re.sub(r"\bFalse\b", "No", text)
    return re.sub(r"Synthetic (investment focus|preference|mandate|policy|requirement|published first check|funding)", lambda m: m[1].capitalize(), text)


def fit_takeaway(result):
    if result["classification"] == "strong_fit":
        return "Your venture aligns with the reviewed criteria across all six factors."
    if result["classification"] == "poor_fit":
        for factor in result["factors"]:
            for entry in factor["entries"]:
                if entry["status"] == "mismatch" and entry["rule_type"] == "hard_requirement":
                    if "all founders work full-time" in entry["description"]:
                        return "Full-time founder requirement not met."
                    return readable(entry["description"])
    issues = result["concerns"] + result["unknowns"]
    return readable(issues[0]) if issues else result["next_step"]


def clean_email(venture, result):
    draft = email_draft(venture, result)
    sector = next((x for x in result["organization"]["criteria"]["sector"]["findings"] if x["evidence_status"] == "verified" and x["rule_type"] in ("hard_requirement", "preference", "typical_profile")), None)
    if sector:
        draft = draft.replace("Your published focus states: " + sector["statement"], "[Add a verified reason your venture fits this organization's current focus.]")
    traction = []
    if venture["paying_customers"] is not None:
        traction.append(f"{venture['paying_customers']:g} paying customers")
    if venture["monthly_revenue_usd"] is not None:
        traction.append(f"${venture['monthly_revenue_usd']:,.0f} in monthly revenue")
    achieved = "Current traction: " + " and ".join(traction) + "." if traction else "[Add confirmed customer or revenue traction.]"
    if venture["unpaid_pilots"] is not None:
        achieved += f" Separately, we have {venture['unpaid_pilots']:g} unpaid pilots."
    return draft.replace("[Add a concise confirmed traction statement.]", achieved)


def factor_entry(entry, factor, index, org, venture, rules):
    criteria = entry["description"].split(" Founder value:")[0]
    factor_rules = [r for r in rules if r["factor"] == factor]
    rule = factor_rules[index] if index < len(factor_rules) else None
    if rule:
        field = rule["field"]
        value = venture[field]
        if field == "funding_stage": value = STAGE_LABELS.get(value, value)
        if field == "sector": value = SECTOR_LABELS.get(value, value)
        answer = field.replace("_", " ").capitalize() + ": " + display_answer(value)
    elif factor == "amount":
        answer = "Funding target: " + (f"${venture['target_min_usd']:,.0f}" if venture['target_min_usd'] is not None else "Unknown")
        if venture['target_max_usd'] is not None: answer += f"–${venture['target_max_usd']:,.0f}"
    else:
        answer = "No reviewed comparison available."
    finding = {"aligned": "Aligned with this criterion", "mismatch": "Requirement not met" if entry["rule_type"] == "hard_requirement" else "Outside this preference; review before approaching", "unknown": "Unresolved; do not assume a match"}.get(entry["status"], entry["status"])
    if entry["evidence_status"] == "inferred": finding += " · Inference requiring review"
    titles = [source["title"] for source in org["sources"] if source["source_id"] in entry["source_ids"]]
    note = "Illustrative demo criteria" if org["canonical_domain"].endswith(".example") else entry["evidence_status"].replace("_", " ").capitalize()
    note += " · " + entry["rule_type"].replace("_", " ") + " · " + (", ".join(titles) or "No source recorded")
    detail_box("Investor criteria", readable(criteria))
    detail_box("Your venture", answer)
    detail_box("Finding", finding, note)


def result_card(result, venture, i):
    org = result["organization"]
    demo = org["canonical_domain"].endswith(".example")
    with st.container(border=True):
        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(f"### {result['name']}")
            st.caption("Research: " + result["research_date"][:10] + (" · Synthetic demonstration" if demo else ""))
        with cols[1]:
            label = LABELS[result["classification"]]
            tone = {"Strong Fit": "strong", "Conditional Fit": "conditional", "Poor Fit": "poor"}.get(label, "unknown")
            st.markdown('<span class="fit-badge ' + tone + '">' + escape(label) + '</span>', unsafe_allow_html=True)
            st.caption("Illustrative demo criteria" if demo else "Evidence: " + result["evidence_quality"].replace("_", " "))
        detail_box("Fit summary", fit_takeaway(result), result["next_step"])
        c = result["contribution"]
        if c:
            cols = st.columns(3)
            with cols[0]: detail_box("Illustrative check", f"${c['amount_usd']:,.0f}")
            with cols[1]: detail_box("Share of this round", f"{c['percentage_min']:.0f}%" + (f"–{c['percentage_max']:.0f}%" if c["percentage_min"] != c["percentage_max"] else ""))
            with cols[2]: detail_box("Still to raise", f"${c['remaining_min_usd']:,.0f}" + (f"–${c['remaining_max_usd']:,.0f}" if c["remaining_min_usd"] != c["remaining_max_usd"] else ""))
            st.caption("Illustrative only. No investment commitment or funding probability is implied.")
        with st.expander("Six factors & findings", expanded=True):
            if not result["factors"]: st.caption("Outside scope; detailed fit evaluation was not performed.")
            rulebook = st.session_state["assessment"].get("rulebook", {"organizations": {}})
            rules = rulebook["organizations"].get(org["canonical_domain"], {}).get("criteria", [])
            for offset in range(0, len(result["factors"]), 2):
                cols = st.columns(2)
                for j, factor in enumerate(result["factors"][offset:offset + 2]):
                    with cols[j]:
                        with st.container(border=True, key=f"factor_card_{i}_{offset+j}"):
                            title = "Funding amount" if factor["factor"] == "amount" else factor["factor"].capitalize()
                            section_heading(title, {"stage": "blue", "sector": "purple", "geography": "green", "traction": "green", "restrictions": "amber"}.get(factor["factor"], "blue"))
                            for index, entry in enumerate(factor["entries"]):
                                factor_entry(entry, factor["factor"], index, org, venture, rules)
        with st.expander("Conditions & unknowns"):
            for title, issues in (("Concerns & conditions", result["concerns"]), ("Unknowns to resolve", result["unknowns"])):
                st.markdown("**" + title + "**")
                for issue in issues: st.write("• " + readable(issue))
                if not issues: st.caption("None recorded")
        with st.expander("Sources & verification"):
            if demo: st.caption("Demo placeholder—not a live source. No real investor or live page was verified.")
            for source in org["sources"]:
                if demo:
                    st.write(source["title"] + " · " + source["checked_on"])
                    st.caption(source["url"])
                else:
                    st.link_button(source["title"], source["url"])
                    st.caption("Checked " + source["checked_on"])
        with st.expander("Contacts & approach route"):
            if demo: st.caption("Demo contact route—placeholder. These organizations are fictional.")
            if not org["contacts"]: st.caption("No relevant individual contact or decision authority has been verified.")
            for contact in org["contacts"]:
                detail_box(contact["name"] + " · " + contact["position"], contact["relevance"], "Decision authority: " + contact["decision_authority"].replace("_", " "))
            for route in org["approach_routes"]:
                st.write(route["label"] + " · " + route["value"])
                st.caption(route["note"])
        show_outreach(result)
        if result["shortlisted"]:
            with st.expander("Editable introduction email"):
                st.caption("Replace recipient, referral, fit reason, deck link and signature placeholders. Review all claims before use.")
                initial = clean_email(venture, result)
                subject, body = initial.split("\n\n", 1)
                prefix = f"email_{i}_{result['observation_id']}"
                subject_key, body_key = prefix + "_subject", prefix
                drafts = st.session_state.get("drafts", {})
                st.text_input("Subject", value=drafts.get(subject_key, subject.removeprefix("Subject: ")), key=subject_key, on_change=remember_email, args=(subject_key,))
                st.text_area("Draft for " + result["name"], value=drafts.get(body_key, body), key=body_key, height=340, on_change=remember_email, args=(body_key,))
                full = "Subject: " + st.session_state[subject_key] + "\n\n" + st.session_state[body_key]
                st.download_button("Download draft", full, file_name="introduction_email.txt", mime="text/plain", key=prefix + "_download")
                with st.expander("Copy draft text"):
                    st.code(full, language=None, wrap_lines=True)


def funding_tile(row, i, outreach_status="not_contacted"):
    """Compact summary; the native button opens full-width evidence below the grid."""
    tone = {"strong_fit": "green", "conditional_fit": "amber", "poor_fit": "red"}.get(row["classification"], "purple")
    with st.container(border=True, key=f"funding_tile_{i}"):
        section_heading(row["name"], tone)
        label = LABELS[row["classification"]]
        badge = {"strong_fit": "strong", "conditional_fit": "conditional", "poor_fit": "poor"}.get(row["classification"], "unknown")
        check = row["organization"]["check_size"]
        amount = check.get("typical_usd")
        check_text = f"Typical check: ${amount:,.0f}" if amount is not None else "Typical check: unverified"
        takeaway = fit_takeaway(row)
        st.markdown('<div class="tile-body"><span class="fit-badge ' + badge + '">' + escape(label) + '</span><p class="tile-check">' + escape(check_text) + '</p><p class="tile-copy">' + escape(takeaway) + '</p><p class="tile-date">Research ' + escape(row["research_date"][:10]) + ' · Synthetic demo</p></div>', unsafe_allow_html=True)
        st.caption("Outreach: " + (OUTREACH_LABELS[outreach_status] if outreach_status is not None else "Unavailable"))
        if st.button("View details →", key=f"view_funder_{i}", use_container_width=True):
            st.session_state["selected_funder"] = row["observation_id"]


def results():
    a = st.session_state.get("assessment")
    if not a:
        st.info("Review and confirm a venture profile to generate results.")
        return
    st.subheader("3 · Funding Fit Brief")
    st.caption("Alignment with reviewed criteria, not the probability of receiving funding.")
    show_profile(a["venture"])
    cols = st.columns(3)
    for col, title, value in zip(cols, ("Research pool", "Screened", "Shortlisted"), (a["coverage"]["pool_size"], a["coverage"]["screened"], a["coverage"]["shortlisted"])):
        col.metric(title, value)
    st.caption(f"{a['coverage']['out_of_scope']} outside-scope control(s) included in screening. Demonstration pool only; no claim of complete U.S. coverage.")
    if st.session_state.get("save_error"):
        st.warning("Latest draft edits could not be saved. Use Save assessment to retry before closing.")
    elif st.session_state.get("saved_assessment_id"):
        st.success("Assessment saved. Reopen it from Saved assessments. Email edits save automatically when you leave the edited field.")
    else:
        st.warning("This assessment has not been saved. Save it before closing the app.")
    if st.button("Save assessment", key="save_assessment"):
        try:
            save_current_assessment()
            st.success("Saved with current email drafts.")
        except (OSError, ValueError, sqlite3.Error) as exc:
            st.error("Could not save assessment: " + str(exc))
    if not a["coverage"]["shortlisted"]: st.warning("No shortlist from this pool. Review mismatches and missing evidence; no extra firms have been invented.")
    outreach_statuses = {}
    if st.session_state.get("venture_id"):
        try:
            conn = database_connection()
            try:
                outreach_statuses = dict(conn.execute("SELECT organization_id,status FROM latest_outreach_status WHERE venture_id=?", (st.session_state["venture_id"],)))
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as exc:
            outreach_statuses = None
            st.error("Could not load outreach statuses: " + str(exc))
    export_panel(a)
    st.markdown('<div class="grid-label">FUNDING ORGANIZATIONS</div>', unsafe_allow_html=True)
    for offset in range(0, len(a["results"]), 3):
        cols = st.columns(3)
        for j, row in enumerate(a["results"][offset:offset + 3]):
            with cols[j]: funding_tile(row, offset + j, outreach_statuses.get(row["organization_id"], "not_contacted") if outreach_statuses is not None else None)
    if a["results"]:
        selected = st.session_state.get("selected_funder", a["results"][0]["observation_id"])
        i, row = next(((i, row) for i, row in enumerate(a["results"]) if row["observation_id"] == selected), (0, a["results"][0]))
        st.markdown('<div class="grid-label">SELECTED ORGANIZATION · FULL FINDINGS</div>', unsafe_allow_html=True)
        result_card(row, a["venture"], i)
    if st.button("Change venture answers", key="edit_results"):
        clear_result()
        st.session_state["next_page"] = "Venture profile"
        st.rerun()



def export_context(assessment):
    """Read live outreach once so the two downloads share the same export snapshot."""
    statuses = {}
    venture_id = st.session_state.get("venture_id")
    if venture_id:
        conn = database_connection()
        try:
            conn.row_factory = sqlite3.Row
            statuses = {row["organization_id"]: dict(row) for row in conn.execute("SELECT * FROM latest_outreach_status WHERE venture_id=?", (venture_id,))}
        finally:
            conn.close()
    return {"assessment": copy.deepcopy(assessment), "outreach": statuses, "exported_at": datetime.now(timezone.utc).isoformat()}


def utc_time(value):
    if not value: return ""
    return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def csv_safe(value):
    # Keep spreadsheet applications from interpreting supplied text as a formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def shortlist_rows(context):
    a = context["assessment"]
    p = a["venture"]
    rows = []
    for result in a["results"]:
        if not result["shortlisted"]: continue
        org = result["organization"]
        outreach = context["outreach"].get(result["organization_id"], {})
        contribution = result["contribution"] or {}
        demo = org["canonical_domain"].endswith(".example")
        rows.append({
            "Venture": p["name"],
            "Organization": result["name"],
            "Fit": LABELS[result["classification"]],
            "Fit summary": fit_takeaway(result),
            "Recommended next step": result["next_step"],
            "Illustrative check (USD)": contribution.get("amount_usd", ""),
            "Share of round minimum (%)": contribution.get("percentage_min", ""),
            "Share of round maximum (%)": contribution.get("percentage_max", ""),
            "Conditions": " | ".join(readable(x) for x in result["concerns"]),
            "Unknowns": " | ".join(readable(x) for x in result["unknowns"]),
            "Contact": " | ".join(c["name"] + " - " + c["position"] for c in org["contacts"]) or "Not verified",
            "Approach route": " | ".join(r["label"] + ": " + r["value"] for r in org["approach_routes"]) or "Not verified",
            "Sources": " | ".join(s["title"] + " - " + s["url"] + " (checked " + s["checked_on"] + ")" for s in org["sources"]),
            "Evidence": "Illustrative demo criteria; placeholder sources" if demo else result["evidence_quality"].replace("_", " "),
            "Research date": result["research_date"][:10],
            "Outreach status": OUTREACH_LABELS[outreach.get("status", "not_contacted")],
            "Contact / response date": outreach.get("occurred_on") or "",
            "Outreach notes": outreach.get("note") or "",
            "Outreach saved at (UTC)": utc_time(outreach.get("recorded_at")),
            "Assessment generated at (UTC)": utc_time(a["generated_at"]),
            "Exported at (UTC)": utc_time(context["exported_at"]),
        })
    return rows


def shortlist_csv(context):
    columns = ["Venture", "Organization", "Fit", "Fit summary", "Recommended next step", "Illustrative check (USD)", "Share of round minimum (%)", "Share of round maximum (%)", "Conditions", "Unknowns", "Contact", "Approach route", "Sources", "Evidence", "Research date", "Outreach status", "Contact / response date", "Outreach notes", "Outreach saved at (UTC)", "Assessment generated at (UTC)", "Exported at (UTC)"]
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in shortlist_rows(context): writer.writerow({key: csv_safe(value) for key, value in row.items()})
    return stream.getvalue().encode("utf-8-sig")


def funding_brief_pdf(context):
    import reportlab
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    a = context["assessment"]
    p = a["venture"]
    output = BytesIO()
    navy, teal, pale = colors.HexColor("#14243b"), colors.HexColor("#087f74"), colors.HexColor("#f0f5f9")
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "BriefVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("BriefVera", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("BriefVeraBold", str(font_dir / "VeraBd.ttf")))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BriefTitle", fontName="BriefVeraBold", fontSize=22, leading=27, textColor=navy, spaceAfter=12))
    styles.add(ParagraphStyle(name="BriefHeading", fontName="BriefVeraBold", fontSize=11, leading=14, textColor=teal, spaceBefore=9, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle(name="BriefBody", fontName="BriefVera", fontSize=9, leading=12.5, textColor=navy, spaceAfter=5, splitLongWords=True))
    styles.add(ParagraphStyle(name="BriefNote", fontName="BriefVera", fontSize=8, leading=10.5, textColor=colors.HexColor("#526176"), spaceAfter=5, splitLongWords=True))
    styles.add(ParagraphStyle(name="BriefLabel", fontName="BriefVeraBold", fontSize=9, leading=13, textColor=navy))
    styles.add(ParagraphStyle(name="BriefWhite", fontName="BriefVeraBold", fontSize=9, leading=13, textColor=colors.white))
    def safe(value):
        value = str(value).replace("—", " - ").replace("–", "-").replace("·", " | ").replace("’", "'").replace("“", '"').replace("”", '"')
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
        return escape(value).replace("\n", "<br/>")
    def para(value, kind="BriefBody"):
        return Paragraph(safe(value), styles[kind])
    def heading(value): story.append(para(value, "BriefHeading"))
    def box(label, value):
        table = Table([[para(label, "BriefLabel")], [para(value)]], colWidths=[504])
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), pale), ("BOX", (0,0), (-1,-1), .4, colors.HexColor("#d0dde6")), ("LEFTPADDING",(0,0),(-1,-1),12), ("RIGHTPADDING",(0,0),(-1,-1),12), ("TOPPADDING",(0,0),(-1,0),8), ("BOTTOMPADDING",(0,-1),(-1,-1),8)]))
        # Let long paragraphs split between pages instead of keeping oversized cards.
        if len(str(value)) < 1200: story.append(KeepTogether([table, Spacer(1,7)]))
        else:
            story.extend([para(label,"BriefLabel"),para(value)])
    def bullets(values, empty="None recorded"):
        if not values: story.append(para(empty,"BriefNote"))
        for value in values: story.append(para("- " + readable(value)))
    def dollar(value): return "Unknown" if value is None else f"${value:,.0f}"
    def count(value): return "Unknown" if value is None else f"{value:g}"
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#c5d3df"));canvas.line(54,39,558,39)
        canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor("#526176"))
        canvas.drawString(54,26,"New Venture Fit Analysis | Funding Fit Brief")
        canvas.drawRightString(558,26,str(doc.page))
        canvas.restoreState()
    story = [para("Funding Fit Brief", "BriefTitle"), para(p["name"], "BriefHeading")]
    story.append(para("Assessment: " + a["generated_at"][:19].replace("T", " ") + " UTC | Export: " + context["exported_at"][:19].replace("T", " ") + " UTC", "BriefNote"))
    story.append(para("Synthetic demonstration. Fictional investors and placeholder sources; no live investor verification." if p["is_synthetic"] else "Findings reflect the saved research available for this assessment.","BriefNote"))
    story.append(para("Fit describes alignment with reviewed criteria, not the probability of receiving funding. Individual checks are illustrative, not commitments. Outreach reflects the latest saved updates as of export.","BriefNote"))
    heading("Venture overview")
    box("Product", p["product"])
    target = dollar(p["target_min_usd"])
    if p["target_max_usd"] is not None and p["target_max_usd"] != p["target_min_usd"]: target += " - " + dollar(p["target_max_usd"])
    summary = [
        ["Location", ", ".join(x for x in (p["operating_city"],p["operating_state"],p["operating_country"]) if x) or "Unknown"],
        ["Formation", p["formation"] or "Unknown"],
        ["Stage / sector", STAGE_LABELS[p["funding_stage"]] + " / " + SECTOR_LABELS[p["sector"]]],
        ["Funding target / timing", target + " / " + (p["raise_timing"] or "Unknown")],
        ["Paying customers / monthly revenue", count(p["paying_customers"]) + " / " + dollar(p["monthly_revenue_usd"])],
        ["Unpaid pilots (separate)", count(p["unpaid_pilots"])],
        ["Founders / all full-time", count(p["founder_count"]) + " / " + display_answer(p["all_founders_full_time"])],
    ]
    table=Table([[para(k,"BriefLabel"),para(v)] for k,v in summary],colWidths=[192,312],splitInRow=1)
    table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,0),(-1,-1),[pale,colors.white]),("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story.append(table)
    box("Funding uses & future milestone", (p["funding_uses"] or "Unknown") + "\nFuture goal: " + (p["milestone"] or "Not specified") + " | " + (p["milestone_timeframe"] or "Timing unknown"))
    heading("Screening summary")
    c=a["coverage"]
    story.append(para(f"Research pool: {c['pool_size']} | Screened: {c['screened']} | Shortlisted: {c['shortlisted']} | Outside scope: {c['out_of_scope']}"))
    overview=[[para("Organization","BriefWhite"),para("Fit","BriefWhite"),para("Current outreach","BriefWhite")]]
    for result in a["results"]:
        event=context["outreach"].get(result["organization_id"],{})
        overview.append([para(result["name"]),para(LABELS[result["classification"]]),para(OUTREACH_LABELS[event.get("status","not_contacted")])])
    if len(overview)>1:
        table=Table(overview,colWidths=[200,112,192],repeatRows=1,splitInRow=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),navy),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[pale,colors.white]),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story.append(table)
    if not c["shortlisted"]: story.append(para("No shortlist was generated; no additional organizations have been invented."))
    for result in a["results"]:
        story.append(PageBreak())
        story.extend([para(result["name"],"BriefTitle"),para(LABELS[result["classification"]],"BriefHeading")])
        box("Fit summary",fit_takeaway(result) + "\nNext step: " + result["next_step"])
        contribution=result["contribution"]
        if contribution:
            share = f"{contribution['percentage_min']:.0f}%" + (f"-{contribution['percentage_max']:.0f}%" if contribution['percentage_max'] != contribution['percentage_min'] else "")
            remaining = dollar(contribution["remaining_min_usd"]) + (" - " + dollar(contribution["remaining_max_usd"]) if contribution['remaining_max_usd'] != contribution['remaining_min_usd'] else "")
            story.append(para("Illustrative contribution: " + dollar(contribution["amount_usd"]) + " | " + share + " of the round | Still to raise: " + remaining))
        if result["concerns"] or result["unknowns"]:
            heading("Conditions & unknowns")
            bullets(result["concerns"]+result["unknowns"])
        else:
            story.append(para("No conditions or unknowns recorded.","BriefNote"))
        heading("Six factors")
        if not result["factors"]: story.append(para("Outside scope; detailed evaluation was not performed."))
        for factor in result["factors"]:
            label="Funding amount" if factor["factor"]=="amount" else factor["factor"].capitalize()
            story.append(para(label,"BriefLabel"))
            for entry in factor["entries"]:
                finding={"aligned":"Aligned", "mismatch":"Mismatch", "unknown":"Unresolved"}.get(entry["status"],entry["status"])
                story.append(para(finding+": "+readable(entry["description"])))
        org=result["organization"]
        heading("Contacts & approach")
        if not org["contacts"]: story.append(para("No individual contact or decision authority verified.","BriefNote"))
        for contact in org["contacts"]:
            story.append(para(contact["name"]+" - "+contact["position"]+" | "+contact["relevance"]+" | Decision authority: "+contact["decision_authority"].replace("_"," ")))
        for route in org["approach_routes"]: story.append(para(route["label"]+": "+route["value"]+" | "+route["note"],"BriefNote"))
        heading("Sources & verification")
        if org["canonical_domain"].endswith(".example"): story.append(para("Illustrative demo criteria. URLs are placeholders, not live evidence.","BriefNote"))
        for source in org["sources"]: story.append(para(source["title"]+" | "+source["url"]+" | Checked "+source["checked_on"],"BriefNote"))
        heading("Current outreach")
        event=context["outreach"].get(result["organization_id"],{})
        box(OUTREACH_LABELS[event.get("status","not_contacted")], "Contact / response date: "+(event.get("occurred_on") or "Not specified")+"\nNotes: "+(event.get("note") or "None recorded"))
    doc=SimpleDocTemplate(output,pagesize=letter,rightMargin=54,leftMargin=54,topMargin=48,bottomMargin=52,title="Funding Fit Brief",author="New Venture Fit Analysis",allowSplitting=True)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()


def export_panel(assessment):
    with st.expander("Download funding brief & shortlist"):
        st.caption("PDF: all screened organizations. CSV: shortlisted organizations only, ready to open in Excel or Google Sheets. Both include current outreach and original saved findings; exports do not change your data.")
        if st.button("Prepare downloads",key="prepare_exports"):
            try:
                context=export_context(assessment)
                pdf=None
                try:
                    pdf=funding_brief_pdf(context)
                except ImportError:
                    st.warning("PDF export needs ReportLab. In your contest folder, run: python -m pip install reportlab")
                st.session_state["prepared_exports"]={"assessment":copy.deepcopy(assessment),"pdf":pdf,"csv":shortlist_csv(context),"at":context["exported_at"]}
            except (OSError,ValueError,sqlite3.Error) as exc:
                st.error("Could not prepare downloads: "+str(exc))
        prepared=st.session_state.get("prepared_exports")
        if prepared and prepared["assessment"]==assessment:
            st.caption("Prepared "+prepared["at"][:19].replace("T"," ")+" UTC. Prepare again after an outreach update to refresh the downloads.")
            cols=st.columns(2)
            with cols[0]:
                if prepared["pdf"]: st.download_button("Download PDF brief",prepared["pdf"],file_name="funding_brief.pdf",mime="application/pdf",key="download_brief",on_click="ignore")
            with cols[1]:
                st.download_button("Download shortlist CSV",prepared["csv"],file_name="funding_shortlist.csv",mime="text/csv",key="download_shortlist",on_click="ignore")


def start_blank():
    set_fields(blank_profile())
    st.session_state["page"] = "Venture profile"


def main():
    st.set_page_config(page_title="New Venture Fit Analysis", page_icon="🔎", layout="wide")
    st.markdown("""<style>
      :root {color-scheme:dark}
      .stApp,[data-testid="stAppViewContainer"], [data-testid="stMain"] {background:#0f172a;color:#e7edf6}
      [data-testid="stHeader"] {background:#0f172a}
      .block-container {max-width:1320px;padding-top:2rem;padding-bottom:3rem}
      h1,h2,h3,h4 {color:#f1f5fb !important;letter-spacing:-0.02em}
      h4 {font-size:1.02rem !important;margin-bottom:.5rem !important}
      [data-testid="stSidebar"] {background:#111c2d;border-right:1px solid #2d3d54}
      [data-testid="stSidebar"] * {color:#e7edf6}
      [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] {color:#e7edf6}
      [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:#adbbcf !important}
      [data-testid="stVerticalBlockBorderWrapper"] > div {border-color:#334155 !important;border-radius:16px !important;background:#1e293b}
      [class*="st-key-funding_tile_"] {background:#1e293b;border-radius:16px;padding:8px}
      [data-testid="stForm"] {background:transparent !important;border:0 !important;padding:0 !important}
      [class*="st-key-intake_"] {background:#1e293b !important;border:1px solid #52627b !important;border-left:4px solid #38bdf8 !important;border-radius:16px !important;padding:24px !important;margin:0 0 22px !important;box-shadow:0 6px 18px rgba(0,0,0,.16);box-sizing:border-box}
      .st-key-intake_business {border-left-color:#a78bfa !important}
      .st-key-intake_demand,.st-key-intake_matching {border-left-color:#34d399 !important}
      .st-key-intake_constraints {border-left-color:#fbbf24 !important}
      [class*="st-key-intake_"] .section-heading {padding-bottom:16px;border-bottom:1px solid #43536b;margin-bottom:8px}
      [data-testid="stSelectbox"] [role="combobox"],[data-testid="stSelectbox"] button,[data-testid="stMultiSelect"] [role="combobox"] {background:#17253a !important;color:#f1f5fb !important;border:1px solid #52627b !important}
      [data-testid="stSelectbox"] [role="combobox"] *,[data-testid="stSelectbox"] button * {color:#f1f5fb !important}
      [class*="st-key-factor_card_"] {background:#18263b;border:1px solid #43536b !important;border-radius:14px;padding:18px;margin-bottom:18px}
      [class*="st-key-factor_card_"] .detail-box {padding:12px 14px;margin-bottom:10px}
      .section-heading {display:flex;align-items:center;gap:13px;margin:4px 0 14px}
      .section-heading h4 {margin:0 !important;line-height:1.4;font-size:1.07rem !important}
      .module-icon {display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:9px;flex-shrink:0}
      .module-icon svg {width:24px;height:24px}
      .module-icon.blue {background:#143a51;color:#38bdf8}
      .module-icon.green {background:#123c38;color:#34d399}
      .module-icon.purple {background:#372367;color:#a78bfa}
      .module-icon.amber {background:#44351c;color:#fbbf24}
      .module-icon.red {background:#51232e;color:#fb7185}
      .grid-label {color:#94a3b8;font-size:.78rem;font-weight:800;letter-spacing:.2em;padding:22px 0 9px;border-bottom:1px solid #26354a;margin-bottom:22px}
      .tile-body {min-height:195px}
      .tile-check {color:#e2e8f0;font-size:.86rem;margin:4px 0 10px}
      .tile-copy {color:#a8b7cd;font-size:.9rem;line-height:1.55;overflow-wrap:anywhere}
      .tile-date {color:#94a3b8;font-size:.75rem;margin:16px 0 0}
      [class*="st-key-funding_tile_"] button {background:transparent !important;border-color:#3b4d66 !important;color:#bfccdd !important;text-align:left}
      [class*="st-key-funding_tile_"] button:hover {background:#293b52 !important;border-color:#38bdf8 !important}
      [data-testid="stForm"] {border-color:#30415a;background:#0f1929;border-radius:16px}
      [data-testid="stExpander"] {background:#111c2d;border-color:#30415a;border-radius:12px}
      [data-testid="stExpander"] summary {color:#e7edf6}
      .detail-box {background:#1e293b;border:1px solid #334155;border-radius:14px;padding:18px 20px;margin:0 0 14px;overflow-wrap:anywhere}
      .detail-label {color:#90b8c6;font-size:.76rem;font-weight:700;letter-spacing:.055em;text-transform:uppercase;margin-bottom:6px}
      .detail-value {color:#f1f5fb;font-size:.96rem;line-height:1.55;white-space:pre-wrap}
      .detail-note {color:#adbbcf;font-size:.8rem;line-height:1.5;margin-top:8px;white-space:pre-wrap}
      .fit-badge {display:inline-block;padding:7px 12px;border-radius:999px;font-weight:700;font-size:.85rem;margin:8px 0}
      .fit-badge.strong {background:#143b35;color:#8fe6cf;border:1px solid #2e6e60}
      .fit-badge.conditional {background:#40351e;color:#f4d68d;border:1px solid #76613a}
      .fit-badge.poor {background:#422532;color:#f4bac9;border:1px solid #7a485b}
      .fit-badge.unknown {background:#29374c;color:#c2d4ee;border:1px solid #526784}
      [data-testid="stMetric"] {background:#152238;border:1px solid #30415a;border-radius:12px;padding:14px}
      [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {color:#f1f5fb}
      [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stDateInput"] input {background:#17253a !important;color:#f1f5fb !important;caret-color:#77d8c0;-webkit-text-fill-color:#f1f5fb}
      [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="base-input"] {background:#17253a !important;border-color:#435875 !important}
      [data-baseweb="select"] > div {background:#17253a !important;color:#f1f5fb !important;border-color:#435875 !important}
      [data-baseweb="select"] span {color:#f1f5fb !important}
      [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"], [role="option"] {background:#17253a !important;color:#f1f5fb !important}
      [role="option"]:hover {background:#30445e !important}
      [data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {background:#1c2c43;color:#edf3fa;border-color:#435875;border-radius:9px}
      button[kind="primary"], button[kind="primaryFormSubmit"] {background:#72d5bc !important;color:#09221c !important;border-color:#72d5bc !important}
      button[kind="primary"] p, button[kind="primaryFormSubmit"] p {color:#09221c !important}
      a {color:#81d9cc}
      [data-testid="stAlert"] {background:#1b2a41 !important;border:1px solid #435875;border-radius:10px}
      [data-testid="stAlert"] p {color:#e7edf6}
      input::placeholder,textarea::placeholder {color:#a9b8cc !important;-webkit-text-fill-color:#a9b8cc}
      @media(max-width:700px) {[class*="st-key-intake_"] {padding:16px !important}.block-container {padding-left:1rem;padding-right:1rem}.detail-box {padding:12px}}
      </style>""", unsafe_allow_html=True)
    if "initialized" not in st.session_state:
        set_fields(blank_profile())
        st.session_state["initialized"] = True
    if "next_page" in st.session_state: st.session_state["page"] = st.session_state.pop("next_page")
    st.title("New Venture Fit Analysis")
    st.caption("Turn a venture profile into a focused funding-fit conversation.")
    st.warning("Synthetic demonstration · U.S. angel and VC funding · No live investor search")
    with st.sidebar:
        st.markdown("### Your workflow")
        st.radio("Step", ("Venture profile", "Confirm summary", "Funding fit results", "Saved assessments"), key="page")
        st.button("Load synthetic example", on_click=load_demo, key="load_demo", type="primary")
        st.button("Start a blank profile", on_click=start_blank, key="blank")
        st.caption("Evaluated assessments and email edits save in demo.db. Profiles save when evaluated; earlier form edits stay in this session. Keep demo.db to retain your work.")
    if st.session_state.get("notice"): st.success(st.session_state.pop("notice"))
    if st.session_state.get("load_error"): st.error(st.session_state.pop("load_error"))
    {"Venture profile": form, "Confirm summary": confirm, "Funding fit results": results, "Saved assessments": saved_assessments}[st.session_state.get("page", "Venture profile")]()


if __name__ == "__main__":
    main()
