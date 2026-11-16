import json
import sqlite3
import threading
import time
from pathlib import Path

from .protocol import Fault


class Database:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "private").mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "private/state.sqlite", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                name TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, bandwidth INTEGER NOT NULL,
                quota INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS transfers(
                id TEXT PRIMARY KEY, user TEXT NOT NULL, direction TEXT NOT NULL,
                path TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
                offset INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
                updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS account_transfers ON transfers(user, status);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, timestamp REAL, user TEXT, event TEXT, detail TEXT);
        """)

    def user(self, fingerprint=None, name=None):
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE fingerprint=?" if fingerprint else "SELECT * FROM users WHERE name=?", (fingerprint or name,)).fetchone()
        if not row or not row["active"]:
            raise Fault("AUTH", "证书未登记或账户已禁用")
        return dict(row)

    def add_user(self, name, fingerprint, bandwidth, quota):
        if not name or len(name) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
            raise Fault("INPUT", "账户名只允许字母、数字、下划线和连字符")
        if bandwidth < 65536 or quota < 0:
            raise Fault("INPUT", "带宽不得低于64KiB/s，配额不能为负")
        (self.root / "users" / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock:
            self.db.execute("INSERT INTO users(name,fingerprint,bandwidth,quota) VALUES(?,?,?,?)", (name, fingerprint, bandwidth, quota))

    def update_user(self, name, active=None, bandwidth=None):
        with self.lock:
            if active is not None:
                self.db.execute("UPDATE users SET active=? WHERE name=?", (int(active), name))
            if bandwidth is not None:
                if bandwidth < 65536:
                    raise Fault("INPUT", "带宽不得低于64KiB/s")
                self.db.execute("UPDATE users SET bandwidth=? WHERE name=?", (bandwidth, name))

    def get(self, transfer, user):
        with self.lock:
            row = self.db.execute("SELECT * FROM transfers WHERE id=? AND user=?", (transfer, user)).fetchone()
        if not row:
            raise Fault("NOT_FOUND", "传输任务不存在或不属于当前用户")
        return dict(row)

    def create(self, transfer, user, direction, path, size, sha256):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                account = self.user(name=user)
                existing = self.db.execute("SELECT * FROM transfers WHERE id=?", (transfer,)).fetchone()
                if existing:
                    if tuple(existing[k] for k in ("user", "direction", "path", "size", "sha256")) != (user, direction, path, size, sha256):
                        raise Fault("CONFLICT", "传输编号与原任务不匹配")
                    self.db.execute("COMMIT")
                    return dict(existing)
                if direction == "upload":
                    used = self.db.execute("SELECT COALESCE(SUM(size),0) FROM transfers WHERE user=? AND direction='upload' AND status NOT IN ('cancelled','failed')", (user,)).fetchone()[0]
                    if used + size > account["quota"]:
                        raise Fault("QUOTA", "存储配额不足，包含未完成任务预留空间")
                count = self.db.execute("SELECT COUNT(*) FROM transfers WHERE user=?", (user,)).fetchone()[0]
                if count >= 10000:
                    raise Fault("LIMIT", "账户任务记录达到10000条，请管理员归档运行数据")
                self.db.execute("INSERT INTO transfers(id,user,direction,path,size,sha256,updated) VALUES(?,?,?,?,?,?,?)", (transfer,user,direction,path,size,sha256,time.time()))
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
        return self.get(transfer, user)

    def update(self, transfer, offset=None, status=None):
        with self.lock:
            if offset is not None:
                self.db.execute("UPDATE transfers SET offset=?,updated=? WHERE id=?", (offset,time.time(),transfer))
            if status is not None:
                self.db.execute("UPDATE transfers SET status=?,updated=? WHERE id=?", (status,time.time(),transfer))

    def audit(self, user, event, detail):
        with self.lock:
            self.db.execute("INSERT INTO audit(timestamp,user,event,detail) VALUES(?,?,?,?)", (time.time(),user,event,json.dumps(detail,ensure_ascii=False)))
            # Bound audit storage; detailed rotating logs supplement this history.
            self.db.execute("DELETE FROM audit WHERE id < (SELECT COALESCE(MAX(id),0)-5000 FROM audit)")
