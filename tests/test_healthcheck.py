import datetime as dt
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from healthcheck.core import (UTC, MAX_RESPONSE_BYTES, ResponseTooLarge, clean_record, http_post,
    interpret_response, load_config, probe, read_json, request_spec, run_probes, save_results,
    timestamp, window_stats)
from healthcheck.site import ROOT, build_demo, build_site

NOW = dt.datetime(2026, 10, 6, 12, tzinfo=UTC)
KEY = "sk-test-secret-DO-NOT-PUBLISH"


def record(model="model-1", when=NOW, status="success", reason="ok", **kwargs):
    return {"model": model, "checked_at": timestamp(when), "status": status, "reason": reason,
            "latency_ms": 100, "http_status": 200, "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}, **kwargs}


def response(protocol):
    if protocol == "messages":
        return {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "OK"}], "usage": {"input_tokens": 8, "output_tokens": 2}}
    if protocol == "responses":
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
                "usage": {"input_tokens": 8, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 1}}}
    return {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {"prompt_tokens": 8, "completion_tokens": 2}}


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config" / "models.json")
        self.env = patch.dict(os.environ, {"ANYROUTER_API_KEY": KEY})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_three_protocols_send_bounded_requests_and_parse_usage(self):
        for protocol in ("messages", "responses", "chat_completions"):
            model = next(model for model in self.config["models"] if model["protocol"] == protocol)
            url, headers, body = request_spec(self.config, model, KEY)
            self.assertIn(KEY, headers["Authorization"])
            payload = json.loads(body)
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["model"], model["id"])
            self.assertTrue(any(key in payload for key in ("max_tokens", "max_output_tokens", "max_completion_tokens")))
            output = probe(self.config, model, lambda *args: (200, json.dumps(response(protocol)).encode()), NOW)
            self.assertEqual(output["status"], "success")
            self.assertEqual(output["usage"]["total_tokens"], 10)
            self.assertNotIn(KEY, json.dumps(output))

    def test_semantic_failures_even_with_http_200(self):
        cases = [
            ("chat_completions", {"choices": [{"message": {"role": "assistant", "content": " "}}]}, "empty_response"),
            ("messages", {"type": "message", "role": "assistant", "content": []}, "empty_response"),
            ("responses", {"status": "completed", "output": [{"type": "reasoning", "summary": []}]}, "empty_response"),
            ("responses", {"status": "incomplete", "output": [], "incomplete_details": {"reason": "max_output_tokens"}}, "incomplete_response"),
            ("messages", {"success": True}, "invalid_response"),
            ("messages", {"content": "wrong"}, "invalid_response"),
        ]
        for protocol, payload, reason in cases:
            with self.subTest(reason=reason):
                output = interpret_response(protocol, 200, json.dumps(payload).encode())
                self.assertEqual(output[:2], ("failure", reason))
        self.assertEqual(interpret_response("messages", 200, b"<html>OK</html>")[:2], ("failure", "invalid_json"))

    def test_error_categories_and_no_error_text_disclosure(self):
        for code, error, expected in [
            (401, {"error": {"message": KEY}}, ("account_restricted", "invalid_api_key")),
            (403, {"error": "permission denied"}, ("account_restricted", "permission_denied")),
            (429, {"error": "limited"}, ("account_restricted", "rate_limited")),
            (200, {"error": {"message": "余额不足 " + KEY}}, ("account_restricted", "quota_exceeded")),
            (500, {"error": KEY}, ("failure", "upstream_error")),
            (400, {"error": "unsupported parameter"}, ("failure", "invalid_request")),
            (400, {"error": "Only Claude Code clients are allowed " + KEY}, ("account_restricted", "client_restricted")),
            (403, {"error": "请使用 Claude Code"}, ("account_restricted", "client_restricted")),
            (400, {"error": "无可用渠道"}, ("failure", "model_unavailable")),
            (400, {"error": "model_not_found"}, ("failure", "model_unavailable")),
            (404, {"error": "model not found"}, ("failure", "endpoint_or_model_not_found")),
        ]:
            result = interpret_response("messages", code, json.dumps(error).encode())
            self.assertEqual(result[:2], expected)
            self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(interpret_response("messages", 403, b"<html>WAF</html>")[:2], ("failure", "access_denied"))

    def test_network_timeout_and_local_error_are_distinct(self):
        for error, expected in [(TimeoutError(), ("failure", "timeout")), (OSError(KEY), ("failure", "network_error")),
                                (ResponseTooLarge(), ("failure", "response_too_large")), (RuntimeError(KEY), ("unknown", "monitor_error"))]:
            def transport(*args):
                raise error
            result = probe(self.config, self.config["models"][0], transport, NOW)
            self.assertEqual((result["status"], result["reason"]), expected)
            self.assertNotIn(KEY, json.dumps(result))

    def test_partial_model_failure_does_not_drop_healthy_models(self):
        config = {**self.config, "models": self.config["models"][:3]}
        def transport(url, headers, raw, timeout):
            payload = json.loads(raw)
            if payload["model"] == "gpt-6-astra":
                return 502, b'{"error":"upstream"}'
            protocol = next(model["protocol"] for model in config["models"] if model["id"] == payload["model"])
            return 200, json.dumps(response(protocol)).encode()
        results = run_probes(config, transport=transport)
        self.assertEqual([value["status"] for value in results], ["success", "failure", "success"])

    def test_missing_key_does_not_make_a_request(self):
        with patch.dict(os.environ, {"ANYROUTER_API_KEY": ""}):
            result = probe(self.config, self.config["models"][0], lambda *args: self.fail("No request expected"), NOW)
            self.assertEqual(result["status"], "unknown")
            with self.assertRaises(ValueError):
                run_probes(self.config, transport=lambda *args: self.fail("No request expected"))

    def test_config_rejects_unbounded_budget_and_duplicate_models(self):
        for mutation in (lambda c: c["models"].append(c["models"][0]), lambda c: c["models"][0].update(parameters={}),
                         lambda c: c.update(base_url="http://example.com"), lambda c: c["models"][0].update(parameters={"max_output_tokens": 32, "stream": True})):
            config = json.loads(json.dumps(self.config))
            mutation(config)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(path)


