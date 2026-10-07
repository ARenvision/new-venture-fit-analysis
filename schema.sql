-- New Venture Fit Analysis: local SQLite schema.
-- Enable foreign_keys on EVERY connection, not just initialization.
-- IDs and hashes are assigned by application code, never by research output.
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS organizations (
 organization_id TEXT PRIMARY KEY NOT NULL,
 canonical_name TEXT NOT NULL CHECK(length(trim(canonical_name)) > 0),
 organization_type TEXT NOT NULL CHECK(organization_type IN ('venture_capital','angel_group','growth_equity','other','unknown')),
 canonical_domain TEXT,
 aliases_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(aliases_json) AND json_type(aliases_json) = 'array'),
 created_at TEXT NOT NULL,
 UNIQUE(canonical_domain, organization_type)
);
CREATE TABLE IF NOT EXISTS investor_observations (
 observation_id TEXT PRIMARY KEY NOT NULL,
 organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
 researched_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL,
 schema_version TEXT NOT NULL,
 import_key TEXT NOT NULL UNIQUE,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json) = 'object'),
 UNIQUE(observation_id, organization_id)
);
CREATE INDEX IF NOT EXISTS ix_observations_org_date ON investor_observations(organization_id, researched_at DESC, recorded_at DESC);
CREATE TABLE IF NOT EXISTS ventures (
 venture_id TEXT PRIMARY KEY NOT NULL,
 working_name TEXT NOT NULL CHECK(length(trim(working_name)) > 0),
 is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK(is_synthetic IN (0,1)),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS venture_profiles (
 venture_profile_id TEXT PRIMARY KEY NOT NULL,
 venture_id TEXT NOT NULL REFERENCES ventures(venture_id),
 confirmed_at TEXT NOT NULL,
 schema_version TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json) = 'object'),
 UNIQUE(venture_profile_id, venture_id)
);
CREATE TABLE IF NOT EXISTS assessments (
 assessment_id TEXT PRIMARY KEY NOT NULL,
 venture_id TEXT NOT NULL REFERENCES ventures(venture_id),
 venture_profile_id TEXT NOT NULL,
 generated_at TEXT NOT NULL,
 methodology_version TEXT NOT NULL,
 pool_size INTEGER NOT NULL CHECK(pool_size >= 0),
 screened_count INTEGER NOT NULL CHECK(screened_count >= 0 AND screened_count <= pool_size),
 shortlisted_count INTEGER NOT NULL CHECK(shortlisted_count >= 0 AND shortlisted_count <= screened_count),
 coverage_json TEXT NOT NULL CHECK(json_valid(coverage_json) AND json_type(coverage_json) = 'object'),
 summary_json TEXT NOT NULL CHECK(json_valid(summary_json) AND json_type(summary_json) = 'object'),
 FOREIGN KEY(venture_profile_id, venture_id) REFERENCES venture_profiles(venture_profile_id, venture_id),
 UNIQUE(assessment_id, venture_id)
);
CREATE INDEX IF NOT EXISTS ix_assessments_venture_date ON assessments(venture_id, generated_at DESC);
CREATE TABLE IF NOT EXISTS assessment_results (
 result_id TEXT PRIMARY KEY NOT NULL,
 assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id),
 organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
 observation_id TEXT NOT NULL,
 classification TEXT NOT NULL CHECK(classification IN ('strong_fit','conditional_fit','poor_fit','insufficient_evidence')),
 evidence_quality TEXT NOT NULL CHECK(evidence_quality IN ('well_supported','partial','insufficient')),
 shortlisted INTEGER NOT NULL CHECK(shortlisted IN (0,1)),
 display_order INTEGER CHECK(display_order IS NULL OR display_order >= 1),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json) = 'object'),
 FOREIGN KEY(observation_id, organization_id) REFERENCES investor_observations(observation_id, organization_id),
 UNIQUE(assessment_id, organization_id),
 CHECK(shortlisted = 0 OR classification IN ('strong_fit','conditional_fit'))
);
CREATE TABLE IF NOT EXISTS outreach_events (
 event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT NOT NULL UNIQUE,
 venture_id TEXT NOT NULL REFERENCES ventures(venture_id),
 organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
 assessment_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('not_contacted','awaiting_response','positive_response','negative_response','follow_up_needed','no_response')),
 occurred_on TEXT,
 recorded_at TEXT NOT NULL,
 note TEXT CHECK(note IS NULL OR length(note) <= 2000),
 FOREIGN KEY(assessment_id, venture_id) REFERENCES assessments(assessment_id, venture_id)
);
CREATE INDEX IF NOT EXISTS ix_outreach_pair ON outreach_events(venture_id, organization_id, event_sequence DESC);
-- Most recently RECORDED status, independent of assessment version.
CREATE VIEW IF NOT EXISTS latest_outreach_status AS
 SELECT e.* FROM outreach_events e
 WHERE e.event_sequence = (
  SELECT MAX(x.event_sequence) FROM outreach_events x
  WHERE x.venture_id=e.venture_id AND x.organization_id=e.organization_id
 );
-- Dated records are immutable. Correct by appending a new version/event.
CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON investor_observations BEGIN SELECT RAISE(ABORT,'Append a new investor observation'); END;
CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON investor_observations BEGIN SELECT RAISE(ABORT,'Investor history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS profiles_no_update BEFORE UPDATE ON venture_profiles BEGIN SELECT RAISE(ABORT,'Append a new venture profile'); END;
CREATE TRIGGER IF NOT EXISTS profiles_no_delete BEFORE DELETE ON venture_profiles BEGIN SELECT RAISE(ABORT,'Venture profile history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS assessments_no_update BEFORE UPDATE ON assessments BEGIN SELECT RAISE(ABORT,'Create a new assessment'); END;
CREATE TRIGGER IF NOT EXISTS assessments_no_delete BEFORE DELETE ON assessments BEGIN SELECT RAISE(ABORT,'Assessment history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON assessment_results BEGIN SELECT RAISE(ABORT,'Create a new assessment result'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON assessment_results BEGIN SELECT RAISE(ABORT,'Assessment results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS outreach_no_update BEFORE UPDATE ON outreach_events BEGIN SELECT RAISE(ABORT,'Append a new outreach event'); END;
CREATE TRIGGER IF NOT EXISTS outreach_no_delete BEFORE DELETE ON outreach_events BEGIN SELECT RAISE(ABORT,'Outreach history is immutable'); END;
COMMIT;
