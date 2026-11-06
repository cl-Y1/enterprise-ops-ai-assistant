"""企业智能运维知识助手 V1.2 自动化测试。

这些测试不会访问真实 Dify，而是模拟 Dify 的响应，用来验证：
- 请求地址、Header 和请求体是否符合官方 API 契约；
- conversation_id 是否在多轮对话中正确传递；
- 点赞/点踩的 content 是否正确拼接；
- 重复反馈、超时、错误 Key、空回答等异常是否被正确处理；
- API Key 是否可能出现在 HTML、JS 或错误响应中。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

import app as app_module

MESSAGE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MESSAGE_ID_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_ID_2 = "22222222-2222-4222-8222-222222222222"
TEST_KEY = "test-key-not-a-real-secret"


def make_response(status: int = 200, payload: dict | None = None) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    return response


class AssistantTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = app_module.create_app(
            {
                "TESTING": True,
                "DIFY_API_KEY": TEST_KEY,
                "DIFY_API_BASE_URL": "https://dify.example.test/v1",
                "DIFY_USER_ID": "test-user-001",
                "DIFY_TIMEOUT": 2,
                "MAX_QUERY_LENGTH": 2000,
                "MAX_COMMENT_LENGTH": 300,
            }
        )
        self.client = self.app.test_client()

    def post_chat(self, query: str = "CBS 与 TDH 数量不一致怎么排查？", conversation_id: str = ""):
        return self.client.post(
            "/api/chat",
            json={"query": query, "conversation_id": conversation_id},
        )

    def post_feedback(self, **overrides):
        payload = {"message_id": MESSAGE_ID, "rating": "like"}
        payload.update(overrides)
        return self.client.post("/api/feedback", json=payload)

    # ---------- 页面与安全 ----------

    def test_homepage_renders_without_api_key(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("企业智能运维知识助手", body)
        self.assertIn("提交反馈", body)
        self.assertNotIn(TEST_KEY, body)

    def test_frontend_assets_do_not_contain_api_key(self) -> None:
        for path in ("/static/js/app.js", "/static/css/style.css"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(TEST_KEY, response.get_data(as_text=True))
            response.close()

    def test_security_headers_and_no_store_for_api(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_health_only_reports_configured_boolean(self) -> None:
        response = self.client.get("/api/health")
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["configured"])
        self.assertNotIn("api_key", data)
        self.assertNotIn(TEST_KEY, response.get_data(as_text=True))

    # ---------- 聊天 ----------

    @patch("app.requests.post")
    def test_chat_contract_and_new_conversation(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(
            200,
            {
                "answer": "建议先核对 CBS 与 TDH 的统计口径……",
                "conversation_id": CONVERSATION_ID,
                "message_id": MESSAGE_ID,
            },
        )

        response = self.post_chat()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["conversation_id"], CONVERSATION_ID)
        self.assertEqual(data["message_id"], MESSAGE_ID)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://dify.example.test/v1/chat-messages")
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TEST_KEY}")
        self.assertEqual(kwargs["json"]["response_mode"], "blocking")
        self.assertEqual(kwargs["json"]["user"], "test-user-001")
        self.assertEqual(kwargs["json"]["inputs"], {})
        self.assertNotIn("conversation_id", kwargs["json"])
        self.assertEqual(kwargs["timeout"], (5, 2.0))

    @patch("app.requests.post")
    def test_multi_turn_reuses_conversation_id(self, mock_post: Mock) -> None:
        mock_post.side_effect = [
            make_response(
                200,
                {
                    "answer": "第一轮回答",
                    "conversation_id": CONVERSATION_ID,
                    "message_id": MESSAGE_ID,
                },
            ),
            make_response(
                200,
                {
                    "answer": "第二轮回答",
                    "conversation_id": CONVERSATION_ID,
                    "message_id": MESSAGE_ID_2,
                },
            ),
        ]

        first = self.post_chat("第一个问题")
        self.assertEqual(first.status_code, 200)
        second = self.post_chat("第二个问题", CONVERSATION_ID)
        self.assertEqual(second.status_code, 200)

        second_payload = mock_post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_payload["conversation_id"], CONVERSATION_ID)
        self.assertEqual(second_payload["query"], "第二个问题")

    @patch("app.requests.post")
    def test_chat_timeout_returns_chinese_error(self, mock_post: Mock) -> None:
        mock_post.side_effect = requests.Timeout("secret internal detail")
        response = self.post_chat()
        self.assertEqual(response.status_code, 504)
        body = response.get_data(as_text=True)
        self.assertIn("响应超时", body)
        self.assertNotIn("secret internal detail", body)

    @patch("app.requests.post")
    def test_chat_connection_error(self, mock_post: Mock) -> None:
        mock_post.side_effect = requests.ConnectionError("internal host 10.0.0.8")
        response = self.post_chat()
        self.assertEqual(response.status_code, 502)
        body = response.get_data(as_text=True)
        self.assertIn("无法连接", body)
        self.assertNotIn("10.0.0.8", body)

    @patch("app.requests.post")
    def test_chat_auth_error_does_not_leak_key(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(
            401,
            {"code": "unauthorized", "message": f"Invalid key {TEST_KEY}"},
        )
        response = self.post_chat()
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertIn("鉴权失败", body)
        self.assertNotIn(TEST_KEY, body)

    @patch("app.requests.post")
    def test_chat_empty_answer_is_rejected(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(
            200,
            {
                "answer": "   ",
                "conversation_id": CONVERSATION_ID,
                "message_id": MESSAGE_ID,
            },
        )
        response = self.post_chat()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["code"], "empty_answer")

    @patch("app.requests.post")
    def test_chat_invalid_conversation_id_rejected_before_request(self, mock_post: Mock) -> None:
        response = self.post_chat(conversation_id="not-a-uuid")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_conversation")
        mock_post.assert_not_called()

    def test_chat_empty_query_rejected(self) -> None:
        response = self.post_chat("   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "empty_query")

    def test_chat_missing_key_returns_configuration_hint(self) -> None:
        app = app_module.create_app({"TESTING": True, "DIFY_API_KEY": ""})
        client = app.test_client()
        response = client.post("/api/chat", json={"query": "测试问题"})
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertIn("尚未完成配置", body)
        self.assertNotIn("sk-", body)

    # ---------- 反馈 ----------

    @patch("app.requests.post")
    def test_like_feedback_contract_and_success_message(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(200, {"result": "success"})
        response = self.post_feedback()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], "感谢你的认可！")

        args, kwargs = mock_post.call_args
        self.assertEqual(
            args[0],
            f"https://dify.example.test/v1/messages/{MESSAGE_ID}/feedbacks",
        )
        self.assertEqual(kwargs["json"], {"rating": "like", "user": "test-user-001"})
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TEST_KEY}")

    @patch("app.requests.post")
    def test_dislike_feedback_combines_reason_and_comment(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(200, {"result": "success"})
        response = self.post_feedback(
            rating="dislike",
            reason="答案不准确",
            comment="缺少 Service 日志检查步骤",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["message"],
            "感谢反馈，我们将持续优化知识助手。",
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["rating"], "dislike")
        self.assertEqual(
            payload["content"],
            "反馈原因：答案不准确；补充说明：缺少 Service 日志检查步骤",
        )

    @patch("app.requests.post")
    def test_dislike_without_comment(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(200, {"result": "success"})
        response = self.post_feedback(rating="dislike", reason="没有解决我的问题")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["content"],
            "反馈原因：没有解决我的问题",
        )

    def test_dislike_requires_valid_reason(self) -> None:
        missing = self.post_feedback(rating="dislike")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()["code"], "invalid_reason")

        invalid = self.post_feedback(rating="dislike", reason="随便写的")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["code"], "invalid_reason")

    @patch("app.requests.post")
    def test_duplicate_feedback_is_not_sent_twice(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(200, {"result": "success"})
        first = self.post_feedback(rating="like")
        second = self.post_feedback(rating="dislike", reason="答案不准确")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(mock_post.call_count, 1)

    def test_invalid_message_id_rejected(self) -> None:
        response = self.post_feedback(message_id="../../etc/passwd")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_message_id")

    def test_comment_too_long_rejected(self) -> None:
        response = self.post_feedback(
            rating="dislike",
            reason="其他",
            comment="测" * 301,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "comment_too_long")

    @patch("app.requests.post")
    def test_feedback_timeout_releases_reservation(self, mock_post: Mock) -> None:
        mock_post.side_effect = [
            requests.Timeout("slow"),
            make_response(200, {"result": "success"}),
        ]
        first = self.post_feedback(rating="like")
        self.assertEqual(first.status_code, 504)

        # 第一次超时不应占用该消息，用户可以重试。
        second = self.post_feedback(rating="like")
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.get_json().get("duplicate", False))
        self.assertEqual(mock_post.call_count, 2)

    @patch("app.requests.post")
    def test_feedback_404_is_safe(self, mock_post: Mock) -> None:
        mock_post.return_value = make_response(
            404,
            {"code": "not_found", "message": "Message Not Exists."},
        )
        response = self.post_feedback(rating="like")
        self.assertEqual(response.status_code, 404)
        self.assertIn("反馈记录已失效", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
