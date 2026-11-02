"""Persistent document inventory, conversations and usage measurements."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config import config


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


@contextmanager
def connection():
    config.database.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(config.database, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    config.upload_dir.mkdir(exist_ok=True)
    with connection() as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, extension TEXT NOT NULL,
                size INTEGER NOT NULL, chunks INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL,
                status TEXT NOT NULL, duration_ms INTEGER NOT NULL,
                retrieval_ms INTEGER NOT NULL, created_at TEXT NOT NULL,
                first_token_ms INTEGER
            );
        """)
        if "first_token_ms" not in {row["name"] for row in db.execute("PRAGMA table_info(messages)")}:
            db.execute("ALTER TABLE messages ADD COLUMN first_token_ms INTEGER")


def documents():
    with connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY created_at DESC, rowid DESC")]


def add_document(doc_id, name, extension, size, chunks):
    with connection() as db:
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (doc_id, name, extension, size, chunks, now()))


def document(doc_id):
    with connection() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def remove_document(doc_id):
    with connection() as db:
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))


def sessions():
    with connection() as db:
        return [dict(row) for row in db.execute("""SELECT s.*, COUNT(m.id) AS count,
            MAX(m.created_at) AS updated_at FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
            GROUP BY s.id ORDER BY COALESCE(MAX(m.created_at),s.created_at) DESC LIMIT 50""")]


def history(session_id):
    with connection() as db:
        rows = db.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        return [decode_message(row) for row in rows]


def decode_message(row):
    message = dict(row)
    message["sources"] = json.loads(message["sources"])
    return message


def save_message(session_id, question, answer, sources, status, duration_ms, retrieval_ms, first_token_ms=None):
    session_id = session_id or uuid4().hex
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?)", (session_id, question[:32], now()))
        cursor = db.execute("""INSERT INTO messages
            (session_id,question,answer,sources,status,duration_ms,retrieval_ms,created_at,first_token_ms)
            VALUES (?,?,?,?,?,?,?,?,?)""", (session_id, question, answer, json.dumps(sources, ensure_ascii=False),
                                          status, duration_ms, retrieval_ms, now(), first_token_ms))
        return session_id, cursor.lastrowid


def overview(days=7):
    today = datetime.now(timezone(timedelta(hours=8))).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    with connection() as db:
        docs = documents()
        summary = dict(db.execute("""SELECT COUNT(*) AS questions,
            SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN sources!='[]' THEN 1 ELSE 0 END) AS with_sources,
            AVG(CASE WHEN status='answered' THEN duration_ms END) AS avg_duration_ms,
            AVG(CASE WHEN status='answered' THEN retrieval_ms END) AS avg_retrieval_ms
            FROM messages WHERE created_at>=?""", (since,)).fetchone())
        grouped = {row["day"]: dict(row) for row in db.execute("""SELECT substr(created_at,1,10) AS day,
            COUNT(*) AS questions, SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END) AS answered
            FROM messages WHERE created_at>=? GROUP BY day""", (since,))}
        recent = [decode_message(row) for row in db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 8")]
        session_count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    trend = []
    for i in range(days):
        day = (today - timedelta(days=days - 1 - i)).isoformat()
        trend.append(grouped.get(day, {"day": day, "questions": 0, "answered": 0}))
    return {"summary": {**summary, "answered": summary["answered"] or 0,
                        "with_sources": summary["with_sources"] or 0,
                        "documents": len(docs), "chunks": sum(d["chunks"] for d in docs),
                        "storage_bytes": sum(d["size"] for d in docs), "sessions": session_count},
            "trend": trend, "documents": docs, "recent": recent, "days": days}
