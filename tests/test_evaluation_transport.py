"""Offline HTTP transport boundaries; no provider SDK or test runner dependency."""
from __future__ import annotations

import io
import json
import socket
import traceback
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from scripts.evaluation.runner import RequestFailure, post_json


class EvaluationTransportTests(unittest.TestCase):
    URL = "http://offline.invalid/api/v1/ai/analyze"
    SECRET = "sk-TRANSPORT_BODY_AND_KEY_CANARY"

    def setUp(self):
        blocked = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        blocked.start()
        self.addCleanup(blocked.stop)

    @staticmethod
    def mock_response(body):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        return response

    def assert_safe_failure(self, expected, *, body=None, error=None):
        response = self.mock_response(body)
        output = io.StringIO()
        with patch("scripts.evaluation.runner.urlopen", return_value=response, side_effect=error) as opening:
            with redirect_stdout(output), redirect_stderr(output):
                try:
                    post_json(self.URL, {"complaint": self.SECRET, "ruleResults": []}, 2.5)
                except RequestFailure as exc:
                    self.assertEqual(str(exc), expected)
                    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                    self.assertNotIn(self.SECRET, str(exc))
                    self.assertNotIn(self.SECRET, repr(exc))
                    self.assertNotIn(self.SECRET, rendered)
                else:
                    self.fail("Expected a safe transport failure")
        opening.assert_called_once()
        self.assertNotIn(self.SECRET, output.getvalue())

    def test_success_decodes_utf8_and_sends_expected_json_request(self):
        payload = {"complaint": "오프라인 요청", "ruleResults": []}
        expected = {"tags": [], "metadata": {"modelName": "offline", "note": "한글 응답"}}
        response = self.mock_response(json.dumps(expected, ensure_ascii=False).encode("utf-8"))
        with patch("scripts.evaluation.runner.urlopen", return_value=response) as opening:
            self.assertEqual(post_json(self.URL, payload, 2.5), expected)
        opening.assert_called_once()
        request = opening.call_args.args[0]
        self.assertEqual(request.full_url, self.URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), payload)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(opening.call_args.kwargs, {"timeout": 2.5})
        response.__exit__.assert_called_once()

    def test_broken_json_does_not_expose_response_or_request(self):
        body = ('{"apiKey": "' + self.SECRET + '", "unfinished":').encode("utf-8")
        self.assert_safe_failure("invalid_json", body=body)

    def test_invalid_utf8_does_not_expose_response_or_request(self):
        self.assert_safe_failure("invalid_json", body=self.SECRET.encode("utf-8") + b"\xff")

    def test_non_object_json_is_rejected(self):
        for value in ([{"apiKey": self.SECRET}], self.SECRET, 42, None):
            with self.subTest(json_type=type(value).__name__):
                self.assert_safe_failure("response_not_object", body=json.dumps(value).encode("utf-8"))

    def test_url_error_does_not_expose_upstream_exception(self):
        self.assert_safe_failure("connection_or_timeout", error=URLError(self.SECRET))

    def test_timeout_does_not_expose_upstream_exception(self):
        self.assert_safe_failure("connection_or_timeout", error=TimeoutError(self.SECRET))

    def test_os_error_does_not_expose_upstream_exception(self):
        self.assert_safe_failure("connection_or_timeout", error=ConnectionResetError(self.SECRET))

    def test_http_error_records_only_status_code(self):
        error = HTTPError(self.URL, 502, self.SECRET, {}, io.BytesIO(self.SECRET.encode("utf-8")))
        self.addCleanup(error.close)
        self.assert_safe_failure("http_502", error=error)


if __name__ == "__main__":
    unittest.main()
