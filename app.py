import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import uuid

from chains.broadcast import broadcast_manager
from chains.daily_runner import run_daily_prediction
from chains.events import hub as event_hub
from chains.hermes_chat import (
    build_greeting,
    build_system_message,
    get_runtime_status,
    stream_reply,
    summarize_session_title_async,
)
from chains.runner import run_gold_analysis_once
from chains.scheduler import start_scheduler, stop_scheduler
from chains.skill_audit import get_skill_audit_summary
from chains.verifier import verify_prediction
from config import settings
from schemas import BroadcastEvent
import auth_utils
import billing
import signal_service
import storage.auth_store as auth_store
from storage.record_manager import (
    append_chat_message,
    archive_chat_session,
    compute_accuracy,
    compute_accuracy_v2,
    compute_calibration_buckets,
    compute_kpis,
    count_chat_messages,
    create_chat_session,
    delete_record,
    get_all_records,
    get_chat_session,
    get_daily_prediction,
    get_daily_predictions,
    get_dashboard_summary,
    get_latest_daily_prediction,
    get_latest_records,
    init_storage,
    list_chat_messages,
    list_chat_sessions,
    query_distribution,
    query_timeseries,
    update_chat_session_title,
)
from tools.gold_price import get_gold_price, get_market_snapshot
from tools.news import get_gold_news


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aurumers · Gold Forecast")
# /api/predictions/daily?range=all&include_backtest=true returns ~1.9 MB
# uncompressed (590 rows × ~3.25 KB each). Gzip middleware compresses to
# ~70 KB before transmit (round-4 audit MED). Applied to all responses
# ≥ 1 KB so small endpoints aren't impacted.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # cookie 会话同源自动携带,与 CORS credentials 无关;跨域不应带 cookie。
    # allow_origins=["*"]+credentials=True 是被 Starlette 忽略的无效组合 → 关掉。
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- 登录墙中间件 (task #62 阶段2) ------------------------------------------
# 除落地页/静态/健康检查/auth 端点外,所有 /api/* 需登录;localhost(本机
# scheduler / Hermes check_daily.sh)豁免,避免打断 02:50 预测。已登录用户挂到
# request.state.user 供下游端点复用。烧钱端点的扣费在阶段3叠加。
_AUTH_PUBLIC_API = ("/api/health", "/api/auth/")


def _api_needs_auth(path: str) -> bool:
    if not path.startswith("/api/"):
        return False  # 静态资源 / SPA 路由放行
    for p in _AUTH_PUBLIC_API:
        if path == p or path.startswith(p):
            return False
    return True


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)  # CORS 预检放行
    path = request.url.path
    client_host = request.client.host if request.client else ""
    # 本机调用(scheduler/check_daily/Hermes)豁免;非 /api 或白名单 API 放行
    if client_host in _LOCAL_HOSTS or not _api_needs_auth(path):
        return await call_next(request)
    user = auth_store.get_session_user(request.cookies.get(auth_utils.SESSION_COOKIE))
    if not user:
        return JSONResponse(
            {"success": False, "data": None, "error": "未登录"}, status_code=401
        )
    request.state.user = user
    return await call_next(request)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SPA_DIR = BASE_DIR / "static_dist"
TEMPLATES_DIR = BASE_DIR / "templates"

if STATIC_DIR.exists():
    app.mount("/static-legacy", StaticFiles(directory=STATIC_DIR), name="static_legacy")
if SPA_DIR.exists():
    app.mount("/static", StaticFiles(directory=SPA_DIR), name="spa_assets")


# SSE event hub now lives in chains/events.py (shared with scheduler/runners).


def success_response(data):
    return {"success": True, "data": data, "error": None}


def error_response(message: str, *, status_code: int | None = None):
    body = {"success": False, "data": None, "error": message}
    if status_code:
        return JSONResponse(content=body, status_code=status_code)
    return body


