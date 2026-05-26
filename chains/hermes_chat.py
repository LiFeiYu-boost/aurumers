"""Hermes 对话 chain：优先走真 Hermes Agent（local api_server），fallback 到 LangChain 直连 + mock。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import AsyncIterable, Iterable

from config import settings
from prompts.hermes_persona import (
    HERMES_SYSTEM,
    SUMMARY_PROMPT_TEMPLATE,
    build_context_block,
)
from schemas import ChatGreeting, ChatMessage, ChatRole, DailyPrediction


HERMES_API_BASE = os.getenv("HERMES_API_BASE", "http://127.0.0.1:8642/v1")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "local-aurumers-bridge")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes-agent")
_HERMES_HEALTH_URL = HERMES_API_BASE.rstrip("/").removesuffix("/v1") + "/health"
_HERMES_HEALTH_TTL = 30      # /health 端点便宜，30s 缓存
_HERMES_INFER_TTL = 300      # 真推理探针 5min 缓存（避免空打 token）
_HERMES_INFER_TIMEOUT = 8.0  # 探针超时；真聊天用更长 timeout
_hermes_health: dict[str, float | bool] = {"ok": False, "checked_at": 0.0}
_hermes_infer: dict[str, float | bool] = {"ok": False, "checked_at": 0.0}


# Roughly 6k Chinese chars ≈ ≤10k tokens, leaves headroom for system prompt + reply.
HISTORY_CHAR_BUDGET = 6000

# Coarse output filter: things Hermes should never end up echoing.
_OUTPUT_DENYLIST = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}|api[_\-]?key\s*[:=]|bearer\s+[a-zA-Z0-9]|/etc/|systemctl\b|nginx\s+-s|"
    r"\bssh\s+root@|drop\s+table\b|truncate\s+table\b|\.env\s*[:=]|chmod\s+\+x\b)",
    re.IGNORECASE,
)


def _scrub_output(text: str) -> str:
    if not text:
        return text
    if _OUTPUT_DENYLIST.search(text):
        return _OUTPUT_DENYLIST.sub("（该内容已被 Hermes 过滤）", text)
    return text


def _trim_history_to_budget(history: Iterable[ChatMessage]) -> list[ChatMessage]:
    """Walk newest → oldest and keep messages while staying within HISTORY_CHAR_BUDGET."""
    items = list(history)
    kept_reverse: list[ChatMessage] = []
    used = 0
    for msg in reversed(items):
        cost = len(msg.content or "")
        if kept_reverse and used + cost > HISTORY_CHAR_BUDGET:
            break
        kept_reverse.append(msg)
        used += cost
    kept_reverse.reverse()
    return kept_reverse


logger = logging.getLogger(__name__)


def _build_llm():
    """Fallback LangChain client when Hermes Agent gateway is unreachable."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        temperature=0.3,
        streaming=True,
    )


async def _hermes_health_only() -> bool:
    """便宜的 /health 探测，30s 缓存。"""
    now = time.time()
    if now - float(_hermes_health.get("checked_at", 0.0)) < _HERMES_HEALTH_TTL:
        return bool(_hermes_health.get("ok"))
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(_HERMES_HEALTH_URL)
        ok = r.status_code == 200
    except Exception:
        ok = False
    _hermes_health.update({"ok": ok, "checked_at": now})
    return ok


async def _hermes_inference_probe() -> bool:
    # /health 200 但 provider 拒绝（如 free tier 耗尽 / API key 失效）会让聊天静默 fallback —
    # 必须实际打一次推理才能区分这种降级。5min 缓存控成本。
    now = time.time()
    if now - float(_hermes_infer.get("checked_at", 0.0)) < _HERMES_INFER_TTL:
        return bool(_hermes_infer.get("ok"))
    ok = False
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=HERMES_API_KEY,
            base_url=HERMES_API_BASE,
            timeout=_HERMES_INFER_TIMEOUT,
        )
        resp = await client.chat.completions.create(
            model=HERMES_MODEL,
            messages=[{"role": "user", "content": "."}],
            max_tokens=1,
            stream=False,
        )
        ok = bool(getattr(resp, "choices", None))
    except Exception:
        ok = False
    _hermes_infer.update({"ok": ok, "checked_at": now})
    return ok


