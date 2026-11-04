"""Additive schema for project access, immutable documents and durable jobs."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bid_agent.core.settings import DB_PATH


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid4().hex}'


@contextmanager
def transaction(db_path: Path = DB_PATH, *, immediate: bool = False):
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        if immediate:
            connection.execute('BEGIN IMMEDIATE')
        with connection:
            yield connection
    finally:
        connection.close()


def init_platform_schema(db_path: Path = DB_PATH) -> None:
    with transaction(db_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS platform_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_sessions_expiry ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
            PRIMARY KEY(project_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL, kind TEXT NOT NULL,
            parent_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_documents_project ON documents(project_id);
        CREATE TABLE IF NOT EXISTS document_versions (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version INTEGER NOT NULL, file_name TEXT NOT NULL, media_type TEXT NOT NULL,
            object_key TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(document_id,version), UNIQUE(document_id,sha256)
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'parse', status TEXT NOT NULL,
            options_json TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
            available_at REAL NOT NULL DEFAULT 0, lease_token TEXT, lease_expires_at REAL,
            progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT 'queued',
            error_code TEXT, error_message TEXT, retryable INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(project_id,idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS ix_jobs_recovery ON jobs(status,lease_expires_at,available_at);
        CREATE INDEX IF NOT EXISTS ix_jobs_project ON jobs(project_id,created_at);
        CREATE TABLE IF NOT EXISTS parsed_documents (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
            document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            parser_version TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_job_events_cursor ON job_events(job_id,sequence);
        CREATE TABLE IF NOT EXISTS outbox_events (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending', available_at REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_expires_at REAL,
            last_error TEXT, created_at TEXT NOT NULL, published_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_outbox_delivery ON outbox_events(status,available_at,lease_expires_at);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(1,?)', (now(),))
        # B07 draft: structured requirements with evidence refs.
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS requirement_items (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            job_id TEXT,
            category TEXT NOT NULL,
            field_key TEXT,
            title TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            normalized_value TEXT,
            confidence REAL NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'draft',
            source_refs_json TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_requirements_version
            ON requirement_items(document_version_id, category, created_at);
        CREATE INDEX IF NOT EXISTS ix_requirements_project
            ON requirement_items(project_id, review_status);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(2,?)', (now(),))
        # Stage gates, bid versions, compliance runs, export artifacts.
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS project_stages (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','passed','skipped')),
            reviewer_id TEXT REFERENCES users(id),
            notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, stage)
        );
        CREATE TABLE IF NOT EXISTS bid_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_version_id TEXT REFERENCES document_versions(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            outline_markdown TEXT NOT NULL,
            outline_json TEXT NOT NULL,
            score_coverage_json TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_bid_versions_project
            ON bid_versions(project_id, created_at);
        CREATE TABLE IF NOT EXISTS bid_sections (
            id TEXT PRIMARY KEY,
            bid_version_id TEXT NOT NULL REFERENCES bid_versions(id) ON DELETE CASCADE,
            section_key TEXT NOT NULL,
            title TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            body_markdown TEXT NOT NULL DEFAULT '',
            UNIQUE(bid_version_id, section_key)
        );
        CREATE INDEX IF NOT EXISTS ix_bid_sections_version
            ON bid_sections(bid_version_id, sort_order);
        CREATE TABLE IF NOT EXISTS compliance_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            bid_version_id TEXT REFERENCES bid_versions(id) ON DELETE SET NULL,
            document_version_id TEXT REFERENCES document_versions(id) ON DELETE SET NULL,
            checker_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            summary_json TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_compliance_runs_project
            ON compliance_runs(project_id, created_at);
        CREATE TABLE IF NOT EXISTS compliance_findings (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES compliance_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            check_name TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('info','low','medium','high','critical')),
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            requirement_item_id TEXT,
            section_key TEXT,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            decision_status TEXT NOT NULL DEFAULT 'open'
                CHECK(decision_status IN ('open','accepted','waived','fixed')),
            decision_notes TEXT NOT NULL DEFAULT '',
            decided_by TEXT REFERENCES users(id),
            decided_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_compliance_findings_run
            ON compliance_findings(run_id, severity);
        CREATE INDEX IF NOT EXISTS ix_compliance_findings_project
            ON compliance_findings(project_id, decision_status);
        CREATE TABLE IF NOT EXISTS export_artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            bid_version_id TEXT NOT NULL REFERENCES bid_versions(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'docx',
            file_name TEXT NOT NULL,
            object_key TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            force_skip_gate INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_export_artifacts_project
            ON export_artifacts(project_id, created_at);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(3,?)', (now(),))
        # B11 draft: section body edit audit columns on bid_sections.
        _ensure_column(conn, 'bid_sections', 'updated_at', 'TEXT')
        _ensure_column(conn, 'bid_sections', 'updated_by', 'TEXT')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(4,?)', (now(),))
        # B13 draft: requirement → section response matrix and missing materials.
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS requirement_responses (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            bid_version_id TEXT NOT NULL REFERENCES bid_versions(id) ON DELETE CASCADE,
            requirement_item_id TEXT NOT NULL REFERENCES requirement_items(id) ON DELETE CASCADE,
            section_id TEXT REFERENCES bid_sections(id) ON DELETE SET NULL,
            response_status TEXT NOT NULL DEFAULT 'uncovered'
                CHECK(response_status IN (
                    'uncovered','mapped','drafted','responded','waived','missing_material'
                )),
            is_mandatory INTEGER NOT NULL DEFAULT 0,
            response_summary TEXT NOT NULL DEFAULT '',
            missing_materials_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_by TEXT REFERENCES users(id),
            updated_at TEXT NOT NULL,
            UNIQUE(bid_version_id, requirement_item_id)
        );
        CREATE INDEX IF NOT EXISTS ix_requirement_responses_bid
            ON requirement_responses(bid_version_id, response_status);
        CREATE INDEX IF NOT EXISTS ix_requirement_responses_project
            ON requirement_responses(project_id, is_mandatory);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(5,?)', (now(),))
        # B15 draft: review decision history, run approval, audit trail.
        _ensure_column(conn, 'compliance_runs', 'approval_status', "TEXT NOT NULL DEFAULT 'pending'")
        _ensure_column(conn, 'compliance_runs', 'approved_by', 'TEXT')
        _ensure_column(conn, 'compliance_runs', 'approved_at', 'TEXT')
        _ensure_column(conn, 'compliance_runs', 'approval_notes', "TEXT NOT NULL DEFAULT ''")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS compliance_decision_events (
            id TEXT PRIMARY KEY,
            finding_id TEXT NOT NULL REFERENCES compliance_findings(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES compliance_runs(id) ON DELETE CASCADE,
            from_status TEXT,
            to_status TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_compliance_decision_events_finding
            ON compliance_decision_events(finding_id, created_at);
        CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_audit_logs_project
            ON audit_logs(project_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_audit_logs_object
            ON audit_logs(object_type, object_id, created_at);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(6,?)', (now(),))
        # B09 draft: enterprise assets with immutable attachment versions and project links.
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS enterprise_assets (
            id TEXT PRIMARY KEY,
            organization_key TEXT NOT NULL DEFAULT 'default',
            category TEXT NOT NULL CHECK(category IN (
                'qualification','personnel','financial','performance','case','template','other'
            )),
            title TEXT NOT NULL,
            subject_name TEXT NOT NULL DEFAULT '',
            certificate_no TEXT NOT NULL DEFAULT '',
            issuer TEXT NOT NULL DEFAULT '',
            issued_on TEXT,
            expires_on TEXT,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_review','active','expired','disabled')),
            review_notes TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_by TEXT REFERENCES users(id),
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_enterprise_assets_org_status
            ON enterprise_assets(organization_key, status, category);
        CREATE INDEX IF NOT EXISTS ix_enterprise_assets_expires
            ON enterprise_assets(expires_on, status);
        CREATE TABLE IF NOT EXISTS enterprise_asset_versions (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL REFERENCES enterprise_assets(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            object_key TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(asset_id, version),
            UNIQUE(asset_id, sha256)
        );
        CREATE INDEX IF NOT EXISTS ix_enterprise_asset_versions_asset
            ON enterprise_asset_versions(asset_id, version);
        CREATE TABLE IF NOT EXISTS project_asset_links (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            asset_id TEXT NOT NULL REFERENCES enterprise_assets(id) ON DELETE CASCADE,
            linked_by TEXT NOT NULL REFERENCES users(id),
            linked_at TEXT NOT NULL,
            PRIMARY KEY(project_id, asset_id)
        );
        CREATE INDEX IF NOT EXISTS ix_project_asset_links_asset
            ON project_asset_links(asset_id);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(7,?)', (now(),))
        # B14 draft: export template metadata and checklist on artifacts.
        _ensure_column(conn, 'export_artifacts', 'template_id', "TEXT NOT NULL DEFAULT 'full'")
        _ensure_column(conn, 'export_artifacts', 'template_version', "TEXT NOT NULL DEFAULT 'export-template-v1'")
        _ensure_column(conn, 'export_artifacts', 'checklist_json', "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, 'export_artifacts', 'parent_artifact_id', 'TEXT')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(8,?)', (now(),))
        # B10 draft: retrieval index versions for project evidence corpora.
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS index_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'keyword'
                CHECK(kind IN ('keyword','hybrid')),
            status TEXT NOT NULL DEFAULT 'ready'
                CHECK(status IN ('building','ready','failed','retired')),
            corpus_stats_json TEXT NOT NULL DEFAULT '{}',
            built_by TEXT NOT NULL REFERENCES users(id),
            built_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_index_versions_project
            ON index_versions(project_id, built_at);
        ''')
        conn.execute('INSERT OR IGNORE INTO platform_migrations(version,applied_at) VALUES(9,?)', (now(),))


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    existing = {
        row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
    }
    if column not in existing:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')


class NotFoundError(ValueError):
    pass


class ConflictError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass
