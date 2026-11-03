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


class NotFoundError(ValueError):
    pass


class ConflictError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass
