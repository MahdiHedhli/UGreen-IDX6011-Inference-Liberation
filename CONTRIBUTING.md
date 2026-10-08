# Contributing

Useful contributions include firmware compatibility reports, clearer installation instructions, and narrowly scoped security improvements. Do not report a capability as tested solely because it appears in a model catalog.

## Compatibility report

Include:

- NAS model and memory, firmware/AI package versions, and model ID.
- Worker fingerprint, gateway discovery method, and Tailscale version.
- Which tests passed: direct loopback chat, local authenticated proxy, remote authenticated chat, streaming, vision, tools, restart, or firmware upgrade.
- Test origin and sanitized HTTP status/output. Distinguish mock testing from real hardware testing.

Do not include credentials, personal tailnet names, private network addresses, raw Tailscale state, enrollment URLs, or complete environment/container dumps. A redacted record of the relevant settings is enough.

## Run local tests

Use a development machine or disposable Linux environment with Python 3, Bash, and Nginx available. Do not install or replace Nginx on the NAS just to run the tests.

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/install-proxy.sh
python3 -m py_compile scripts/test-client.py
```

The tests start their own temporary Nginx instance and mock HTTP backend on loopback ephemeral ports. They do not use systemd, connect to Tailscale, load model weights, change vendor files, or install the proxy. Nginx integration tests are skipped if its binary is missing; a skipped run is not an integration pass. Run in an environment with Nginx to validate all tests.

The generalized installer should also be manually exercised on a disposable/appropriate NAS with a recovery path before marking a new firmware combination supported. Never run the installer in a test that points at a user's live NAS without their approval.

Keep the default exposure private, keep the upstream and proxy loopback-only, and do not silently broaden the route allowlist, tailnet permissions, or runtime privileges. Changes to authentication should include positive and negative tests. Public fixture keys in tests must never be used as deployment keys.
