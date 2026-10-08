"""Local integration tests against a mock backend, NOT a NAS or tailnet."""
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KEY = "abcdef0123456789" * 4  # Public fixture, never a deployment credential.


class Backend(http.server.BaseHTTPRequestHandler):
    headers_seen = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).headers_seen = dict(self.headers)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "should-not-leak=yes")
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "test-model"}]}).encode())

    def do_POST(self):
        type(self).headers_seen = dict(self.headers)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(body) if body else {}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
        self.end_headers()
        if payload.get("stream"):
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n')
            self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')


@unittest.skipUnless(shutil.which("nginx"), "nginx binary required")
class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ugreen-proxy-test-")
        cls.directory = Path(cls.tmp.name)
        cls.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}"
        text = (ROOT / "config/nginx.conf.in").read_text()
        for name, value in {"CFG_DIR": cls.tmp.name, "RUN_DIR": cls.tmp.name,
                            "GATEWAY_PORT": str(cls.backend.server_port), "PROXY_PORT": str(port)}.items():
            text = text.replace("@@" + name + "@@", value)
        (cls.directory / "nginx.conf").write_text(text)
        (cls.directory / "auth.conf").write_text(
            'map $http_authorization $inference_authorized {\n default 0;\n'
            f' "~^(?i:Bearer) {KEY}$" 1;\n}}\n')
        cls.log = (cls.directory / "test.log").open("w+")
        cls.process = subprocess.Popen([shutil.which("nginx"), "-e", "stderr", "-p", cls.tmp.name,
                                        "-c", str(cls.directory / "nginx.conf"),
                                        "-g", "daemon off; master_process off;"],
                                       stdout=cls.log, stderr=cls.log)
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            cls.log.seek(0)
            raise RuntimeError("nginx did not start: " + cls.log.read())
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.log.close()
        cls.tmp.cleanup()

    def request(self, path="/v1/models", method="GET", key=KEY, data=None, extra=None):
        headers = {} if key is None else {"Authorization": "Bearer " + key}
        headers.update(extra or {})
        if data is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_no_key(self):
        status, headers, _ = self.request(key=None)
        self.assertEqual(status, 401)
        self.assertIn("Bearer", headers["WWW-Authenticate"])

    def test_wrong_key(self):
        self.assertEqual(self.request(key="wrong")[0], 401)

    def test_case_changed_key(self):
        self.assertEqual(self.request(key=KEY.upper())[0], 401)

    def test_lowercase_scheme(self):
        self.assertEqual(self.request(extra={"Authorization": "bearer " + KEY})[0], 200)

    def test_models(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"][0]["id"], "test-model")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_chat(self):
        status, _, body = self.request("/v1/chat/completions", "POST", data={"messages": []})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["choices"][0]["message"]["content"], "ok")

    def test_event_stream_transport(self):
        status, headers, body = self.request("/v1/chat/completions", "POST", data={"stream": True})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn(b"data: [DONE]", body)

    def test_no_other_routes(self):
        for path in ("/health", "/v1/embeddings", "/v1/responses", "/admin", "/v1/models/"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_no_other_methods(self):
        for path, method in (("/v1/models", "POST"), ("/v1/models", "HEAD"),
                             ("/v1/models", "DELETE"), ("/v1/chat/completions", "GET")):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.request(path, method)[0], 405)

    def test_auth_and_cookies_not_forwarded(self):
        status, headers, _ = self.request(extra={"Cookie": "private=example"})
        self.assertEqual(status, 200)
        lowered = {k.lower(): v for k, v in Backend.headers_seen.items()}
        self.assertNotIn("authorization", lowered)
        self.assertNotIn("cookie", lowered)
        self.assertNotIn("Set-Cookie", headers)

    def test_request_size_limit(self):
        # An oversized declared body is rejected without sending the payload.
        self.assertEqual(self.request("/v1/chat/completions", "POST",
                                     extra={"Content-Length": str(9 * 1024 * 1024)})[0], 413)


class StaticTests(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(ROOT / "scripts/install-proxy.sh")], check=True)

    def test_no_automatic_publication(self):
        script = (ROOT / "scripts/install-proxy.sh").read_text()
        self.assertNotIn("tailscale serve --", script)
        self.assertNotIn("tailscale funnel", script)

    def test_client_rejects_plain_http(self):
        result = subprocess.run(["python3", str(ROOT / "scripts/test-client.py"),
                                 "--base-url", "http://example.com/v1"], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"HTTPS", result.stderr)


if __name__ == "__main__":
    unittest.main()