async def _hermes_is_alive() -> bool:
    """Hermes 真活 = /health 通过 AND 真推理通过。"""
    if not await _hermes_health_only():
        return False
    return await _hermes_inference_probe()


async def _stream_via_hermes(
    *,
    system_text: str,
    history: list[ChatMessage],
    user_input: str,
    session_id: str,
    client_id: str,
) -> AsyncIterable[str]:
    """Stream tokens from Hermes Agent's OpenAI-compatible api_server.

    Honors X-Hermes-Session-Id (session continuity) + X-Hermes-Session-Key
    (cross-session long-term memory scoping).
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=HERMES_API_KEY, base_url=HERMES_API_BASE)
    messages = [{"role": "system", "content": system_text}]
    for msg in history:
        if msg.role is ChatRole.USER:
            messages.append({"role": "user", "content": msg.content})
        elif msg.role is ChatRole.ASSISTANT:
            messages.append({"role": "assistant", "content": msg.content})
    messages.append({"role": "user", "content": user_input})

    stream = await client.chat.completions.create(
        model=HERMES_MODEL,
        messages=messages,
        stream=True,
        temperature=0.3,
        extra_headers={
            "X-Hermes-Session-Id": f"web_{session_id}",
            "X-Hermes-Session-Key": f"client_{client_id}",
        },
    )
    async for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (IndexError, AttributeError):
            delta = None
        if delta:
            yield _scrub_output(delta)


def build_system_message(*, market: dict, prediction: dict | None, accuracy: dict, news: list[dict]) -> str:
    context = build_context_block(market=market, prediction=prediction, accuracy=accuracy, news=news)
    return f"{HERMES_SYSTEM}\n\n{context}"


def _to_lc_messages(system_text: str, history: Iterable[ChatMessage]):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages = [SystemMessage(content=system_text)]
    for msg in history:
        if msg.role is ChatRole.ASSISTANT:
            messages.append(AIMessage(content=msg.content))
        elif msg.role is ChatRole.USER:
            messages.append(HumanMessage(content=msg.content))
        # SYSTEM messages from history are intentionally ignored to prevent injection
    return messages


async def stream_reply(
    *,
    system_text: str,
    history: list[ChatMessage],
    user_input: str,
    session_id: str = "default",
    client_id: str = "anonymous",
) -> AsyncIterable[str]:
    """Yields assistant reply tokens.

    Order of preference:
      1. MOCK_LLM=1 → deterministic mock stream (tests / no-network)
      2. Hermes Agent gateway at HERMES_API_BASE → real Hermes loop
      3. Fallback: LangChain ChatOpenAI direct to DashScope (only when Hermes is down,
         so chat doesn't hard-fail; UI gets a flag from /api/chat/runtime)
    """
    if settings.mock_llm:
        async for chunk in _mock_stream(user_input):
            yield chunk
        return

    trimmed_history = _trim_history_to_budget(history)

    if await _hermes_is_alive():
        try:
            async for chunk in _stream_via_hermes(
                system_text=system_text,
                history=trimmed_history,
                user_input=user_input,
                session_id=session_id,
                client_id=client_id,
            ):
                yield chunk
            return
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            logger.exception("Hermes gateway streaming failed; falling back to LangChain direct")
            _hermes_health["ok"] = False
            _hermes_infer["ok"] = False
            # fall through to LangChain fallback

    # Fallback path — direct to DashScope via LangChain
    from langchain_core.messages import HumanMessage

    llm = _build_llm()
    messages = _to_lc_messages(system_text, trimmed_history) + [HumanMessage(content=user_input)]
    try:
        async for chunk in llm.astream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                yield _scrub_output(text)
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception:
        logger.exception("Fallback LangChain streaming failed")
        yield "（抱歉，刚刚和模型通信时出现问题，请稍后再试一次。）"


async def _mock_stream(user_input: str) -> AsyncIterable[str]:
    """Deterministic mock streaming so frontend works without a real LLM."""
    import asyncio

    text = (
        "（Mock 模式占位）这是 Hermes 的演示回复。\n"
        f"我看到你刚才说：「{user_input.strip()[:80]}」。\n"
        "在真实模型接入后，我会基于平台采集的金价、新闻和每日预测给出可追溯的中文回答；\n"
        "现在仅作为前端联调使用。"
    )
    for word in re.split(r"(\s+|，|。)", text):
        if word:
            yield word
            await asyncio.sleep(0.02)


async def summarize_session_title_async(first_message: str) -> str:
    """Async wrapper — runs the (synchronous) LLM call in a worker thread."""
    return await asyncio.to_thread(summarize_session_title, first_message)


def summarize_session_title(first_message: str) -> str:
    """Generate a ≤16-char Chinese title for the chat session. Best-effort."""
    cleaned = first_message.strip().replace("\n", " ")
    if not cleaned:
        return "新对话"

    # Mock or fallback path: trim user input itself.
    if settings.mock_llm:
        return _trim_title(cleaned)

    try:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.model_name,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=15,
            max_retries=0,
            temperature=0.0,
            max_tokens=32,
        )
        from langchain_core.prompts import ChatPromptTemplate

        chain = (
            ChatPromptTemplate.from_template(SUMMARY_PROMPT_TEMPLATE)
            | llm
            | StrOutputParser()
        )
        title = chain.invoke({"first_message": cleaned[:200]})
        return _trim_title(title)
    except Exception:
        logger.warning("title summarization failed, falling back", exc_info=True)
        return _trim_title(cleaned)


def _trim_title(text: str) -> str:
    cleaned = (text or "").strip().strip("「」\"' .。!？?:：·-").replace("\n", " ")
    # Strip C0 controls + bidi/RTL overrides + invisible chars that could spoof titles.
    cleaned = re.sub(r"[\x00-\x1f‪-‮⁦-⁩﻿]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "新对话"
    if len(cleaned) > 16:
        cleaned = cleaned[:16]
    return cleaned


async def get_runtime_status() -> dict:
    """Used by /api/chat/runtime so UI can show 'Hermes 真机' vs '降级'."""
    if settings.mock_llm:
        return {"backend": "mock", "hermes_alive": False, "model": "mock"}
    health_ok = await _hermes_health_only()
    infer_ok = await _hermes_inference_probe() if health_ok else False
    alive = health_ok and infer_ok
    return {
        "backend": "hermes" if alive else "fallback",
        "hermes_alive": alive,
        "hermes_health_ok": health_ok,
        "hermes_inference_ok": infer_ok,
        "model": HERMES_MODEL if alive else settings.model_name,
        "base_url": HERMES_API_BASE if alive else settings.dashscope_base_url,
    }


def build_greeting(*, market: dict, prediction: DailyPrediction | None, accuracy: dict, news: list[dict]) -> ChatGreeting:
    """Compose the standard opening message — no LLM call, fully deterministic."""
    market_lines: list[str] = []
    price = market.get("price_value") or market.get("price_raw")
    label = market.get("data_label") or "—"
    stamp = market.get("data_timestamp") or "—"
    if price is not None:
        market_lines.append(f"COMEX 黄金 {price}（{label}，截至 {stamp} 北京时间）")
    if prediction:
        sge = prediction.today_close_sge
        comex = prediction.today_close_comex
        market_lines.append(
            f"今日 SGE 收盘 {sge if sge is not None else '—'} CNY/g · "
            f"今日 COMEX 收盘 {comex if comex is not None else '—'} USD/oz"
        )
        market_lines.append(
            f"最新每日预测（{prediction.prediction_date}）：明日 {prediction.tomorrow_direction.value}"
            f"（置信 {(prediction.tomorrow_confidence or 0) * 100:.0f}%）"
        )

    market_summary = "\n".join(market_lines) or "暂时还没拉到有效行情。"

    suggested = [
        "今日金价整体怎么看？",
        "明日预测背后的逻辑是什么？",
        "网站上哪里能看历史命中率？",
    ]

    opening = (
        "你好，我是 Aurumers 的对话助手 Hermes。👋\n\n"
        f"{market_summary}\n\n"
        "我可以帮你解读最新行情、解释每日预测的依据、带你熟悉网站的几个页面。"
        "你也可以直接点下面任一个建议问题开聊。"
    )

    return ChatGreeting(
        market_summary=market_summary,
        latest_prediction=prediction,
        suggested_questions=suggested,
        opening_message=opening,
    )
