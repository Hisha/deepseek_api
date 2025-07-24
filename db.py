import sqlite3
from datetime import datetime

DB_PATH = "jobs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT,
        type TEXT,
        status TEXT,
        output TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        progress INTEGER DEFAULT 0,
        current_step TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_job(prompt, job_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    c.execute("""
        INSERT INTO jobs (prompt, type, status, created_at)
        VALUES (?, ?, 'queued', ?)
    """, (prompt, job_type, created_at))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id

def update_job_status(job_id, status, message=None, progress=None, current_step=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if status == "completed":
        c.execute("""
        UPDATE jobs SET status=?, output=?, completed_at=CURRENT_TIMESTAMP, progress=?, current_step=? WHERE id=?
        """, (status, message, 100, None, job_id))
    else:
        c.execute("""
        UPDATE jobs SET status=?, output=?, progress=?, current_step=?, completed_at=NULL WHERE id=?
        """, (status, message, progress, current_step, job_id))
    conn.commit()
    conn.close()

def get_all_jobs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, prompt, type, status, created_at, completed_at FROM jobs ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT id, prompt, type, status, output, created_at, completed_at, progress, current_step
    FROM jobs WHERE id=?
    """, (job_id,))
    job = c.fetchone()
    conn.close()
    return job
