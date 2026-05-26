"""用户 / 会话 / 每日用量存储层(task #62 多用户体系)。

复用 record_manager 的 gold_records.db 与连接,新增 users / user_sessions /
daily_usage 三张表。访问风格与 record_manager 一致:原生 sqlite3 + closing()。
纯 additive(只加表/索引),不动现有业务表。
"""
from __future__ import annotations

import time
import uuid
from contextlib import closing
from datetime import datetime, timezone

from storage.record_manager import _connect  # 同一个 gold_records.db

_AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',          -- 'user' | 'admin'
    status TEXT NOT NULL DEFAULT 'active',        -- 'active' | 'disabled'
    balance_cents INTEGER NOT NULL DEFAULT 0,     -- 钱包余额(分),阶段4启用
    daily_free_cents INTEGER,                     -- NULL=用全局默认;非空=管理员为该用户单独提额
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at INTEGER NOT NULL                   -- epoch 秒
);
CREATE TABLE IF NOT EXISTS daily_usage (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,                           -- YYYY-MM-DD (北京时区)
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_cents INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS redemption_codes (
    code TEXT PRIMARY KEY,
    cents INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    used_by TEXT,
    used_at TEXT
);
"""


def init_auth_storage() -> None:
    """建表 + 索引。在 app 启动时调用一次(纯 additive,可重复执行)。"""
    with closing(_connect()) as conn:
        conn.executescript(_AUTH_SCHEMA)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_exp ON user_sessions(expires_at)")
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----- users -----------------------------------------------------------------

def create_user(username: str, password_hash: str, role: str = "user", balance_cents: int = 0) -> dict:
    uid = str(uuid.uuid4())
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, status, balance_cents, created_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (uid, username, password_hash, role, balance_cents, _now_iso()),
        )
        conn.commit()
    return get_user_by_id(uid)


def get_user_by_username(username: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(uid: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def set_user_password(uid: str, password_hash: str) -> None:
    with closing(_connect()) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, uid))
        conn.commit()


def list_users() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_user_fields(uid: str, **fields) -> None:
    """只允许更新白名单字段(管理员用)。"""
    allowed = {"role", "status", "balance_cents", "daily_free_cents"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with closing(_connect()) as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id = ?", (*sets.values(), uid))
        conn.commit()


def charge_wallet(user_id: str, cents: float) -> None:
    """从钱包扣费(cents 分,可浮点,取整为整数分);余额可短暂为负,下次预检拦截。"""
    amt = int(round(cents))
    if amt <= 0:
        return
    with closing(_connect()) as conn:
        conn.execute("UPDATE users SET balance_cents = balance_cents - ? WHERE id = ?", (amt, user_id))
        conn.commit()


def add_balance(user_id: str, cents: int) -> None:
    """钱包充值(整数分)。"""
    with closing(_connect()) as conn:
        conn.execute("UPDATE users SET balance_cents = balance_cents + ? WHERE id = ?", (int(cents), user_id))
        conn.commit()


# ----- sessions --------------------------------------------------------------

def create_session(user_id: str, token: str, ttl_seconds: int) -> None:
    exp = int(time.time()) + ttl_seconds
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, _now_iso(), exp),
        )
        conn.commit()


def get_session_user(token: str | None) -> dict | None:
    """返回 token 对应的有效用户(会话未过期 + 账号 active),否则 None。"""
    if not token:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT u.* FROM user_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ? AND u.status = 'active'",
            (token, int(time.time())),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()


def delete_user_sessions(user_id: str) -> None:
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()


def purge_expired_sessions() -> None:
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (int(time.time()),))
        conn.commit()


# ----- daily usage (阶段3 计费启用,此处先放基础读写) -------------------------

def get_today_usage(user_id: str, date: str) -> dict:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM daily_usage WHERE user_id = ? AND date = ?", (user_id, date)
        ).fetchone()
    if row:
        return dict(row)
    return {"user_id": user_id, "date": date, "prompt_tokens": 0, "completion_tokens": 0, "cost_cents": 0}


def add_usage(user_id: str, date: str, prompt_tokens: int, completion_tokens: int, cost_cents: int) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO daily_usage (user_id, date, prompt_tokens, completion_tokens, cost_cents) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, date) DO UPDATE SET "
            "prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
            "completion_tokens = completion_tokens + excluded.completion_tokens, "
            "cost_cents = cost_cents + excluded.cost_cents",
            (user_id, date, prompt_tokens, completion_tokens, cost_cents),
        )
        conn.commit()


# ----- redemption codes (钱包充值) -------------------------------------------

def create_redemption_code(code: str, cents: int) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO redemption_codes (code, cents, created_at) VALUES (?, ?, ?)",
            (code, int(cents), _now_iso()),
        )
        conn.commit()


def redeem_code(code: str, user_id: str) -> tuple[bool, object]:
    """兑换码 → 加余额。返回 (ok, cents 或 错误消息)。原子:标记已用 + 加余额。"""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM redemption_codes WHERE code = ?", (code,)).fetchone()
        if not row:
            return False, "兑换码无效"
        if row["used_by"]:
            return False, "兑换码已被使用"
        cur = conn.execute(
            "UPDATE redemption_codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
            (user_id, _now_iso(), code),
        )
        if cur.rowcount == 0:  # 并发抢用
            conn.rollback()
            return False, "兑换码已被使用"
        conn.execute("UPDATE users SET balance_cents = balance_cents + ? WHERE id = ?", (row["cents"], user_id))
        conn.commit()
        return True, int(row["cents"])


def list_redemption_codes(limit: int = 200) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM redemption_codes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
