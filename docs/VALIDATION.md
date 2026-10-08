# Validation and provenance

[Back to README](../README.md) | [Security boundaries](SECURITY.md) | [Operations](OPERATIONS.md)

## Scope

This report distinguishes the deployment owner's live NAS results from local tests of the published repository. A working text completion is useful evidence, not a security audit, a firmware compatibility guarantee, or proof of complete OpenAI API support.

The repository implementation tested for this report is commit [`6c29b5eadbd842f1bb2ed9d3897e23c9842f16dd`](https://github.com/MahdiHedhli/UGreen-IDX6011-Inference-Liberation/commit/6c29b5eadbd842f1bb2ed9d3897e23c9842f16dd). The test-related source files were retrieved from that revision and their Git blob hashes were checked before execution. No installation commands were run against the live NAS while preparing this report.

## Live reference deployment

The following evidence was supplied by the deployment owner:

| Item | Observation |
|---|---|
| Hardware | UGREEN iDX6011 Pro |
| Native service | `llama_serv_sycl@aiconsole.service` |
| Process relationship | `infer_gateway_s` as the service's main process, with a child `.llama-server` |
| Runtime | Vendor llama.cpp SYCL build, with a Unix-socket worker and a loopback TCP gateway |
| Observed gateway port | `62891`; discovery remains necessary on each installation and after changes |
| Accepted request model ID | `Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-GGUF` |
| Direct loopback completion | HTTP 200 with final content `NAS inference is working.` |
| Protected remote model discovery | Owner reported authenticated HTTP 200, including the configured model |
| Protected remote chat completion | Owner reported authenticated HTTP 200 with non-empty final text |
| Tailscale | An existing host-networked Docker container with persistent state |
| Exact UGOS firmware and AI app versions | Not recorded in the supplied evidence |

The catalog advertised 51,200 context tokens and vision capability for the main model. Those are advertised metadata, not long-context or vision test results. Its second `mmproj-BF16` entry is not evidence of a second independently usable chat model.

One direct six-token completion reported approximately 15.85 generated tokens per second and about 762 ms in the server's time-to-first-token field. This tiny smoke test is not a throughput benchmark. The owner's approximately 20 tokens/second observation is also not a controlled sustained or multi-client measurement. Neither should be treated as a guaranteed performance specification.

## Local repository tests

The following commands completed successfully against the published implementation:

```bash
python3 -m unittest discover -s tests -v
systemd-analyze verify config/ugreen-inference-proxy.service
python3 -m py_compile scripts/test-client.py
```

The suite reported **14 tests passed**, comprising 11 Nginx integration tests and three static/client-input checks:

| Test | Verified result |
|---|---|
| Missing API key | HTTP 401 with a Bearer challenge |
| Incorrect API key | HTTP 401 |
| Case-changed API key | HTTP 401; credential matching is case-sensitive |
| Lowercase authentication scheme | Valid `bearer` scheme accepted |
| Authenticated model discovery | HTTP 200 with the expected mock model and `Cache-Control: no-store` |
| Synthetic chat completion | HTTP 200 with non-empty mock assistant content |
| Synthetic event-stream response | Expected content type and event data, including the completion marker, reached the client |
| Unlisted routes | Selected health, embeddings, Responses, administration, and trailing-slash routes rejected with HTTP 404 |
| Unlisted methods | Selected wrong methods rejected with HTTP 405 |
| Credential and cookie forwarding | Authorization and Cookie absent upstream; Set-Cookie absent downstream |
| Request-size restriction | Oversized declared request body rejected with HTTP 413 |
| Installer syntax | `bash -n` succeeded |
| No automatic publication | Installer contained neither a Serve publishing invocation nor a Funnel invocation checked by the test |
| Client transport input | The smoke-test client rejected a non-HTTPS base URL |

These tests launch a temporary local Nginx process with a synthetic HTTP backend. They do not create NAS accounts, install the systemd unit, run Tailscale or Docker, or exercise the actual Qwen model. The event-stream test checks transport content, not time-to-first-chunk behavior or real-model streaming compatibility. The full HTTPS smoke-test client was not run against a fresh NAS in this repository validation pass.

The unit verification checks configuration syntax in the test environment. It does not exercise systemd sandbox behavior on UGOS. Python compilation and Bash parsing are also syntax checks, not deployment tests.

Nginx must be installed in the local test environment. Without it, the integration tests are skipped. Check the runner output and do not count a skipped suite as a pass.

## Still needs hardware or deployment validation

Fresh Tailscale enrollment using the documented bootstrap, execution of the generalized installer on a clean target NAS, planned restart and firmware-update persistence, denied-device tailnet policy, real-model streaming, tool calling, vision, long context, sustained concurrency, and vendor prompt/log-retention behavior all require separate tests.

The owner used the earlier manual proxy recipe. The repository generalizes it into templates and an installer, including root-only client settings instead of a machine-specific home directory. Do not reinstall over the owner's already-working deployment solely to reproduce this report.

For community compatibility reports, include the NAS model, firmware and AI app versions, reviewed repository revision, Tailscale version, HTTP statuses, and which capabilities were actually tested. Follow [CONTRIBUTING.md](../CONTRIBUTING.md), and never attach live keys, passwords, enrollment links, private hostnames, or Tailscale state.
