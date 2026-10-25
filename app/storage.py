import sqlite3
from datetime import datetime
from .config import DATABASE_PATH

def connect():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL UNIQUE,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            telegram_message_id INTEGER,
            error TEXT,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic)")

def topics_used(limit=120):
    with connect() as conn:
        rows = conn.execute(
            "SELECT topic FROM posts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row["topic"] for row in rows]

def already_ran(run_date):
    with connect() as conn:
        row = conn.execute("SELECT id FROM posts WHERE run_date=?", (run_date,)).fetchone()
    return row is not None

def save_post(run_date, topic, title, body, status, message_id=None, error=None):
    with connect() as conn:
        conn.execute("""
        INSERT INTO posts(run_date, topic, title, body, status, telegram_message_id, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_date) DO UPDATE SET
          topic=excluded.topic, title=excluded.title, body=excluded.body,
          status=excluded.status, telegram_message_id=excluded.telegram_message_id,
          error=excluded.error
        """, (run_date, topic, title, body, status, message_id, error,
              datetime.now().astimezone().isoformat(timespec="seconds")))

def update_status(run_date, status, message_id=None, error=None):
    with connect() as conn:
        conn.execute("""
        UPDATE posts SET status=?, telegram_message_id=COALESCE(?, telegram_message_id), error=?
        WHERE run_date=?
        """, (status, message_id, error, run_date))
