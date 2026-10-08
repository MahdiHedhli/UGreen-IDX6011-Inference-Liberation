#!/usr/bin/env python3
"""Test auth, route restrictions, model discovery, and one synthetic completion."""
import argparse
import getpass
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MODEL = "Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a credential to a redirect destination.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTPS base URL ending in /v1")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urllib.parse.urlsplit(base)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path != "/v1"):
        parser.error("Use an HTTPS URL ending in /v1, without credentials, query, or fragment.")
    if not 1 <= args.timeout <= 1800:
        parser.error("Timeout must be between 1 and 1800 seconds.")
    if not sys.stdin.isatty():
        parser.error("Run in an interactive terminal so the API key can be entered without echo.")
    key = getpass.getpass("UGREEN API key (hidden): ")
    if not key or any(c.isspace() for c in key):
        parser.error("An API key without whitespace is required.")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def request(path, method="GET", token=None, payload=None):
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=args.timeout) as response:
                return response.status, response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(4096)

    for label, path, method, token, expected in [
        ("No key rejected", "/models", "GET", None, 401),
        ("Wrong key rejected", "/models", "GET", key + "invalid", 401),
        ("Unlisted route rejected", "/not-allowed", "GET", key, 404),
        ("Wrong method rejected", "/models", "POST", key, 405),
    ]:
        status, _ = request(path, method, token)
        if status != expected:
            raise RuntimeError(f"{label}: expected HTTP {expected}, received {status}.")
        print(f"PASS: {label} (HTTP {status})")
    status, body = request("/models", token=key)
    if status != 200:
        raise RuntimeError(f"Model discovery returned HTTP {status}.")
    catalog = json.loads(body)
    models = catalog.get("data", [])
    if not any(m.get("id") == args.model for m in models if isinstance(m, dict)):
        raise RuntimeError("Configured model is not in the catalog. Check its exact ID.")
    print(f"PASS: /v1/models (HTTP 200, {len(models)} catalog entries, configured model present)")
    status, body = request("/chat/completions", "POST", key, {
        "model": args.model,
        "messages": [{"role": "user", "content": "Reply with exactly: Tailscale inference is working."}],
        "max_tokens": 512, "stream": False,
    })
    if status != 200:
        raise RuntimeError(f"Chat completion returned HTTP {status}.")
    completion = json.loads(body)
    choices = completion.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("HTTP 200 but no final text. Inspect reasoning/token limits separately.")
    print("PASS: /v1/chat/completions (HTTP 200, non-empty final text)")
    print("Reply:", content[:500])
    print("Authenticated inference test succeeded. Streaming, tools, and vision are separate tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
