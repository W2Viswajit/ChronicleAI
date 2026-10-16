import json
import sqlite3
from .config import RUNTIME
DB = RUNTIME / 'chronicle.sqlite3'
def connect():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init():
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, status TEXT, stage TEXT, payload TEXT, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
        c.execute("UPDATE analyses SET status='failed', error='Server restarted before this job finished.' WHERE status IN ('queued','running')")

def create(job):
    with connect() as c:
        c.execute('INSERT INTO analyses(id,status,stage) VALUES (?,?,?)', (job,'queued','Waiting for CPU worker'))

def update(job, status, stage='', payload=None, error=None):
    with connect() as c:
        c.execute('UPDATE analyses SET status=?,stage=?,payload=?,error=? WHERE id=?', (status,stage,json.dumps(payload) if payload is not None else None,error,job))

def get(job):
    with connect() as c:
        r = c.execute('SELECT * FROM analyses WHERE id=?',(job,)).fetchone()
    if not r: return None
    d = dict(r)
    d['result'] = json.loads(d.pop('payload')) if d['payload'] else None
    d.pop('payload', None)
    return d

def history():
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT id,status,stage,error,created FROM analyses ORDER BY created DESC LIMIT 20')]
