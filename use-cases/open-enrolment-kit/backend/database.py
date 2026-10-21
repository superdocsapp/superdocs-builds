import psycopg
import json
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.getenv("DATABASE_URL", "postgresql://superdocs_user:superdocs_password@localhost:5432/superdocs_db")

def init_db():
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT,
                    status TEXT,
                    content TEXT
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    document_id TEXT,
                    status TEXT,
                    proposed_changes TEXT,
                    cost REAL
                )
            ''')
        conn.commit()

def save_document(doc_id, filename, status, content=""):
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO documents (id, filename, status, content) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    filename = EXCLUDED.filename, 
                    status = EXCLUDED.status, 
                    content = EXCLUDED.content
            """, (doc_id, filename, status, content))
        conn.commit()

def save_job(job_id, document_id, status, proposed_changes=None, cost=0.0):
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as c:
            changes_json = json.dumps(proposed_changes) if proposed_changes else "[]"
            c.execute("""
                INSERT INTO jobs (id, document_id, status, proposed_changes, cost) 
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    document_id = EXCLUDED.document_id,
                    status = EXCLUDED.status,
                    proposed_changes = EXCLUDED.proposed_changes,
                    cost = EXCLUDED.cost
            """, (job_id, document_id, status, changes_json, cost))
        conn.commit()

def get_job(job_id):
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as c:
            c.execute("SELECT id, document_id, status, proposed_changes, cost FROM jobs WHERE id = %s", (job_id,))
            row = c.fetchone()
            if row:
                return {
                    "id": row[0],
                    "document_id": row[1],
                    "status": row[2],
                    "proposed_changes": json.loads(row[3]),
                    "cost": row[4]
                }
    return None


