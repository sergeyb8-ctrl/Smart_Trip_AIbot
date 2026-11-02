from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from .models import Place

class Database:
    def __init__(self, path, catalog):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS places (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL, input_mode TEXT NOT NULL,
                    request TEXT NOT NULL, result TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS trips_owner ON trips(user_id,id);
                CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY, state TEXT, data TEXT NOT NULL DEFAULT '{}');
            """)
        content = json.loads(Path(catalog).read_text(encoding="utf-8"))
        self.catalog_info = content["metadata"]
        places = [Place.model_validate(item) for item in content["places"]]
        if len({p.id for p in places}) != len(places):
            raise ValueError("Повторяющиеся идентификаторы объектов каталога")
        with self.connect() as db:
            db.execute("DELETE FROM places")
            db.executemany("INSERT INTO places VALUES (?,?)", [(p.id, p.model_dump_json()) for p in places])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def places(self):
        with self.connect() as db:
            return [Place.model_validate_json(row[0]) for row in db.execute("SELECT payload FROM places ORDER BY id")]

    def save_trip(self, user_id, request, result, mode):
        with self.connect() as db:
            cursor = db.execute("INSERT INTO trips(user_id,created_at,input_mode,request,result) VALUES (?,?,?,?,?)",
                (user_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), mode,
                 request.model_dump_json(), json.dumps(result, ensure_ascii=False)))
            return cursor.lastrowid

    def history(self, user_id, limit=5):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,created_at,request FROM trips WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id,limit))]

    def trip(self, user_id, trip_id=None):
        with self.connect() as db:
            if trip_id is None:
                row = db.execute("SELECT * FROM trips WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM trips WHERE user_id=? AND id=?",(user_id,trip_id)).fetchone()
            if row is None:
                return None
            return {**dict(row), "request": json.loads(row["request"]), "result": json.loads(row["result"])}

    def clear_history(self, user_id):
        with self.connect() as db:
            db.execute("DELETE FROM trips WHERE user_id=?",(user_id,))

class SQLiteStorage(BaseStorage):
    """Состояние анкеты сохраняется после перезапуска процесса."""
    def __init__(self, db):
        self.db = db

    @staticmethod
    def session_key(key: StorageKey):
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id}:{key.destiny}"

    async def set_state(self, key, state=None):
        value = state.state if hasattr(state, "state") else state
        with self.db.connect() as db:
            db.execute("INSERT INTO sessions(key,state) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET state=excluded.state",
                       (self.session_key(key), value))

    async def get_state(self, key):
        with self.db.connect() as db:
            row = db.execute("SELECT state FROM sessions WHERE key=?",(self.session_key(key),)).fetchone()
            return row[0] if row else None

    async def set_data(self, key, data):
        with self.db.connect() as db:
            db.execute("INSERT INTO sessions(key,data) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                       (self.session_key(key), json.dumps(data,ensure_ascii=False)))

    async def get_data(self, key):
        with self.db.connect() as db:
            row = db.execute("SELECT data FROM sessions WHERE key=?",(self.session_key(key),)).fetchone()
            return json.loads(row[0]) if row else {}

    async def close(self):
        return None

