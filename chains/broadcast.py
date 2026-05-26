from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Protocol

import requests

from schemas import BroadcastEvent


logger = logging.getLogger(__name__)


class Broadcaster(Protocol):
    name: str

    def is_configured(self) -> bool: ...
    def send(self, event: BroadcastEvent) -> bool: ...


def _bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _format_text(event: BroadcastEvent) -> str:
    parts = [f"【{event.title}】", event.body.strip()]
    if event.payload:
        parts.append("--")
        for k, v in event.payload.items():
            parts.append(f"{k}: {v}")
    return "\n".join(parts)


def _is_safe_outbound_url(url: str) -> bool:
    """Reject local-only / non-http schemes to mitigate SSRF abuse.

    Blocks loopback, private, link-local and reserved IP ranges across both
    IPv4 and IPv6, plus DNS host names that resolve to those ranges via the
    obvious string forms (`localhost`, `*.local`, etc.). Hostnames that need
    DNS resolution are accepted on-trust here — operator-controlled config.
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False

    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname (DNS lookup not performed). Operator-controlled — allow.
        return True
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    return True


class WebhookBroadcaster:
    name = "webhook"

    def is_configured(self) -> bool:
        return bool((os.getenv("WEBHOOK_URLS") or "").strip())

    def send(self, event: BroadcastEvent) -> bool:
        urls = [u.strip() for u in (os.getenv("WEBHOOK_URLS") or "").split(",") if u.strip()]
        if not urls:
            return False
        ok = True
        for url in urls:
            if not _is_safe_outbound_url(url):
                logger.warning("webhook delivery skipped (unsafe url): %s", url)
                ok = False
                continue
            try:
                requests.post(
                    url,
                    json=event.model_dump(mode="json"),
                    timeout=5,
                )
            except Exception:
                logger.warning("webhook delivery failed url=%s", url, exc_info=True)
                ok = False
        return ok


class TelegramBroadcaster:
    name = "telegram"

    def is_configured(self) -> bool:
        return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    def send(self, event: BroadcastEvent) -> bool:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return False
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": _format_text(event)},
                timeout=8,
            )
            return True
        except Exception:
            logger.warning("telegram delivery failed", exc_info=True)
            return False


class FeishuBroadcaster:
    name = "feishu"

    def is_configured(self) -> bool:
        return bool(os.getenv("FEISHU_WEBHOOK_URL"))

    def send(self, event: BroadcastEvent) -> bool:
        url = os.getenv("FEISHU_WEBHOOK_URL")
        if not url:
            return False
        try:
            requests.post(
                url,
                json={"msg_type": "text", "content": {"text": _format_text(event)}},
                timeout=5,
            )
            return True
        except Exception:
            logger.warning("feishu delivery failed", exc_info=True)
            return False


class WeComBroadcaster:
    name = "wecom"

    def is_configured(self) -> bool:
        return bool(os.getenv("WECOM_KEY"))

    def send(self, event: BroadcastEvent) -> bool:
        key = os.getenv("WECOM_KEY")
        if not key:
            return False
        try:
            requests.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}",
                json={"msgtype": "text", "text": {"content": _format_text(event)}},
                timeout=5,
            )
            return True
        except Exception:
            logger.warning("wecom delivery failed", exc_info=True)
            return False


class EmailBroadcaster:
    name = "email"

    def is_configured(self) -> bool:
        return all(
            os.getenv(k)
            for k in (
                "EMAIL_SMTP_HOST",
                "EMAIL_SMTP_USER",
                "EMAIL_SMTP_PASS",
                "EMAIL_FROM",
                "EMAIL_TO",
            )
        )

    def send(self, event: BroadcastEvent) -> bool:
        host = os.getenv("EMAIL_SMTP_HOST")
        port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        user = os.getenv("EMAIL_SMTP_USER")
        password = os.getenv("EMAIL_SMTP_PASS")
        sender = os.getenv("EMAIL_FROM")
        recipient = os.getenv("EMAIL_TO")
        if not (host and user and password and sender and recipient):
            return False
        msg = MIMEText(_format_text(event), "plain", "utf-8")
        msg["Subject"] = event.title
        msg["From"] = sender
        msg["To"] = recipient
        try:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.sendmail(sender, [recipient], msg.as_string())
            return True
        except Exception:
            logger.warning("email delivery failed", exc_info=True)
            return False


_DEFAULT_CHANNELS: list[Broadcaster] = [
    WebhookBroadcaster(),
    TelegramBroadcaster(),
    FeishuBroadcaster(),
    WeComBroadcaster(),
    EmailBroadcaster(),
]


class BroadcastManager:
    def __init__(self, channels: list[Broadcaster] | None = None):
        self.channels = channels if channels is not None else _DEFAULT_CHANNELS

    def configured_channels(self) -> list[str]:
        return [c.name for c in self.channels if c.is_configured()]

    def dispatch(self, event: BroadcastEvent) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for channel in self.channels:
            if not channel.is_configured():
                continue
            try:
                results[channel.name] = channel.send(event)
            except Exception:
                logger.exception("broadcast channel %s raised", channel.name)
                results[channel.name] = False
        if not results:
            logger.info("broadcast: no channels configured (event=%s)", event.type)
        return results


broadcast_manager = BroadcastManager()


__all__ = [
    "Broadcaster",
    "WebhookBroadcaster",
    "TelegramBroadcaster",
    "FeishuBroadcaster",
    "WeComBroadcaster",
    "EmailBroadcaster",
    "BroadcastManager",
    "broadcast_manager",
]