def _serve_spa() -> FileResponse:
    spa_index = SPA_DIR / "index.html"
    if spa_index.exists():
        return FileResponse(spa_index)
    legacy = TEMPLATES_DIR / "index.html"
    if legacy.exists():
        return FileResponse(legacy)
    raise HTTPException(status_code=404, detail="UI not built. Run `npm run build` in frontend/.")


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _check_admin(request: Request) -> None:
    expected = settings.admin_token
    if not expected:
        raise HTTPException(status_code=403, detail="管理员通道未启用")
    provided = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
    if provided != expected:
        raise HTTPException(status_code=401, detail="管理员鉴权失败")


def _check_admin_or_local(request: Request) -> None:
    """Allow either an admin-token request OR localhost (for in-host scheduler/Hermes)."""
    client_host = request.client.host if request.client else ""
    if client_host in _LOCAL_HOSTS:
        return
    if not settings.admin_token:
        raise HTTPException(status_code=403, detail="该接口仅限管理员或本机调用，请配置 ADMIN_TOKEN")
    provided = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
    if provided != settings.admin_token:
        raise HTTPException(status_code=401, detail="管理员鉴权失败")


# ----- Lifecycle ---------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    init_storage()
    auth_store.init_auth_storage()
    _seed_admin()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_scheduler()


# ----- Pages / SPA -------------------------------------------------------------

@app.get("/")
def home():
    return _serve_spa()


@app.get("/app/{path:path}")
def app_routes(path: str):
    """SPA catch-all for /app/* routes."""
    return _serve_spa()


@app.get("/records")
def records_legacy():
    return _serve_spa()


@app.get("/auth/{path:path}")
def auth_spa(path: str):
    """SPA fallback：登录/注册等前端路由直接访问/刷新时返回 index。"""
    return _serve_spa()


@app.get("/_ops")
@app.get("/_ops/{path:path}")
def ops_spa(path: str = ""):
    """SPA fallback：管理后台前端路由直接访问/刷新时返回 index。"""
    return _serve_spa()


