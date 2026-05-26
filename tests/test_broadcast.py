import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from chains.broadcast import (
    BroadcastManager,
    EmailBroadcaster,
    FeishuBroadcaster,
    TelegramBroadcaster,
    WeComBroadcaster,
    WebhookBroadcaster,
)
from schemas import BroadcastEvent


class BroadcastTests(unittest.TestCase):
    def _event(self) -> BroadcastEvent:
        return BroadcastEvent(type="test", title="T", body="B")

    def test_no_channels_configured_dispatch_silent(self):
        manager = BroadcastManager()
        with patch.dict(os.environ, {
            "WEBHOOK_URLS": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "FEISHU_WEBHOOK_URL": "",
            "WECOM_KEY": "",
            "EMAIL_SMTP_HOST": "",
        }, clear=False):
            results = manager.dispatch(self._event())
        self.assertEqual(results, {})

    def test_webhook_configured_sends(self):
        with patch.dict(os.environ, {"WEBHOOK_URLS": "https://example.test/hook"}, clear=False):
            broadcaster = WebhookBroadcaster()
            self.assertTrue(broadcaster.is_configured())
            with patch("chains.broadcast.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)
                ok = broadcaster.send(self._event())
        self.assertTrue(ok)
        mock_post.assert_called_once()

    def test_webhook_failure_returns_false_but_does_not_raise(self):
        with patch.dict(os.environ, {"WEBHOOK_URLS": "https://example.test/hook"}, clear=False):
            broadcaster = WebhookBroadcaster()
            with patch("chains.broadcast.requests.post", side_effect=ConnectionError("nope")):
                ok = broadcaster.send(self._event())
        self.assertFalse(ok)

    def test_telegram_requires_token_and_chat(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": ""}, clear=False):
            self.assertFalse(TelegramBroadcaster().is_configured())
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "1"}, clear=False):
            self.assertTrue(TelegramBroadcaster().is_configured())

    def test_email_requires_all_keys(self):
        partial = {
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_SMTP_USER": "u",
            "EMAIL_SMTP_PASS": "p",
        }
        with patch.dict(os.environ, partial, clear=False):
            self.assertFalse(EmailBroadcaster().is_configured())
        full = {**partial, "EMAIL_FROM": "f@x", "EMAIL_TO": "t@x"}
        with patch.dict(os.environ, full, clear=False):
            self.assertTrue(EmailBroadcaster().is_configured())


if __name__ == "__main__":
    unittest.main()
