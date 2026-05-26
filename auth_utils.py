"""鉴权工具(task #62):argon2 密码哈希、会话 token、HttpOnly cookie、
FastAPI 依赖(require_user/require_admin)、登录失败内存限流。

会话采用服务端 session:cookie 只存高熵随机 token,服务端查 user_sessions 表
校验(可吊销、过期自动失效)。cookie HttpOnly+Secure(生产)+SameSite=Lax。
"""
from __future__ import annotations

import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response

import storage.auth_store as auth_store
from config import settings

_ph = PasswordHasher()
SESSION_COOKIE = "aurumers_session"


# ----- 密码 ------------------------------------------------------------------

def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(password_hash: str, pw: str) -> bool:
    try:
        return _ph.verify(password_hash, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ----- 会话 token / cookie ---------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


# ----- FastAPI 依赖 ----------------------------------------------------------

def get_current_user(request: Request) -> dict | None:
    """从 cookie 解析当前登录用户;未登录返回 None(不抛错,用于可选鉴权)。"""
    token = request.cookies.get(SESSION_COOKIE)
    return auth_store.get_session_user(token)


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ----- 登录失败限流(内存,单进程) --------------------------------------------

_login_fails: dict[str, list[float]] = {}
_MAX_FAILS = 5
_WINDOW = 300  # 5 分钟内 5 次失败 → 锁定


def login_rate_limited(key: str) -> bool:
    now = time.time()
    arr = [t for t in _login_fails.get(key, []) if now - t < _WINDOW]
    _login_fails[key] = arr
    return len(arr) >= _MAX_FAILS


def record_login_fail(key: str) -> None:
    _login_fails.setdefault(key, []).append(time.time())


def clear_login_fails(key: str) -> None:
    _login_fails.pop(key, None)
