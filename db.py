import sqlite3
from datetime import datetime

DB_PATH = "jobs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        output TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        type TEXT DEFAULT 'chat'
    )
    """)
    conn.commit()
    conn.close()

def add_job(prompt, job_type="chat"):
    conn = sqlite3.connect("jobs.db")
    c = conn.cursor()
    c.execute("INSERT INTO jobs (prompt, status, created_at, type) VALUES (?, 'queued', ?, ?)",
              (prompt, datetime.utcnow().isoformat(), job_type))
    conn.commit()
    job_id = c.lastrowid
    conn.close()
    return job_id

def get_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = c.fetchone()
    conn.close()
    return job

def update_job_status(job_id, status, output=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if output:
        c.execute("UPDATE jobs SET status = ?, output = ?, completed_at = ? WHERE id = ?",
                  (status, output, datetime.utcnow().isoformat(), job_id))
    else:
        c.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    conn.close()

def get_all_jobs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, prompt, status, created_at, completed_at FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    return jobs
