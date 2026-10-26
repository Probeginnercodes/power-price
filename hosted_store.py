"""Durable SQLite queue for ONE host and ONE active model worker.

Transactions enforce quotas and atomic claims across API processes. Anonymous
sessions provide job isolation, not verified user identity. This is a bounded
portfolio demo, not a multi-tenant trading platform.
"""

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

from hosted_settings import HostedSettings


class QueueLimitError(ValueError):
    """A quota or queue capacity was reached; callers should return HTTP 429."""


class JobStore:
    def __init__(self, settings: HostedSettings):
        self.settings = settings
        settings.root.mkdir(parents=True, exist_ok=True)
        self.database = settings.root / "jobs.sqlite3"
        with self.connection() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS session_attempts(client_hash TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, client_hash TEXT NOT NULL,
                    options TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    started REAL, finished REAL, lease_until REAL, result_id TEXT, error TEXT);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);
                CREATE TABLE IF NOT EXISTS worker_state(id INTEGER PRIMARY KEY, heartbeat REAL);
            """)
        # Persistent server-side salt prevents publishing raw client IPs in the DB.
        salt_path = settings.root / "client_hash_salt"
        try:
            with salt_path.open("x", encoding="utf-8") as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        self.salt = salt_path.read_text(encoding="utf-8")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, client: str = "local") -> str:
        token = secrets.token_urlsafe(32)
        client_hash = hashlib.sha256((self.salt + client).encode()).hexdigest()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM session_attempts WHERE created<?", (time.time() - 3600,)
            )
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM session_attempts WHERE client_hash=?", (client_hash,)
                ).fetchone()[0]
                >= 20
            ):
                raise QueueLimitError("Too many demo sessions; retry in an hour")
            connection.execute(
                "INSERT INTO session_attempts VALUES (?,?)", (client_hash, time.time())
            )
            connection.execute(
                "INSERT INTO sessions VALUES (?,?)", (self.token_hash(token), time.time())
            )
        return token

    def owner(self, token: str) -> str | None:
        digest = self.token_hash(token)
        with self.connection() as connection:
            found = connection.execute(
                "SELECT created FROM sessions WHERE token_hash=?", (digest,)
            ).fetchone()
        return digest if found and found["created"] > time.time() - 7 * 86400 else None

    def submit(self, owner: str, client: str, options: dict) -> str:
        now = time.time()
        client_hash = hashlib.sha256((self.salt + client).encode()).hexdigest()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            pending = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            active = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE owner=? AND status IN ('queued','running')",
                (owner,),
            ).fetchone()[0]
            hourly = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE client_hash=? AND created>?",
                (client_hash, now - 3600),
            ).fetchone()[0]
            daily = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE created>?", (now - 86400,)
            ).fetchone()[0]
            if (
                active
                or pending >= self.settings.max_pending
                or hourly >= self.settings.per_ip_hour
                or daily >= self.settings.global_daily
            ):
                raise QueueLimitError(
                    "Demo limit reached. One active job per session, three submissions per client per hour, and twelve globally per day."
                )
            job_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO jobs(id,owner,client_hash,options,status,created) VALUES (?,?,?,?,?,?)",
                (job_id, owner, client_hash, json.dumps(options), "queued", now),
            )
        return job_id

    def claim(self) -> dict | None:
        """Lease one job atomically; never run two model jobs on this host."""
        now = time.time()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT OR REPLACE INTO worker_state VALUES (1,?)", (now,))
            connection.execute(
                "UPDATE jobs SET status='interrupted',finished=?,error='Worker interrupted; please submit again.' WHERE status='running' AND lease_until<?",
                (now, now),
            )
            if connection.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                return None
            job = connection.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if job is None:
                return None
            connection.execute(
                "UPDATE jobs SET status='running',started=?,lease_until=? WHERE id=?",
                (now, now + self.settings.timeout_seconds + 30, job["id"]),
            )
        return dict(job)

    def finish(
        self, job_id: str, status: str, result_id: str | None = None, error: str | None = None
    ):
        with self.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status=?,finished=?,result_id=?,error=? WHERE id=? AND status='running'",
                (status, time.time(), result_id, error, job_id),
            )

    def list_jobs(self, owner: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 30", (owner,)
            ).fetchall()
        return [dict(row) for row in rows]

    def result_job(self, owner: str, run_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE owner=? AND result_id=? AND status='success'",
                (owner, run_id),
            ).fetchone()
        return dict(row) if row else None

    def pulse(self) -> float | None:
        with self.connection() as connection:
            row = connection.execute("SELECT heartbeat FROM worker_state WHERE id=1").fetchone()
        return row[0] if row else None

    def expired(self) -> list[str]:
        """Expire terminal results after retention; leave active jobs untouched."""
        cutoff = time.time() - self.settings.retention_hours * 3600
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE finished<? AND status IN ('success','failed','timed_out','interrupted')",
                (cutoff,),
            ).fetchall()
            connection.execute(
                "UPDATE jobs SET status='expired',result_id=NULL WHERE finished<? AND status IN ('success','failed','timed_out','interrupted')",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM sessions WHERE created<? AND token_hash NOT IN (SELECT owner FROM jobs WHERE status IN ('queued','running'))",
                (time.time() - 7 * 86400,),
            )
        return [row[0] for row in rows]
