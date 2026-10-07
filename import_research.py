"""Validate and append investor research. No network access or outreach.

Run python import_research.py --help. Public API: load_research, validate_research,
import_research. Validation checks declared provenance, not source truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 5 * 1024 * 1024


class ResearchError(ValueError):
    """Actionable validation or identity issue; the batch is not imported."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ResearchError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ResearchError(f"Non-finite JSON number: {value}")


def load_research(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ResearchError("Research file exceeds the 5 MiB limit; split into smaller batches.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ResearchError(f"Invalid UTF-8 JSON: {exc}") from exc


def _stamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResearchError("researched_at requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _name(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _domain(value):
    if value is None:
        return None
    if value != value.lower() or len(value) > 253 or "." not in value:
        raise ResearchError("canonical_domain must be a lowercase hostname, or null.")
    labels = value.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
        raise ResearchError("canonical_domain contains an invalid hostname label.")
    return value.removeprefix("www.")


def _web(value, where):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ResearchError(f"{where}: invalid URL port") from exc
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or re.search(r"\s", value):
        raise ResearchError(f"{where}: expected an HTTP(S) URL without credentials or spaces")
    host = parsed.hostname.casefold()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        raise ResearchError(f"{where}: LinkedIn sourcing is outside this project")
    return host


def validate_research(data, *, allow_demo=False, now=None, schema_path=None):
    """Validate all records before opening a database; return the original data."""
    try:
        canonical(data)
    except (ValueError, TypeError) as exc:
        raise ResearchError(f"Research must contain finite JSON values: {exc}") from exc
    schema = json.loads(Path(schema_path or ROOT / "research.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data))
    if errors:
        details = [f"{'/'.join(map(str, e.absolute_path)) or 'root'}: {e.message}" for e in errors[:8]]
        raise ResearchError("Research format errors:\n" + "\n".join(details))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ResearchError("Validation clock requires a timezone.")
    researched = _stamp(data["researched_at"])
    if researched > now:
        raise ResearchError("researched_at is in the future")
    demo = data["data_scope"] == "synthetic_demo"
    if demo and not allow_demo:
        raise ResearchError("Synthetic demonstration data requires --demo and a separate demo database.")
    names, domains = set(), set()
    for index, org in enumerate(data["organizations"], 1):
        prefix = f"Organization {index} ({org['name']})"
        if not org["name"].strip():
            raise ResearchError(f"{prefix}: name is blank")
        org_names = {_name(x) for x in [org["name"], *org["aliases"]]}
        if "" in org_names or names.intersection(org_names):
            raise ResearchError(f"{prefix}: blank or overlapping organization names/aliases in batch")
        names.update(org_names)
        domain = _domain(org["canonical_domain"])
        if domain and domain in domains:
            raise ResearchError(f"{prefix}: shared domain requires identity review; use separate batches")
        if domain:
            domains.add(domain)

        def nonblank(value, path=""):
            if isinstance(value, str) and not value.strip():
                raise ResearchError(f"{prefix}/{path}: whitespace-only text")
            if isinstance(value, dict):
                for key, child in value.items():
                    nonblank(child, f"{path}/{key}")
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    nonblank(child, f"{path}/{i}")
        nonblank(org)
        sources = {s["source_id"]: s for s in org["sources"]}
        routes = {r["route_id"]: r for r in org["approach_routes"]}
        if len(sources) != len(org["sources"]) or len(routes) != len(org["approach_routes"]):
            raise ResearchError(f"{prefix}: duplicate source or route IDs")
        for source in sources.values():
            _web(source["url"], f"{prefix}/{source['source_id']}")
            checked = date.fromisoformat(source["checked_on"])
            if checked > researched.date():
                raise ResearchError(f"{prefix}: source access date is after researched_at (UTC)")
            if source["published_on"] and date.fromisoformat(source["published_on"]) > checked:
                raise ResearchError(f"{prefix}: source publication is after its access date")
            if source["redistribution_status"] != "unknown" and not source["rights_note"]:
                raise ResearchError(f"{prefix}: declared source rights require a rights_note")

        def references(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("source_ids", "route_ids"):
                        target = sources if key == "source_ids" else routes
                        if len(child) != len(set(child)) or any(x not in target for x in child):
                            raise ResearchError(f"{prefix}: unresolved or repeated {key}: {child}")
                    else:
                        references(child)
            elif isinstance(value, list):
                for child in value:
                    references(child)
        references(org)

        def official(ids, where):
            if not any(sources[x]["source_type"] == "official" for x in ids):
                raise ResearchError(f"{prefix}: {where} requires at least one declared official source")
        for contact in org["contacts"]:
            official(contact["source_ids"], "contact")
        for route in routes.values():
            official(route["source_ids"], "approach route")
            if route["route_type"] in ("pitch_form", "contact_page", "homepage"):
                _web(route["value"], f"{prefix}/route")
            elif route["route_type"] == "business_email":
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", route["value"]):
                    raise ResearchError(f"{prefix}: invalid business email")
            elif not re.fullmatch(r"[+()0-9 .-]+(?:\s*(?:ext\.?|x)\s*\d+)?", route["value"], re.I) or len(re.sub(r"\D", "", route["value"])) < 7:
                raise ResearchError(f"{prefix}: invalid company phone")
        check = org["check_size"]
        lo, hi, typical = (check[k] for k in ("minimum_usd", "maximum_usd", "typical_usd"))
        if lo is not None and hi is not None and lo > hi:
            raise ResearchError(f"{prefix}: minimum check exceeds maximum")
        if typical is not None and ((lo is not None and typical < lo) or (hi is not None and typical > hi)):
            raise ResearchError(f"{prefix}: typical check falls outside the published range")
        if org["portfolio_conflicts"]["review_status"] == "not_reviewed" and org["portfolio_conflicts"]["items"]:
            raise ResearchError(f"{prefix}: unreviewed portfolio cannot contain reviewed items")
        if org["scope_status"] == "in_scope":
            if org["organization_type"] not in ("venture_capital", "angel_group"):
                raise ResearchError(f"{prefix}: only VC/angel organizations can be in scope")
            if not org["criteria"]["geography"]["findings"]:
                raise ResearchError(f"{prefix}: in-scope classification needs sourced geography findings")
        if demo and not any("synthetic" in x.casefold() for x in org["research_limitations"]):
            raise ResearchError(f"{prefix}: synthetic records must explicitly disclose synthetic evidence")
    return data


def _resolve(conn, org):
    domain = _domain(org["canonical_domain"])
    names = {_name(x) for x in [org["name"], *org["aliases"]]}
    matches = []
    for row in conn.execute("SELECT organization_id, canonical_name, organization_type, canonical_domain, aliases_json FROM organizations"):
        existing_names = {_name(x) for x in [row[1], *json.loads(row[4])]}
        if (domain and _domain(row[3]) == domain) or names.intersection(existing_names):
            matches.append((row, existing_names))
    if len(matches) > 1:
        raise ResearchError(f"{org['name']}: ambiguous identity; review names/domains before importing")
    if matches:
        row, existing_names = matches[0]
        if row[2] != org["organization_type"] or not names.intersection(existing_names) or (domain and row[3] and domain != _domain(row[3])):
            raise ResearchError(f"{org['name']}: name, domain or organization type conflicts with saved identity; review required")
        # Preserve canonical identity. New aliases remain in the dated observation.
        return row[0], False
    oid = str(uuid.uuid4())
    conn.execute("INSERT INTO organizations VALUES (?, ?, ?, ?, ?, ?)", (oid, org["name"].strip(), org["organization_type"], domain, canonical(org["aliases"]), _utc(datetime.now(timezone.utc))))
    return oid, True


def import_research(data, db_path, *, allow_demo=False, now=None):
    """Atomic batch import. Exact profile/date repeats are no-ops; revisions append."""
    validate_research(data, allow_demo=allow_demo, now=now)
    db_path = Path(db_path)
    if not db_path.parent.exists():
        raise ResearchError("Database parent directory does not exist")
    recorded = _utc(now or datetime.now(timezone.utc))
    researched = _utc(_stamp(data["researched_at"]))
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        expected = {"organizations", "investor_observations", "ventures", "venture_profiles", "assessments", "assessment_results", "outreach_events"}
        if tables and tables != expected:
            raise ResearchError("Existing database is not the standalone venture-fit database; choose a new filename.")
        if tables:
            definitions = sqlite3.connect(":memory:")
            try:
                definitions.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
                for table in expected:
                    if conn.execute(f"PRAGMA table_info({table})").fetchall() != definitions.execute(f"PRAGMA table_info({table})").fetchall():
                        raise ResearchError("Existing database has an incompatible schema; use a new filename and review migration separately.")
            finally:
                definitions.close()
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        existing_scopes = {row[0] for row in conn.execute("SELECT DISTINCT json_extract(payload_json, '$.data_scope') FROM investor_observations")}
        if existing_scopes - {data["data_scope"]}:
            raise ResearchError("Do not mix synthetic and real research in one database; choose a separate database.")
        results = []
        for org in data["organizations"]:
            oid, created = _resolve(conn, org)
            payload = {"data_scope": data["data_scope"], "organization": org}
            key = hashlib.sha256(canonical({"organization_id": oid, "schema_version": data["schema_version"], "researched_at": researched, "payload": payload}).encode("utf-8")).hexdigest()
            previous = conn.execute("SELECT observation_id FROM investor_observations WHERE import_key=?", (key,)).fetchone()
            if previous:
                observation_id, status = previous[0], "duplicate_skipped"
            else:
                observation_id, status = str(uuid.uuid4()), "observation_added"
                conn.execute("INSERT INTO investor_observations VALUES (?, ?, ?, ?, ?, ?, ?)", (observation_id, oid, researched, recorded, data["schema_version"], key, canonical(payload)))
            results.append({"name": org["name"], "organization_id": oid, "observation_id": observation_id, "new_organization": created, "status": status})
        conn.commit()
        return {"data_scope": data["data_scope"], "added": sum(r["status"] == "observation_added" for r in results), "duplicates_skipped": sum(r["status"] == "duplicate_skipped" for r in results), "results": results}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Research JSON file")
    parser.add_argument("--db", type=Path, help="Default: demo.db with --demo; otherwise venturefit.db beside this script")
    parser.add_argument("--demo", action="store_true", help="Permit explicitly labeled synthetic research")
    parser.add_argument("--validate-only", action="store_true", help="Check research without opening or creating a database; no identity check")
    args = parser.parse_args(argv)
    try:
        data = load_research(args.file)
        validate_research(data, allow_demo=args.demo)
        if args.demo and data["data_scope"] != "synthetic_demo":
            raise ResearchError("--demo expects data_scope synthetic_demo; omit it for real research")
        if args.validate_only:
            result = {"status": "valid", "organizations": len(data["organizations"]), "data_scope": data["data_scope"], "database_written": False}
        else:
            result = import_research(data, args.db or ROOT / ("demo.db" if args.demo else "venturefit.db"), allow_demo=args.demo)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ResearchError, OSError, sqlite3.Error, ValueError, RecursionError) as exc:
        print(f"Import failed: {exc}\nNo batch records were committed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
