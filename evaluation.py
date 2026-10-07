"""Explainable matching of confirmed fields to evidence-linked reviewed rules.

Rules are curated data, never extracted by keyword guessing. Each rule set is
bound to the exact research profile hash. No AI service or network is used.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from import_research import ResearchError, canonical, validate_research

METHOD = "reviewed_rules_1.0"
FACTORS = ("stage", "sector", "geography", "amount", "traction", "restrictions")
LABELS = {"strong_fit": "Strong Fit", "conditional_fit": "Conditional Fit", "poor_fit": "Poor Fit", "insufficient_evidence": "Insufficient Evidence"}
PROGRESS = ("Unknown", "Idea only", "Building a prototype", "Working prototype", "Product in pilots", "Paying customers", "Other")
STAGES = ("unknown", "pre_seed", "seed", "series_a", "later")
SECTORS = ("unknown", "b2b_software", "consumer_software", "healthtech", "hardware", "other")
RULE_FIELDS = {
    "stage": {"funding_stage", "progress"},
    "sector": {"sector"},
    "geography": {"operating_country", "operating_state"},
    "traction": {"paying_customers", "monthly_revenue_usd", "unpaid_pilots"},
    "restrictions": {"all_founders_full_time", "equity_willing", "relocation_willing"},
}
TEXT_FIELDS = ("name", "website", "operating_city", "operating_state", "operating_country", "formation", "product", "customer", "problem", "ai_role", "advantage", "progress", "demand_signal", "team_experience", "raise_timing", "funding_uses", "milestone", "milestone_timeframe", "previous_funding", "constraints")
NUM_FIELDS = ("paying_customers", "unpaid_pilots", "active_users", "monthly_revenue_usd", "founder_count", "target_min_usd", "target_max_usd")
BOOL_FIELDS = ("all_founders_full_time", "equity_willing", "relocation_willing")
PROFILE_KEYS = set(TEXT_FIELDS + NUM_FIELDS + BOOL_FIELDS + ("schema_version", "is_synthetic", "funding_stage", "sector", "preferences", "confirmed"))


def profile_hash(org):
    return hashlib.sha256(canonical(org).encode("utf-8")).hexdigest()


def validate_profile(profile, *, require_confirmed=True):
    if set(profile) != PROFILE_KEYS or profile["schema_version"] != "1.0":
        raise ResearchError("Venture profile has missing or unsupported fields.")
    if not all(isinstance(profile[x], str) for x in TEXT_FIELDS):
        raise ResearchError("Venture text fields must be text; use an empty answer for unknown.")
    if not profile["name"].strip() or not profile["product"].strip():
        raise ResearchError("Enter a working venture name and what you are building.")
    if any(len(profile[x]) > 5000 for x in TEXT_FIELDS):
        raise ResearchError("Keep each answer under 5,000 characters.")
    if profile["funding_stage"] not in STAGES or profile["sector"] not in SECTORS or profile["progress"] not in PROGRESS:
        raise ResearchError("Choose a supported stage, sector and progress option.")
    for field in NUM_FIELDS:
        value = profile[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ResearchError(f"{field}: use a nonnegative number or unknown.")
        if value is not None and field in ("paying_customers", "unpaid_pilots", "active_users", "founder_count") and value != int(value):
            raise ResearchError(f"{field}: use a whole number.")
    for field in BOOL_FIELDS:
        if profile[field] is not None and type(profile[field]) is not bool:
            raise ResearchError(f"{field}: use Yes, No or Unknown.")
    if type(profile["confirmed"]) is not bool or type(profile["is_synthetic"]) is not bool:
        raise ResearchError("Confirmation and synthetic flags must be booleans.")
    if require_confirmed and not profile["confirmed"]:
        raise ResearchError("Review and confirm the venture summary before evaluating.")
    if not isinstance(profile["preferences"], list) or not set(profile["preferences"]).issubset({"Angel investors", "Venture capital", "Accelerators", "Grants", "Unsure / Open to guidance"}):
        raise ResearchError("Unsupported funding preference.")
    low, high = profile["target_min_usd"], profile["target_max_usd"]
    if high is not None and (low is None or high < low):
        raise ResearchError("Funding target maximum must be at least the minimum.")
    if low == 0:
        raise ResearchError("Funding target must be positive, or blank for undecided.")
    if profile["progress"] == "Paying customers" and profile["paying_customers"] == 0:
        raise ResearchError("Paying-customer progress conflicts with zero paying customers. Correct one before confirming.")
    return profile


def number_answer(value, label, *, whole=False):
    value = value.strip().replace(",", "").removeprefix("$")
    if not value or value.casefold() in ("unknown", "undecided", "not yet"):
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ResearchError(f"{label}: enter digits (for example 750000), or leave blank.") from exc
    if not math.isfinite(result) or result < 0 or (whole and result != int(result)):
        raise ResearchError(f"{label}: enter a nonnegative {'whole ' if whole else ''}number, or leave blank.")
    return int(result) if whole else result


def latest_research(db_path, *, scope="synthetic_demo"):
    """Read-only database access; never initializes an unrelated database."""
    path = Path(db_path).resolve()
    if not path.exists():
        return []
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        rows = conn.execute("""SELECT organization_id, observation_id, researched_at, payload_json
          FROM investor_observations ORDER BY researched_at DESC, recorded_at DESC, rowid DESC""").fetchall()
        selected, seen = [], set()
        for oid, obsid, researched, payload_text in rows:
            if oid in seen:
                continue
            seen.add(oid)
            payload = json.loads(payload_text)
            if payload.get("data_scope") != scope:
                raise ResearchError("This database contains a different research scope.")
            selected.append({"organization_id": oid, "observation_id": obsid, "researched_at": researched, "organization": payload["organization"]})
        return sorted(selected, key=lambda r: r["organization"]["name"])
    finally:
        conn.close()


def _reviewed_rules(org, rules):
    if not rules:
        raise ResearchError("No reviewed matching rules are available for this research profile.")
    expected = {"organization_domain", "profile_sha256", "review_status", "criteria", "check_size_reviewed"}
    if set(rules) != expected or rules["review_status"] != "reviewed" or rules["profile_sha256"] != profile_hash(org) or rules["organization_domain"] != org["canonical_domain"] or type(rules["check_size_reviewed"]) is not bool:
        raise ResearchError("Matching rules are unreviewed or do not match the current research. Review the latest evidence.")
    if not isinstance(rules["criteria"], list):
        raise ResearchError("Matching criteria must be a list.")
    for rule in rules["criteria"]:
        if set(rule) != {"factor", "field", "operator", "value", "finding_index"}:
            raise ResearchError("Unsupported matching-rule fields.")
        factor, field, op = rule["factor"], rule["field"], rule["operator"]
        if factor not in RULE_FIELDS or field not in RULE_FIELDS[factor] or op not in ("one_of", "at_least", "equals"):
            raise ResearchError("Unsupported factor, field or operator.")
        i = rule["finding_index"]
        findings = org["criteria"][factor]["findings"]
        if type(i) is not int or i < 0 or i >= len(findings):
            raise ResearchError("Matching rule points at a missing research finding.")
        value = rule["value"]
        if op == "at_least" and (field not in ("paying_customers", "monthly_revenue_usd", "unpaid_pilots") or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ResearchError("Minimum threshold requires a nonnegative numeric field/value.")
        if op == "one_of" and (field in BOOL_FIELDS or field in NUM_FIELDS or not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value)):
            raise ResearchError("Allowed values must be a nonempty list for a category field.")
        if op == "equals" and (field not in BOOL_FIELDS or type(value) is not bool):
            raise ResearchError("Boolean rule requires a boolean value.")
    return rules


def _matches(value, rule):
    if value is None or value == "unknown" or value == "Unknown" or value == "":
        return None
    if rule["operator"] == "one_of":
        return value in rule["value"]
    if rule["operator"] == "at_least":
        return value >= rule["value"]
    return value == rule["value"]


def evaluate(profile, record, rules=None):
    validate_profile(profile)
    org = record["organization"]
    # Revalidate research before using it, including reference resolution.
    validate_research({"schema_version": "1.0", "data_scope": "synthetic_demo" if profile["is_synthetic"] else "real_investor_research", "researched_at": record["researched_at"], "organizations": [org]}, allow_demo=profile["is_synthetic"])
    result = {"organization_id": record["organization_id"], "observation_id": record["observation_id"], "name": org["name"], "classification": "insufficient_evidence", "evidence_quality": "insufficient", "reasons": [], "concerns": [], "unknowns": [], "factors": [], "contribution": None, "shortlisted": False, "research_date": record["researched_at"], "organization": org, "method": METHOD}
    if org["scope_status"] == "out_of_scope":
        result.update(classification="poor_fit", evidence_quality="partial")
        result["concerns"].append(f"Outside this prototype's angel/VC scope: {org['scope_reason']}")
        result["next_step"] = "Exclude from this shortlist; outside scope is not a claim that the firm would reject the venture."
        return result
    if org["scope_status"] != "in_scope":
        result["unknowns"].append("U.S. angel/VC scope has not been established.")
    try:
        rules = _reviewed_rules(org, rules)
    except ResearchError as exc:
        result["unknowns"].append(str(exc))
        result["factors"] = [{"factor": f, "entries": [{"status": "unknown", "rule_type": "unknown", "evidence_status": "unknown", "description": "No current reviewed rule available.", "source_ids": []}]} for f in FACTORS]
        result["next_step"] = "Review and normalize the investor's evidence before recommending an approach."
        return result
    hard_mismatch, uncertain = False, False
    covered = set()
    source_ids = {s["source_id"] for s in org["sources"]}
    for factor in FACTORS:
        entries = []
        for rule in rules["criteria"]:
            if rule["factor"] != factor:
                continue
            finding = org["criteria"][factor]["findings"][rule["finding_index"]]
            if not set(finding["source_ids"]).issubset(source_ids):
                raise ResearchError("Rule citation is missing from the research profile.")
            match = _matches(profile[rule["field"]], rule)
            kind = finding["rule_type"]
            inferred = finding["evidence_status"] == "inferred" or kind in ("inference", "portfolio_example")
            status = "unknown" if match is None else "aligned" if match else "mismatch"
            description = f"{finding['statement']} Founder value: {profile[rule['field']] if match is not None else 'unknown'}."
            entry = {"status": status, "rule_type": kind, "evidence_status": finding["evidence_status"], "description": description, "source_ids": finding["source_ids"]}
            entries.append(entry)
            if match is False and kind == "hard_requirement":
                hard_mismatch = True
                result["concerns"].append(description)
            elif match is not True or inferred:
                uncertain = True
                (result["unknowns"] if match is None else result["concerns"]).append(description)
            else:
                result["reasons"].append(description)
                covered.add(factor)
        if factor == "amount":
            entry, contribution = _amount(profile, org, rules["check_size_reviewed"])
            entries.append(entry)
            result["contribution"] = contribution
            if entry["status"] == "aligned":
                covered.add(factor)
                result["reasons"].append(entry["description"])
            else:
                uncertain = True
                result["unknowns"].append(entry["description"])
        if not entries:
            uncertain = True
            text = f"{factor.capitalize()}: no reviewed rule is available; not assumed favorable."
            result["unknowns"].append(text)
            entries.append({"status": "unknown", "rule_type": "unknown", "evidence_status": "unknown", "description": text, "source_ids": []})
        for issue in org["criteria"][factor]["conflicts"]:
            uncertain = True
            result["concerns"].append(f"Conflicting {factor} evidence: {issue}")
        for unknown in org["criteria"][factor]["unknowns"]:
            uncertain = True
            result["unknowns"].append(f"{factor.capitalize()}: {unknown}")
        result["factors"].append({"factor": factor, "entries": entries})
    # Funding route/equity preferences can block an otherwise suitable firm.
    prefs = profile["preferences"]
    route = "Angel investors" if org["organization_type"] == "angel_group" else "Venture capital"
    if profile["equity_willing"] is False or (prefs and "Unsure / Open to guidance" not in prefs and route not in prefs):
        hard_mismatch = True
        result["concerns"].append("Founder funding preferences exclude this equity funding route.")
    elif profile["equity_willing"] is None or not prefs:
        uncertain = True
        result["unknowns"].append("Founder equity willingness or funding-route preference is undecided.")
    if org["funding_status"]["status"] == "not_currently_investing":
        hard_mismatch = True
        result["concerns"].append("Research reports that the organization is not currently investing.")
    elif org["funding_status"]["status"] == "unknown":
        uncertain = True
        result["unknowns"].append("Current investing activity is unknown.")
    if org["scope_status"] != "in_scope":
        uncertain = True
    if profile["constraints"].strip():
        uncertain = True
        result["unknowns"].append("Additional free-text constraints need human review; they were not silently interpreted.")
    if any(i["assessment"] == "confirmed_restriction" for i in org["portfolio_conflicts"]["items"]):
        hard_mismatch = True
        result["concerns"].append("Research reports a portfolio restriction; review it before any approach.")
    elif org["portfolio_conflicts"]["review_status"] != "reviewed" or org["portfolio_conflicts"]["items"]:
        uncertain = True
        result["unknowns"].append("Portfolio overlap is unreviewed, partial or requires follow-up.")
    if org["research_limitations"] and not profile["is_synthetic"]:
        uncertain = True
        result["unknowns"].extend(org["research_limitations"])
    if hard_mismatch:
        classification = "poor_fit"
    elif profile["funding_stage"] == "unknown" or not {"stage", "sector", "geography"}.issubset(covered):
        classification = "insufficient_evidence"
    elif uncertain:
        classification = "conditional_fit"
    else:
        classification = "strong_fit"
    result.update(classification=classification, evidence_quality="well_supported" if len(covered) == 6 and not uncertain else "partial" if covered else "insufficient", shortlisted=classification in ("strong_fit", "conditional_fit"))
    result["next_step"] = {"strong_fit": "Review the evidence and approach route, then personalize your introduction.", "conditional_fit": "Resolve the listed conditions before spending time on an approach.", "poor_fit": "Deprioritize this organization for the current profile; inspect the mismatch.", "insufficient_evidence": "Clarify essential founder fields or investor criteria before shortlisting."}[classification]
    return result


def _amount(profile, org, reviewed):
    check, low, high = org["check_size"], profile["target_min_usd"], profile["target_max_usd"]
    entry = {"status": "unknown", "rule_type": "individual_check", "evidence_status": "unknown", "description": "Funding target or reviewed individual check size is unknown.", "source_ids": check["source_ids"]}
    if not reviewed or low is None or not check["source_ids"]:
        return entry, None
    high = high if high is not None else low
    chosen = check["typical_usd"]
    basis = "published typical/first check"
    if chosen is None:
        if check["minimum_usd"] is None:
            return entry, None
        chosen, basis = check["minimum_usd"], "published minimum; illustrative only"
    if chosen <= 0 or chosen > low:
        entry["description"] = "Published check is zero or exceeds the lower funding target; suitable contribution needs review. No check-size mismatch is treated as an automatic rejection."
        return entry, None
    entry.update(status="aligned", evidence_status="verified", description=f"Illustrative ${chosen:,.0f} individual check ({basis}) toward a ${low:,.0f}" + (f"–${high:,.0f}" if high != low else "") + " round; not a funding commitment.")
    return entry, {"amount_usd": chosen, "percentage_min": chosen / high * 100, "percentage_max": chosen / low * 100, "remaining_min_usd": low - chosen, "remaining_max_usd": high - chosen, "basis": basis}


def evaluate_pool(profile, records, rulebook):
    validate_profile(profile)
    scope = "synthetic_demo" if profile["is_synthetic"] else "real_investor_research"
    if rulebook.get("data_scope") != scope or rulebook.get("methodology_version") != METHOD:
        raise ResearchError("Matching-rule scope or methodology does not match this venture.")
    rows = [evaluate(profile, record, rulebook.get("organizations", {}).get(record["organization"]["canonical_domain"])) for record in records]
    order = {"strong_fit": 0, "conditional_fit": 1, "insufficient_evidence": 2, "poor_fit": 3}
    rows.sort(key=lambda r: (order[r["classification"]], r["name"]))
    return {"venture": profile, "method": METHOD, "generated_at": datetime.now(timezone.utc).isoformat(), "coverage": {"pool_size": len(records), "screened": len(rows), "shortlisted": sum(r["shortlisted"] for r in rows), "out_of_scope": sum(r["organization"]["scope_status"] == "out_of_scope" for r in rows)}, "results": rows}


def email_draft(profile, result):
    org = result["organization"]
    sector = next((x for x in org["criteria"]["sector"]["findings"] if x["evidence_status"] == "verified" and x["rule_type"] in ("hard_requirement", "preference", "typical_profile")), None)
    reason = f"Your published focus states: {sector['statement']}" if sector else "[Add a verified reason this organization is relevant.]"
    target = f"${profile['target_min_usd']:,.0f}" if profile["target_min_usd"] is not None else "[funding amount]"
    if profile["target_max_usd"] is not None and profile["target_max_usd"] != profile["target_min_usd"]:
        target += f"–${profile['target_max_usd']:,.0f}"
    return f"Subject: {profile['name']} — introduction\n\nHello [recipient name],\n\n[Optional referral or connection.]\n\nWe are building {profile['product']} for {profile['customer'] or '[target customer]'}. {reason}\n\nWe are seeking {target} to {profile['funding_uses'] or '[intended use of funds]'}. [Add a concise confirmed traction statement.]\n\nWould this be appropriate for your current investment focus?\n\n[Optional deck link]\n[Founder name and signature]"
