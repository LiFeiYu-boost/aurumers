import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("SCHEDULER_DAILY_ENABLED", "0")


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import storage.record_manager as record_manager

        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "chat.db"
        self.original_db = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()
        self.record_manager = record_manager

        from app import app
        self.client = TestClient(app)
        self.client_id = "client-aaaa-bbbb-cccc-dddd-eeee"

    def tearDown(self):
        self.record_manager.DB_PATH = self.original_db
        self.temp_dir.cleanup()

    def test_greeting_returns_payload(self):
        with patch("chains.daily_runner.get_gold_news", return_value=[]):
            res = self.client.get("/api/chat/greeting").json()
        self.assertTrue(res["success"], res.get("error"))
        self.assertIn("opening_message", res["data"])
        self.assertIn("suggested_questions", res["data"])

    def test_create_list_session(self):
        create_res = self.client.post("/api/chat/sessions", json={"client_id": self.client_id}).json()
        self.assertTrue(create_res["success"])
        session_id = create_res["data"]["id"]
        self.assertEqual(create_res["data"]["client_id"], self.client_id)

        list_res = self.client.get(f"/api/chat/sessions?client_id={self.client_id}").json()
        self.assertTrue(list_res["success"])
        self.assertEqual(len(list_res["data"]), 1)
        self.assertEqual(list_res["data"][0]["id"], session_id)

    def test_session_idor_blocked(self):
        # Create session under client A
        a = self.client.post("/api/chat/sessions", json={"client_id": "client-aaaa-bbbb-cccc-dddd-eeee"}).json()
        session_id = a["data"]["id"]
        # Client B tries to read messages — must 404
        res = self.client.get(
            f"/api/chat/sessions/{session_id}/messages?client_id=client-XXXX-YYYY-ZZZZ-1111-2222"
        )
        self.assertEqual(res.status_code, 404)
        # Client B tries to delete — must 404
        del_res = self.client.delete(
            f"/api/chat/sessions/{session_id}?client_id=client-XXXX-YYYY-ZZZZ-1111-2222"
        )
        body = del_res.json()
        self.assertFalse(body["success"])

    def test_message_too_long_rejected(self):
        sid = self.client.post("/api/chat/sessions", json={"client_id": self.client_id}).json()["data"]["id"]
        big = "x" * 4001
        res = self.client.post(
            f"/api/chat/sessions/{sid}/message?client_id={self.client_id}",
            json={"content": big},
        )
        self.assertEqual(res.status_code, 413)

    def test_empty_message_rejected(self):
        sid = self.client.post("/api/chat/sessions", json={"client_id": self.client_id}).json()["data"]["id"]
        res = self.client.post(
            f"/api/chat/sessions/{sid}/message?client_id={self.client_id}",
            json={"content": "   "},
        )
        self.assertEqual(res.status_code, 400)

    def test_streaming_persists_messages(self):
        with patch("chains.daily_runner.get_gold_news", return_value=[]):
            sid = self.client.post(
                "/api/chat/sessions",
                json={"client_id": self.client_id},
            ).json()["data"]["id"]
            with self.client.stream(
                "POST",
                f"/api/chat/sessions/{sid}/message?client_id={self.client_id}",
                json={"content": "金价怎么看？"},
            ) as response:
                self.assertEqual(response.status_code, 200)
                body = ""
                for chunk in response.iter_text():
                    body += chunk
            self.assertGreater(len(body), 0)

        msgs = self.client.get(f"/api/chat/sessions/{sid}/messages?client_id={self.client_id}").json()
        self.assertTrue(msgs["success"])
        self.assertEqual(len(msgs["data"]), 2)
        self.assertEqual(msgs["data"][0]["role"], "user")
        self.assertEqual(msgs["data"][0]["content"], "金价怎么看？")
        self.assertEqual(msgs["data"][1]["role"], "assistant")
        self.assertGreater(len(msgs["data"][1]["content"]), 0)

    def test_delete_archives_session(self):
        sid = self.client.post("/api/chat/sessions", json={"client_id": self.client_id}).json()["data"]["id"]
        del_res = self.client.delete(f"/api/chat/sessions/{sid}?client_id={self.client_id}").json()
        self.assertTrue(del_res["success"])
        listed = self.client.get(f"/api/chat/sessions?client_id={self.client_id}").json()
        self.assertEqual(len(listed["data"]), 0)

    def test_invalid_client_id_rejected(self):
        res = self.client.get("/api/chat/sessions?client_id=short")
        self.assertEqual(res.status_code, 400)
        # Header path also rejects short id
        res2 = self.client.get(
            "/api/chat/sessions",
            headers={"X-Aurumers-Client-Id": "x"},
        )
        self.assertEqual(res2.status_code, 400)
        # Header takes precedence — valid header should win even if query is short
        res3 = self.client.get(
            "/api/chat/sessions?client_id=short",
            headers={"X-Aurumers-Client-Id": self.client_id},
        )
        self.assertEqual(res3.status_code, 200)


if __name__ == "__main__":
    unittest.main()