# ----- Existing API endpoints --------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness probe: 200 if DB readable, 503 otherwise."""
    try:
        get_daily_predictions(window_days=1)
        return {"status": "ok", "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)[:200]}, status_code=503)


@app.get("/api/price")
def read_gold_price():
    snapshot = get_market_snapshot()
    return success_response(snapshot)


@app.get("/api/signal/latest")
def read_trend_signal():
    """最新黄金趋势信号(多周期集成,未来约1个月方向)。"""
    try:
        sig = signal_service.get_signal()
        return success_response({**sig, "disclaimer": signal_service.DISCLAIMER})
    except FileNotFoundError:
        return error_response("信号模型尚未部署", status_code=503)
    except Exception:
        logger.exception("trend signal failed")
        return error_response("信号计算失败，请稍后再试", status_code=503)


@app.post("/api/holdings/advice")
async def holdings_advice(request: Request):
    """持仓助手:输入持仓(总价值 或 成本价×克数)→ 信号驱动的买卖建议。"""
    try:
        body = await request.json()
    except Exception:
        return error_response("请求体无效", status_code=400)

    grams = body.get("grams")
    cost_per_g = body.get("cost_per_g")
    value_cny = body.get("value_cny")

    try:
        sig = signal_service.get_signal()
    except FileNotFoundError:
        return error_response("信号模型尚未部署", status_code=503)
    except Exception:
        logger.exception("trend signal failed")
        return error_response("信号计算失败，请稍后再试", status_code=503)
    price = sig["price_cny_per_g"]

    # 两种输入归一到克数
    try:
        if grams is not None:
            grams = float(grams)
        elif value_cny is not None:
            grams = float(value_cny) / price
        else:
            return error_response("请提供持仓克数或总价值", status_code=400)
        if grams <= 0 or grams > 1e7:
            return error_response("持仓数值超出合理范围", status_code=400)
        if cost_per_g is not None:
            cost_per_g = float(cost_per_g)
            if cost_per_g <= 0 or cost_per_g > 1e6:
                return error_response("成本价超出合理范围", status_code=400)
    except (TypeError, ValueError):
        return error_response("持仓数值无效", status_code=400)

    return success_response(signal_service.build_advice(round(grams, 4), cost_per_g))


@app.post("/api/analysis/run")
async def run_analysis(request: Request):
    user = getattr(request.state, "user", None)
    if user:
        billing.assert_can_spend(user)  # 额度/余额不足 → 402
    try:
        record = await asyncio.to_thread(run_gold_analysis_once)
        await event_hub.publish("analysis_record_added", record.model_dump(mode="json"))
        if user:
            billing.charge_for_record(user, record)
        return success_response(record.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Analysis request failed")
        return error_response("分析执行失败，请稍后再试")


@app.get("/api/records")
def read_records():
    return success_response([record.model_dump(mode="json") for record in get_all_records()])


@app.get("/api/records/latest")
def read_latest_records(n: int = 20):
    return success_response([record.model_dump(mode="json") for record in get_latest_records(n)])


@app.delete("/api/records/{record_id}")
def remove_record(record_id: str, request: Request):
    _check_admin_or_local(request)
    success, message = delete_record(record_id)
    if success:
        return success_response({"message": message})
    return error_response(message)


@app.get("/api/dashboard/summary")
def read_dashboard_summary(limit: int = 24):
    return success_response(get_dashboard_summary(limit).model_dump(mode="json"))


@app.get("/api/analytics/timeseries")
def read_analytics_timeseries(range: str = Query("24h")):
    resolved, points = query_timeseries(range)
    return success_response({
        "range": resolved,
        "points": [point.model_dump(mode="json") for point in points],
    })


@app.get("/api/analytics/distribution")
def read_analytics_distribution(range: str = Query("24h")):
    resolved, snapshot = query_distribution(range)
    payload = snapshot.model_dump(mode="json")
    payload["range"] = resolved
    return success_response(payload)


@app.get("/api/analytics/kpis")
def read_analytics_kpis(range: str = Query("24h")):
    return success_response(compute_kpis(range).model_dump(mode="json"))


# ----- New: predictions --------------------------------------------------------

@app.post("/api/predictions/daily/run")
async def post_predictions_run(
    request: Request,
    date: str | None = Query(None),
):
    """Idempotent for the SAME day. Default `date=today_beijing` is unauthenticated
    (SPA + scheduler trigger). A non-today `date` is admin-only — without that
    guard any caller could POST `?date=2024-06-15` and overwrite the historical
    row's predict-owned columns (today_close_*, prob_*, reasoning_summary,
    advice, raw_output) with today's live data, while UPSERT preserves
    verified_* / baseline_* via Round 1-4 COALESCE protection.
    """
    today_iso = datetime.now().strftime("%Y-%m-%d")
    target = date or today_iso
    if target != today_iso:
        _check_admin_or_local(request)
    try:
        prediction = await asyncio.to_thread(run_daily_prediction, target)
        if prediction is None:
            return success_response({"skipped": "weekend", "date": target})
        payload = prediction.model_dump(mode="json")
        await event_hub.publish("daily_prediction_ready", payload)
        return success_response(payload)
    except Exception:
        logger.exception("daily prediction run failed")
        return error_response("每日预测执行失败，请稍后再试")


@app.post("/api/predictions/daily/verify")
async def post_predictions_verify(
    request: Request,
    date: str | None = Query(None),
    force: bool = Query(False),
):
    """Idempotent — only writes if actual close differs from anchor.

    ``force=true`` re-runs verification even on an already-verified row.
    Used to correct verifications that ran against stale / wrong close
    feeds. Requires admin or localhost auth to prevent anyone rewriting
    history through this endpoint."""
    if force:
        _check_admin_or_local(request)
    target = date or datetime.now().strftime("%Y-%m-%d")
    refreshed = await asyncio.to_thread(verify_prediction, target, force=force)
    if refreshed is None:
        return error_response("未找到该日期的预测记录")
    if refreshed.verified_correct is None:
        return success_response({"prediction": refreshed.model_dump(mode="json"), "verified": False})
    await event_hub.publish("prediction_verified", refreshed.model_dump(mode="json"))
    return success_response({"prediction": refreshed.model_dump(mode="json"), "verified": True})


@app.get("/api/predictions/today")
def get_today_prediction():
    today = datetime.now().strftime("%Y-%m-%d")
    today_pred = get_daily_prediction(today)
    fallback = get_latest_daily_prediction() if today_pred is None else None
    prediction = today_pred or fallback
    if prediction is None:
        return success_response(None)
    payload = prediction.model_dump(mode="json")
    payload["is_today"] = (today_pred is not None)
    return success_response(payload)


# When ``include_backtest=true`` is passed by the frontend toggle, aggregation
# expands to include historical replay rows (no-news provenance). Default is
# live-only so the headline dashboard never silently dilutes its denominator.
# placeholder_legacy is never included via this flag — those rows stay
# auditable but invisible to live metrics.
def _resolve_data_origins(include_backtest: bool) -> tuple[str, ...]:
    return ("live", "backtest_no_news") if include_backtest else ("live",)


@app.get("/api/predictions/daily")
def list_daily_predictions(
    range: str = Query("30d"),
    include_backtest: bool = Query(False),
):
    window_map = {"7d": 7, "30d": 30, "90d": 90, "all": None}
    days = window_map.get(range, 30)
    predictions = get_daily_predictions(days, data_origins=_resolve_data_origins(include_backtest))
    return success_response({
        "range": range if range in window_map else "30d",
        "items": [p.model_dump(mode="json") for p in predictions],
    })


@app.get("/api/predictions/accuracy")
def get_accuracy(
    window: str = Query("30d"),
    include_backtest: bool = Query(False),
):
    return success_response(
        compute_accuracy(window, data_origins=_resolve_data_origins(include_backtest)).model_dump(mode="json")
    )


@app.get("/api/predictions/calibration")
def get_calibration(
    window: str = Query("30d"),
    buckets: int = Query(5),
    include_backtest: bool = Query(False),
):
    return success_response([
        b.model_dump(mode="json") for b in compute_calibration_buckets(
            window,
            n_buckets=max(2, min(10, buckets)),
            data_origins=_resolve_data_origins(include_backtest),
        )
    ])


@app.get("/api/predictions/metrics/detailed")
def get_metrics_detailed(
    window: str = Query("30d"),
    include_reconstructed: bool = Query(False),
    include_synthetic: bool = Query(False),
    include_synthetic_v1: bool = Query(False),
    include_raw: bool = Query(False),
    include_backtest: bool = Query(False),
):
    return success_response(
        compute_accuracy_v2(
            window,
            include_reconstructed=include_reconstructed,
            include_synthetic=include_synthetic,
            include_synthetic_v1=include_synthetic_v1,
            include_raw=include_raw,
            data_origins=_resolve_data_origins(include_backtest),
        ).model_dump(mode="json")
    )


@app.get("/api/skill_audit/recent")
def get_skill_audit_recent(
    request: Request,
    window_days: int = Query(30),
    recent_n: int = Query(7),
):
    """Snapshot of Hermes skill self-evolution observability.

    Public endpoint (Insights page is public). To avoid leaking ops-side
    fingerprints, the response strips ``bytes`` per entry for non-admin
    callers and never includes the audit dir path. Admin (token or localhost)
    sees full detail including byte sizes."""
    summary = get_skill_audit_summary(
        window_days=max(1, min(365, window_days)),
        recent_n=max(1, min(30, recent_n)),
    )
    payload = summary.model_dump(mode="json")
    is_admin = False
    try:
        _check_admin_or_local(request)
        is_admin = True
    except HTTPException:
        is_admin = False
    if not is_admin:
        for entry in payload.get("most_recent", []):
            entry.pop("bytes", None)
    return success_response(payload)


@app.post("/api/predictions/inbox")
async def predictions_inbox(request: Request):
    """Receive supplementary commentary from external agents (e.g., Hermes).

    Allowed sources:
    - localhost (127.0.0.1 / ::1) — for the on-host Hermes skill
    - any caller carrying a valid X-Admin-Token (when ADMIN_TOKEN is configured)
    """
    client_host = request.client.host if request.client else ""
    is_local = client_host in _LOCAL_HOSTS
    has_admin = bool(settings.admin_token) and (
        request.headers.get("X-Admin-Token") == settings.admin_token
    )
    if not (is_local or has_admin):
        raise HTTPException(status_code=403, detail="inbox 仅限本机或管理员")

    try:
        payload = await request.json()
    except Exception:
        return error_response("请求体不是合法 JSON", status_code=400)
    note = str(payload.get("note", "")).strip()
    prediction_date = str(payload.get("prediction_date", "")).strip()
    if not (note and prediction_date):
        return error_response("缺少 note 或 prediction_date", status_code=400)
    target = get_daily_prediction(prediction_date)
    if target is None:
        return error_response("未找到该日期的预测", status_code=404)
    appended = (target.calibration_note + "\n[外部评论] " + note).strip()
    target.calibration_note = appended[:2000]
    from storage.record_manager import save_daily_prediction
    save_daily_prediction(target)
    await event_hub.publish("prediction_commentary", target.model_dump(mode="json"))
    return success_response({"prediction_date": prediction_date, "appended": True})


# ----- Notifications -----------------------------------------------------------

@app.get("/api/notifications/channels")
def list_channels():
    return success_response({
        "configured": broadcast_manager.configured_channels(),
        "available": [c.name for c in broadcast_manager.channels],
    })


@app.post("/api/notifications/test")
async def test_notification(request: Request):
    if not settings.allow_test_notify:
        raise HTTPException(status_code=403, detail="测试推送未开启")
    _check_admin(request)
    event = BroadcastEvent(
        type="test",
        title="Aurumers · 测试推送",
        body="如果你看到这条消息，说明推送通道已成功打通。",
        payload={"sent_at": datetime.now().isoformat(timespec="seconds")},
    )
    results = broadcast_manager.dispatch(event)
    return success_response({"results": results})


# ----- Auth / 用户体系 (task #62) ---------------------------------------------

def _public_user(user: dict) -> dict:
    """剔除敏感字段(password_hash),供前端展示。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "status": user["status"],
        "balance_cents": user["balance_cents"],
        "daily_free_cents": user.get("daily_free_cents"),
        "created_at": user["created_at"],
    }


def _seed_admin() -> None:
    """配置了 ADMIN_PASSWORD 且管理员账号不存在时创建之。"""
    if not settings.admin_password:
        return
    if auth_store.get_user_by_username(settings.admin_username) is None:
        auth_store.create_user(
            settings.admin_username,
            auth_utils.hash_password(settings.admin_password),
            role="admin",
        )
        logger.info("seeded admin user: %s", settings.admin_username)


def _validate_credentials(body: dict) -> tuple[str, str]:
    username = str((body or {}).get("username", "")).strip()
    password = str((body or {}).get("password", ""))
    if not (3 <= len(username) <= 32) or not username.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="用户名需 3-32 位字母/数字/下划线")
    if not (6 <= len(password) <= 128):
        raise HTTPException(status_code=400, detail="密码需 6-128 位")
    return username, password


@app.post("/api/auth/register")
async def auth_register(request: Request, response: Response):
    if not settings.enable_registration:
        raise HTTPException(status_code=403, detail="注册已关闭")
    ip = request.client.host if request.client else "?"
    if auth_utils.register_rate_limited(ip):
        raise HTTPException(status_code=429, detail="注册过于频繁,请稍后再试")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    username, password = _validate_credentials(body)
    if auth_store.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    user = auth_store.create_user(username, auth_utils.hash_password(password), role="user")
    token = auth_utils.new_session_token()
    auth_store.create_session(user["id"], token, settings.session_ttl_hours * 3600)
    auth_utils.set_session_cookie(response, token)
    auth_utils.record_register(ip)
    return success_response(_public_user(user))


@app.post("/api/auth/login")
async def auth_login(request: Request, response: Response):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    username = str((body or {}).get("username", "")).strip()
    password = str((body or {}).get("password", ""))
    ip = request.client.host if request.client else "?"
    key = f"{ip}:{username}"
    if auth_utils.login_rate_limited(key):
        raise HTTPException(status_code=429, detail="登录失败次数过多,请稍后再试")
    user = auth_store.get_user_by_username(username)
    if user is None or not auth_utils.verify_password(user["password_hash"], password):
        auth_utils.record_login_fail(key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已停用")
    auth_utils.clear_login_fails(key)
    token = auth_utils.new_session_token()
    auth_store.create_session(user["id"], token, settings.session_ttl_hours * 3600)
    auth_utils.set_session_cookie(response, token)
    return success_response(_public_user(user))


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get(auth_utils.SESSION_COOKIE)
    if token:
        auth_store.delete_session(token)
    auth_utils.clear_session_cookie(response)
    return success_response({"ok": True})


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = auth_utils.require_user(request)
    today = datetime.now().strftime("%Y-%m-%d")
    usage = auth_store.get_today_usage(user["id"], today)
    free_limit = user.get("daily_free_cents")
    if free_limit is None:
        free_limit = settings.free_daily_cents
    data = _public_user(user)
    data["today_cost_cents"] = usage["cost_cents"]
    data["daily_free_limit_cents"] = free_limit
    data["free_remaining_cents"] = max(0, free_limit - usage["cost_cents"])
    return success_response(data)


@app.post("/api/auth/password")
async def auth_change_password(request: Request):
    """用户自助改密码(需验证旧密码)。"""
    user = auth_utils.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    old_pw = str((body or {}).get("old_password", ""))
    new_pw = str((body or {}).get("new_password", ""))
    if not (6 <= len(new_pw) <= 128):
        raise HTTPException(status_code=400, detail="新密码需 6-128 位")
    fresh = auth_store.get_user_by_id(user["id"])
    if not fresh or not auth_utils.verify_password(fresh["password_hash"], old_pw):
        raise HTTPException(status_code=401, detail="旧密码错误")
    auth_store.set_user_password(user["id"], auth_utils.hash_password(new_pw))
    return success_response({"ok": True})


@app.delete("/api/auth/account")
async def auth_delete_account(request: Request, response: Response):
    """用户自助注销:停用账号 + 清所有会话,停用后无法再登录。"""
    user = auth_utils.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    auth_store.update_user_fields(user["id"], status="disabled")
    auth_store.delete_user_sessions(user["id"])
    auth_utils.clear_session_cookie(response)
    return success_response({"ok": True})


# ----- 钱包 (task #62 阶段4) --------------------------------------------------

@app.get("/api/wallet")
async def wallet_info(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    fresh = auth_store.get_user_by_id(user["id"]) or user
    usage = auth_store.get_today_usage(user["id"], datetime.now().strftime("%Y-%m-%d"))
    free_limit = fresh.get("daily_free_cents")
    if free_limit is None:
        free_limit = settings.free_daily_cents
    return success_response({
        "balance_cents": fresh["balance_cents"],
        "today_cost_cents": round(usage["cost_cents"], 4),
        "daily_free_limit_cents": free_limit,
        "free_remaining_cents": max(0.0, free_limit - usage["cost_cents"]),
    })


@app.post("/api/wallet/redeem")
async def wallet_redeem(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    code = str((body or {}).get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=400, detail="请输入兑换码")
    ok, result = auth_store.redeem_code(code, user["id"])
    if not ok:
        raise HTTPException(status_code=400, detail=str(result))
    fresh = auth_store.get_user_by_id(user["id"])
    return success_response({"added_cents": result, "balance_cents": fresh["balance_cents"]})


# ----- 管理后台 (task #62 阶段5) ----------------------------------------------

def _require_admin_state(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    _require_admin_state(request)
    return success_response([_public_user(u) for u in auth_store.list_users()])


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    """管理员创建用户。"""
    _require_admin_state(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    username, password = _validate_credentials(body)
    if auth_store.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    role = "admin" if (body or {}).get("role") == "admin" else "user"
    user = auth_store.create_user(username, auth_utils.hash_password(password), role=role)
    return success_response(_public_user(user))


@app.patch("/api/admin/users/{uid}")
async def admin_update_user(uid: str, request: Request):
    """管理员改用户:role/status/额度/余额,以及重置密码(password)。"""
    _require_admin_state(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    changed = False
    pw = (body or {}).get("password")
    if pw:
        if not (6 <= len(str(pw)) <= 128):
            raise HTTPException(status_code=400, detail="密码需 6-128 位")
        auth_store.set_user_password(uid, auth_utils.hash_password(str(pw)))
        changed = True
    fields = {k: body[k] for k in ("role", "status", "daily_free_cents", "balance_cents") if k in body}
    if fields:
        auth_store.update_user_fields(uid, **fields)
        changed = True
    if not changed:
        raise HTTPException(status_code=400, detail="无可更新字段")
    fresh = auth_store.get_user_by_id(uid)
    if not fresh:
        raise HTTPException(status_code=404, detail="用户不存在")
    return success_response(_public_user(fresh))


@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: str, request: Request):
    """管理员注销用户:软删(停用 + 清会话),不能删自己。"""
    admin = _require_admin_state(request)
    if uid == admin["id"]:
        raise HTTPException(status_code=400, detail="不能注销自己")
    if auth_store.get_user_by_id(uid) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    auth_store.update_user_fields(uid, status="disabled")
    auth_store.delete_user_sessions(uid)
    return success_response({"ok": True})


@app.get("/api/admin/codes")
async def admin_list_codes(request: Request):
    _require_admin_state(request)
    return success_response(auth_store.list_redemption_codes())


@app.post("/api/admin/codes")
async def admin_create_codes(request: Request):
    _require_admin_state(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    cents = int((body or {}).get("cents", 0))
    count = int((body or {}).get("count", 1))
    if cents <= 0 or not (1 <= count <= 100):
        raise HTTPException(status_code=400, detail="参数无效(cents>0, 1<=count<=100)")
    import secrets as _secrets
    codes = []
    for _ in range(count):
        code = "AUR-" + _secrets.token_hex(6).upper()
        auth_store.create_redemption_code(code, cents)
        codes.append(code)
    return success_response({"codes": codes, "cents": cents})


# ----- Hermes chat ------------------------------------------------------------

CHAT_MAX_INPUT_LEN = 4000
CHAT_MAX_MESSAGES_PER_SESSION = 200


def _validate_client_id(client_id: str | None) -> str:
    if not client_id or len(client_id) < 8 or len(client_id) > 128:
        raise HTTPException(status_code=400, detail="缺少有效 client_id")
    return client_id


def _require_uid(request: Request) -> str:
    """多租户隔离:从登录会话取 user_id(中间件已保证 /api/chat/* 需登录)。
    chat 一律按 user_id 隔离,不再接受前端自报的 client_id。"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user["id"]


def _ensure_session_owned(session_id: str, user_id: str):
    session = get_chat_session(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    return session


@app.get("/api/chat/sessions")
def chat_list_sessions(request: Request):
    cid = _require_uid(request)
    return success_response([s.model_dump(mode="json") for s in list_chat_sessions(cid)])


@app.post("/api/chat/sessions")
async def chat_create_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    cid = _require_uid(request)
    title = (body.get("title") if isinstance(body, dict) else None) or "新对话"
    session_id = str(uuid.uuid4())
    session = create_chat_session(session_id, cid, str(title)[:64])
    return success_response(session.model_dump(mode="json"))


@app.delete("/api/chat/sessions/{session_id}")
def chat_delete_session(session_id: str, request: Request):
    cid = _require_uid(request)
    if archive_chat_session(session_id, cid):
        return success_response({"archived": True, "session_id": session_id})
    return error_response("会话不存在或不属于当前用户", status_code=404)


@app.get("/api/chat/sessions/{session_id}/messages")
def chat_list_messages(session_id: str, request: Request):
    cid = _require_uid(request)
    _ensure_session_owned(session_id, cid)
    return success_response([m.model_dump(mode="json") for m in list_chat_messages(session_id, cid)])


async def _gather_chat_context() -> tuple[dict, "DailyPrediction | None", dict, list[dict]]:
    """Pull market snapshot + latest prediction + accuracy + news without blocking the event loop.

    Each underlying call wraps either requests.get() or sqlite — all sync — so we
    push them to worker threads and gather concurrently.
    """
    market_t = asyncio.to_thread(get_market_snapshot)
    pred_t = asyncio.to_thread(get_latest_daily_prediction)
    acc_t = asyncio.to_thread(compute_accuracy, "30d")
    news_t = asyncio.to_thread(get_gold_news, 5)
    market, prediction, accuracy_obj, news_items = await asyncio.gather(
        market_t, pred_t, acc_t, news_t,
    )
    accuracy = accuracy_obj.model_dump(mode="json")
    news = [n.model_dump(mode="json") for n in (news_items or [])]
    return market, prediction, accuracy, news


@app.get("/api/chat/runtime")
async def chat_runtime():
    return success_response(await get_runtime_status())


@app.get("/api/chat/greeting")
async def chat_greeting():
    market, prediction, accuracy, news = await _gather_chat_context()
    greeting = build_greeting(market=market, prediction=prediction, accuracy=accuracy, news=news)
    return success_response(greeting.model_dump(mode="json"))


@app.post("/api/chat/sessions/{session_id}/message")
async def chat_post_message(
    session_id: str,
    request: Request,
):
    from fastapi.responses import StreamingResponse
    from schemas import ChatRole

    cid = _require_uid(request)
    session = _ensure_session_owned(session_id, cid)

    if count_chat_messages(session_id) >= CHAT_MAX_MESSAGES_PER_SESSION:
        raise HTTPException(status_code=409, detail="该会话已达消息上限，请新建对话")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    content_raw = (body or {}).get("content")
    if not isinstance(content_raw, str):
        raise HTTPException(status_code=400, detail="content 必须是字符串")
    content = content_raw.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容为空")
    if len(content) > CHAT_MAX_INPUT_LEN:
        raise HTTPException(status_code=413, detail=f"消息超过 {CHAT_MAX_INPUT_LEN} 字符上限")

    user = getattr(request.state, "user", None)
    if user:
        billing.assert_can_spend(user)  # 额度/余额不足 → 402

    history = await asyncio.to_thread(
        list_chat_messages, session_id, cid, CHAT_MAX_MESSAGES_PER_SESSION
    )
    is_first_message = session.message_count == 0

    user_msg = await asyncio.to_thread(
        append_chat_message,
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        role=ChatRole.USER,
        content=content,
    )

    market, prediction, accuracy, news = await _gather_chat_context()
    prediction_dump = prediction.model_dump(mode="json") if prediction else None
    system_text = build_system_message(
        market=market, prediction=prediction_dump, accuracy=accuracy, news=news,
    )

    accumulator: list[str] = []

    async def streamer():
        try:
            async for chunk in stream_reply(
                system_text=system_text,
                history=history,
                user_input=content,
                session_id=session_id,
                client_id=cid,
            ):
                accumulator.append(chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            logger.exception("chat stream failed mid-flight")
            tail = "（连接异常，部分内容已截断）"
            accumulator.append(tail)
            yield tail
        finally:
            full_reply = "".join(accumulator).strip()
            if not full_reply:
                full_reply = "（暂无回复）"
            try:
                await asyncio.to_thread(
                    append_chat_message,
                    message_id=str(uuid.uuid4()),
                    session_id=session_id,
                    role=ChatRole.ASSISTANT,
                    content=full_reply,
                )
                if is_first_message:
                    title = await summarize_session_title_async(content)
                    await asyncio.to_thread(
                        update_chat_session_title, session_id, cid, title,
                    )
                if user:
                    billing.charge(user, settings.model_name, content, full_reply)
            except Exception:
                logger.exception("chat persistence failed")

    return StreamingResponse(
        streamer(),
        # Was text/plain; GZipMiddleware buffered it → users saw 8s freeze
        # then full-dump (round-5 audit CRITICAL). Starlette excludes
        # text/event-stream from gzip, so switching the media_type fixes
        # progressive delivery without disabling gzip for other responses.
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Aurumers-User-Message-Id": user_msg.id,
        },
    )


# ----- SSE stream --------------------------------------------------------------

# SSE 全局并发上限(task #62 阶段6,防连接耗尽 DoS)
_SSE_MAX = 64
_sse_state = {"n": 0}


@app.get("/api/stream")
async def stream(request: Request):
    if _sse_state["n"] >= _SSE_MAX:
        raise HTTPException(status_code=503, detail="实时连接数已满,请稍后重试")
    queue = await event_hub.subscribe()
    _sse_state["n"] += 1

    async def event_source():
        try:
            yield f": connected at {datetime.now().isoformat(timespec='seconds')}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: {message['type']}\n" \
                          f"data: {json.dumps(message['payload'], ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _sse_state["n"] -= 1
            await event_hub.unsubscribe(queue)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
