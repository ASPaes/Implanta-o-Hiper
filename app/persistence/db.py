"""SQLite connection and schema initialization."""

import sqlite3
from pathlib import Path

from app.models import STEP_KEYS


SCHEMA = """
CREATE TABLE IF NOT EXISTS deployments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id TEXT NOT NULL,
  hiper_account TEXT,
  environment TEXT NOT NULL DEFAULT 'homologacao',
  status TEXT NOT NULL DEFAULT 'rascunho',
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT
);

CREATE TABLE IF NOT EXISTS deployment_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deployment_id INTEGER NOT NULL REFERENCES deployments(id),
  step_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pendente',
  attempts INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  evidence_reference TEXT,
  error_code TEXT,
  error_message_sanitized TEXT,
  UNIQUE(deployment_id, step_key)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deployment_id INTEGER NOT NULL REFERENCES deployments(id),
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hiper_store_mappings (
  contract_id TEXT NOT NULL, cnpj TEXT NOT NULL, hiper_base_url TEXT NOT NULL,
  hiper_store_id TEXT NOT NULL, hiper_store_name TEXT NOT NULL, verified_at TEXT NOT NULL,
  PRIMARY KEY(contract_id, cnpj, hiper_base_url)
);
CREATE TABLE IF NOT EXISTS hiper_locks (
  resource TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL
);
"""


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def connect(database_path: str) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=DatabaseConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db(database_path: str) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deployments)")}
        additions = {
            "hiper_base_url": "TEXT", "hiper_store_id": "TEXT",
            "hiper_store_name": "TEXT", "hiper_store_cnpj": "TEXT",
            "hiper_store_url": "TEXT", "store_resolution_method": "TEXT",
            "store_verified_at": "TEXT", "execution_mode": "TEXT NOT NULL DEFAULT 'simulation'",
            "selected_steps_json": "TEXT NOT NULL DEFAULT '[\"loja_config\"]'",
            "pause_requested": "INTEGER NOT NULL DEFAULT 0",
            "contract_source": "TEXT NOT NULL DEFAULT 'fixture'",
        }
        for column, definition in additions.items():
            if column not in columns:
                connection.execute(f"ALTER TABLE deployments ADD COLUMN {column} {definition}")
        step_columns = {row[1] for row in connection.execute("PRAGMA table_info(deployment_steps)")}
        if "execution_mode" not in step_columns:
            connection.execute("ALTER TABLE deployment_steps ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'simulation'")
        for step_key in STEP_KEYS:
            connection.execute(
                """INSERT OR IGNORE INTO deployment_steps (deployment_id, step_key)
                   SELECT id, ? FROM deployments""",
                (step_key,),
            )
        connection.execute(
            """UPDATE deployments SET status = 'aguardando_intervencao'
               WHERE status = 'homologacao_concluida' AND EXISTS (
                 SELECT 1 FROM deployment_steps
                 WHERE deployment_id = deployments.id AND status != 'concluida'
               )"""
        )