class StorageTests(unittest.TestCase):
    def test_retention_preserves_old_daily_summaries_and_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            old = record(when=NOW - dt.timedelta(days=91))
            new = record(when=NOW)
            save_results(data, [old, new], 90, NOW)
            self.assertFalse((data / "history" / "2026-07-07.json").exists())
            self.assertTrue((data / "summaries" / "2026-07-07.json").exists())
            summary = read_json(data / "summaries" / "2026-07-07.json")
            self.assertEqual(summary["models"]["model-1"]["success"], 1)
            self.assertEqual(read_json(data / "latest.json")["model-1"], new)
            # Re-running persistence for the same sample is idempotent.
            save_results(data, [new], 90, NOW)
            self.assertEqual(len(read_json(data / "history" / "2026-10-06.json")["checks"]), 1)

    def test_restricted_calls_count_as_non_success_but_missing_samples_do_not(self):
        values = [record(when=NOW-dt.timedelta(minutes=45)), record(when=NOW-dt.timedelta(minutes=15), status="account_restricted", reason="rate_limited"),
                  record(when=NOW, status="unknown", reason="monitor_error")]
        stats = window_stats(values, NOW, 24, 15, timestamp(NOW-dt.timedelta(minutes=45)))
        self.assertEqual(stats["success_rate"], 50)
        self.assertEqual(stats["attempts"], 2)
        self.assertEqual(stats["coverage"], 50)
        self.assertEqual(stats["expected_samples"], 4)

    def test_public_build_sanitizes_fields_and_marks_stale(self):
        config = load_config(ROOT / "config" / "models.json")
        with tempfile.TemporaryDirectory() as directory:
            data, output = Path(directory) / "data", Path(directory) / "public"
            value = record(model=config["models"][0]["id"], when=NOW-dt.timedelta(minutes=31), raw_response=KEY, headers={"Authorization": KEY})
            save_results(data, [value], 90, NOW)
            manifest = build_site(config, data, output, NOW)
            self.assertEqual(manifest["models"][0]["current_status"], "unknown")
            self.assertEqual(manifest["models"][0]["latest"]["status"], "success")
            self.assertEqual(len(manifest["models"]), 17)
            self.assertFalse(manifest["is_demo"])
            for path in output.rglob("*.json"):
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"))
                self.assertNotIn("raw_response", path.read_text(encoding="utf-8"))

    def test_empty_site_does_not_manufacture_healthy_status(self):
        config = load_config(ROOT / "config" / "models.json")
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_site(config, Path(directory) / "data", Path(directory) / "public", NOW)
            self.assertTrue(all(model["current_status"] == "unknown" for model in manifest["models"]))
            self.assertTrue(all(model["stats"]["24"]["success_rate"] is None for model in manifest["models"]))
            self.assertEqual(manifest["history"], [])

    def test_demo_is_marked_and_does_not_make_network_calls(self):
        config = load_config(ROOT / "config" / "models.json")
        with tempfile.TemporaryDirectory() as directory, patch("healthcheck.core.http_post", side_effect=AssertionError("Demo must not call API")):
            output = Path(directory) / "preview"
            build_demo(config, output)
            self.assertTrue(read_json(output / "data" / "status.json")["is_demo"])


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                cls.requests.append(self.path)
                self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/should-not-be-called")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.path == "/oversized":
                    self.send_response(200)
                    self.send_header("Content-Length", str(MAX_RESPONSE_BYTES + 1))
                    self.end_headers()
                elif self.path == "/slow":
                    time.sleep(1.4)
                    try:
                        self.send_response(200)
                        self.send_header("Content-Length", "2")
                        self.end_headers()
                        self.wfile.write(b"{}")
                    except OSError:
                        pass
                else:
                    raw = json.dumps(response("messages")).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
            def log_message(self, *args):
                pass
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_real_transport_handles_success_without_following_redirects(self):
        code, raw = http_post(self.url + "/ok", {"Content-Type": "application/json"}, b"{}", 2)
        self.assertEqual(interpret_response("messages", code, raw)[0], "success")
        code, _ = http_post(self.url + "/redirect", {}, b"{}", 2)
        self.assertEqual(code, 302)
        self.assertNotIn("/should-not-be-called", self.requests)

    def test_total_timeout_and_response_size_limit(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            http_post(self.url + "/slow", {}, b"{}", 1)
        self.assertLess(time.monotonic() - start, 1.3)
        with self.assertRaises(ResponseTooLarge):
            http_post(self.url + "/oversized", {}, b"{}", 2)


if __name__ == "__main__":
    unittest.main()
