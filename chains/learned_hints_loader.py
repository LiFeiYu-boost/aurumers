"""Read Hermes-authored hint files and inject them into the daily prompt.

This is the closing half of the loop SKILL.md describes:
  Hermes 周日反思 → 写 hint .md → daily_prompt 读 hint → 模型看见经验

Until this module shipped, that loop dead-ended at the file write — the
prompt never read the directory, so anything Hermes "learned" was invisible
to the next prediction. Now the bottom-3-by-mtime hints are summarised in
under 1 KB and pasted under a "## 来自周日反思的经验提示" heading.

Hard caps (intentional, prevent prompt-bloat / accidental sensitive leak):
- max 3 files
- max 300 chars per file
- only files matching ``*.md`` directly in HINT_DIR (no recursion)

Prompt-injection defence:
- Each hint is wrapped in a delimited envelope (HINT_BEGIN / HINT_END).
- A blocklist regex strips override-style phrases ("忽略之前所有规则",
  "ignore all previous instructions", role-tag tokens like ``<|im_start|>``,
  ``<system>``, ``</system>``) BEFORE rendering. These don't belong in
  pattern hints, so dropping them never destroys signal.
- DAILY_RULES instructs the model to treat the envelope contents as data,
  not instructions. The combination makes hint files much less dangerous
  if Hermes itself is ever compromised.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path


logger = logging.getLogger(__name__)

HINT_DIR = Path(os.environ.get("AURUMERS_SKILL_HINT_DIR", "/root/.hermes/skills/gold_buy_predictor/hints"))
MAX_HINTS = 3
# Bumped 300 → 1200 in round-3 audit: SKILL.md tells Hermes "≤300 字"
# (Chinese chars ≈ 900 UTF-8 chars), but the loader was counting bytes-ish
# chars. Real Hermes weekly hints came in at 600-900 chars and got
# truncated mid-rule, dropping the most actionable directive (e.g.
# "强制 prob_flat = 0"). 1200 leaves a safety margin while still keeping
# total injection budget ≤ 3600 chars (~3 % of 65k context).
MAX_CHARS_PER_HINT = 1200

EMPTY_TEXT = "暂无积累（Hermes 周日反思尚未生成 hint 文件）"

# Phrases that, in a hint file, only make sense if someone is trying to override
# the system prompt. The Chinese verbs cover synonyms (忽略/无视/忽视/丢弃/抛弃/
# 忘记/抛开/不遵守) within a short distance of "rule/instruction" nouns
# (规则/指令/铁律/准则/约束/提示/prompt). English mirrors that span.
# .{0,12} between verb and noun catches "请抛弃 前面 所有 准则" without
# matching benign sentences that mention "规则" 20 chars later.
# Single hybrid pattern covers cross-language attacks like "ignore 以下所有
# 提示词" or "无视 above rules" — verb + noun lists are unioned across both
# languages. The bridge between verb and noun is up to 40 chars *on the same
# line* (the [^\n] class forbids crossing newlines — this is what limits the
# blast radius; legitimate sentences with both keywords are usually on
# different lines).
_INJECTION_PATTERNS = [
    # Verb-first (SVO): "ignore the rules" / "无视上述规定"
    re.compile(
        r"(忽略|无视|忽视|丢弃|抛弃|忘记|抛开|不遵守|不要遵守|不再遵守|跳过"
        r"|覆盖|作废|不再适用|抛诸脑后|脑后|废除|取消"
        r"|ignore|disregard|override|forget|bypass|skip|cancel|nullify|void)"
        r"[^\n]{0,40}?"
        r"(规则|指令|铁律|准则|约束|规定|提示词|提示|要求|条款|限制"
        r"|rules?|instructions?|prompts?|directives?|guidelines?|system"
        r"|previous|prior|above|earlier|said|told|preceding)",
        re.IGNORECASE,
    ),
    # Noun-first (Chinese SOV): "规则都作废" / "准则被忽略".
    # Deliberately narrow:
    #   - noun list omits 提示/要求/条款/限制 — too common in legitimate
    #     金融 hint text ("止损要求"、"约束限制" 等)
    #   - verb list omits 失效/过时/不再有效/不再适用 — these legitimately
    #     describe historical observation ("某指令在 high-vol regime 下过时")
    #     and erasing them was self-DOS on the hint loop's own signal
    #   - bridge tightened to {0,8} so only adjacent SOV phrases match
    re.compile(
        r"(规则|指令|铁律|准则|规定)"
        r"[^\n]{0,8}?"
        r"(作废|废除|被取消|被忽略|无须遵守|不必遵守)",
    ),
    re.compile(r"</?system>", re.IGNORECASE),
    re.compile(r"</?user>", re.IGNORECASE),
    re.compile(r"</?assistant>", re.IGNORECASE),
    re.compile(r"<\|im_(start|end|sep)\|>", re.IGNORECASE),
    re.compile(r"\[\[?(SYSTEM|INST|/INST)\]?\]", re.IGNORECASE),
    # Self-fence: if a hint file's body contains the very delimiters we use
    # to wrap them, a partial render could close the fence early and the
    # remainder of the hint becomes "outside the envelope". Strip these
    # markers before injection — hints never legitimately reference them.
    re.compile(r"<<\s*HERMES_HINT_(BEGIN|END)\s*>>", re.IGNORECASE),
]


def _sanitize(text: str) -> str:
    for pat in _INJECTION_PATTERNS:
        text = pat.sub("[已剔除可疑指令]", text)
    return text


def _truncate(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def load_recent_hints(
    limit: int = MAX_HINTS,
    char_limit: int = MAX_CHARS_PER_HINT,
) -> str:
    """Return a multi-line string of the N most recent hint files, wrapped
    in a HINT_BEGIN / HINT_END envelope and stripped of injection attempts.

    Format (when hints exist)::
        <<HERMES_HINT_BEGIN>>
        - [YYYY-MM-DD] <truncated body>
        - [YYYY-MM-DD] <truncated body>
        <<HERMES_HINT_END>>

    Empty / missing dir → returns ``EMPTY_TEXT`` (no envelope, just the
    fallback string). Callers should not need to special-case this.
    """
    # Everything that stats the directory or its entries lives in one try:
    # Path.is_dir() re-raises EACCES (only ENOENT/ENOTDIR-style errors return
    # False), and the sort key stats each file. Under systemd ProtectHome the
    # whole subtree is EACCES — that must degrade to EMPTY_TEXT, not crash the
    # daily run (seen in prod: PermissionError escaping run_daily_prediction).
    try:
        if not HINT_DIR.is_dir():
            return EMPTY_TEXT
        files = [p for p in HINT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".md"]
        # Primary: newest mtime first. Secondary: filename desc (so "03-…" beats
        # "01-…" when Hermes writes all 3 in the same epoch second — without
        # this tiebreak, iterdir() order is filesystem-defined and could promote
        # an arbitrary hint, round-3 audit LOW).
        files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    except OSError as exc:
        logger.warning("learned_hints: scan failed dir=%s err=%s", HINT_DIR, exc)
        return EMPTY_TEXT
    if not files:
        return EMPTY_TEXT
    selected = files[: max(1, limit)]

    lines: list[str] = []
    for path in selected:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("learned_hints: read failed path=%s err=%s", path, exc)
            continue
        try:
            mtime = path.stat().st_mtime
            from datetime import datetime
            date_label = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except OSError:
            date_label = "unknown"
        sanitized = _sanitize(body)
        snippet = _truncate(sanitized, char_limit)
        if not snippet:
            continue
        lines.append(f"- [{date_label}] {snippet}")

    if not lines:
        return EMPTY_TEXT
    return "<<HERMES_HINT_BEGIN>>\n" + "\n".join(lines) + "\n<<HERMES_HINT_END>>"
