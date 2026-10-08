# Security boundaries

## What this configuration does

Tailscale access rules determine which tailnet clients can reach the HTTPS listener. The separate proxy then requires a bearer API key and permits only `GET /v1/models` and `POST /v1/chat/completions`. It does not expose a shell, filesystem browser, or model-management route.

The Nginx service runs as a dedicated non-login user without Linux capabilities, with a restricted filesystem view. The shared token is generated locally, is not passed upstream, and uses a case-sensitive credential match. Nginx literal `map` keys are case-insensitive, so this project deliberately uses a regex for authentication. Only the `Bearer` scheme is matched case-insensitively. [Nginx map reference](https://nginx.org/en/docs/http/ngx_http_map_module.html)

Access logs are disabled in the custom proxy, cookies are not forwarded, and responses are marked `no-store`. This does not establish that vendor services, clients, operating-system diagnostics, or network metadata never log anything. Inspect those separately before submitting sensitive material.

## What it does not do

The existing vendor gateway remains reachable without this key by processes that can access the NAS's loopback namespace. Root, Docker administrators, and host-networked containers are within that trust boundary. This project does not isolate the original root-run inference worker or stop local software from bypassing the proxy.

The key is a shared secret, not a per-agent identity or authorization system. There is no per-user revocation, prompt filtering, request-body schema enforcement, model allowlist, or security audit log. Two catalog entries do not mean two independently usable chat models. Do not treat this as a hostile multi-tenant service.

The two-request proxy concurrency limit is global to this proxy and does not cover UGREEN's own requests. It is not a token quota or a guarantee of CPU/RAM availability. Authorized clients can still consume resources, request long contexts, or interfere with local AI use. Timeouts are inactivity/transport safeguards, not a strict GPU time budget. [Connection-limit reference](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)

Use a vendor-supported, maintained firmware/runtime. The added proxy cannot fix vulnerabilities in those components. Upgrades can remove custom services, alter ports, or change gateway authentication. Review and retest instead of automatically relaxing controls.

## Tailnet policy example

Review policy **before enrolling** a host-networked NAS. Its services that bind all interfaces can become reachable over Tailscale under existing rules. This guide does not reconfigure SSH, SMB, or NAS management exposure.

This illustrative policy fragment grants a group inference access on one port. Replace the example email and example IP with your actual values. Merge deliberately into the policy editor; do not overwrite an existing policy or remove necessary recovery access.

```json
{
  "groups": {
    "group:inference-clients": ["operator@example.com"]
  },
  "hosts": {
    "nas-inference": "100.101.102.103"
  },
  "grants": [
    {
      "src": ["group:inference-clients"],
      "dst": ["nas-inference"],
      "ip": ["tcp:8443"]
    }
  ]
}
```

The group selects users and their applicable devices, not one specific laptop. For more precise device/agent separation, use appropriately owned tags and device posture rules in your existing policy. Do not tag an existing NAS blindly: changing node ownership can affect other access.

**Grants and legacy ACL allows are additive.** A new narrow grant does not override a broader rule already permitting NAS access. Review broad wildcards and test an allowed client and a denied client before sharing the key. [Grants semantics](https://tailscale.com/docs/reference/syntax/grants)

## Private, not public

Use `tailscale serve`, not `tailscale funnel`, and proxy only to the authenticated loopback port. No router port-forward is required. HTTPS certificates publish certificate names in transparency logs even while the service itself remains private. Avoid sensitive device names. [Serve](https://tailscale.com/docs/features/tailscale-serve) | [Certificate privacy](https://tailscale.com/docs/how-to/set-up-https-certificates)

Do not bind the unauthenticated gateway to `0.0.0.0` or publish it through Docker `-p`. For non-Tailscale LAN clients, deploy a separately reviewed TLS/authenticated endpoint with firewall restrictions. That is outside the verified setup; a plaintext LAN bearer-key endpoint is not an equivalent substitute.

## Secrets and reports

Never commit Tailscale state, pre-auth keys, enrollment URLs, API keys, `auth.conf`, `client.header`, or `client.env`. Avoid `nginx -T`, full process-environment dumps, broad container inspections, screenshots of terminal scrollback, and shell tracing (`set -x`) when handling credentials. File permissions do not protect a credential already copied into logs or Git history.

On suspected key compromise, disable Serve immediately, stop the proxy, generate a new key through the documented reinstall procedure, and update all clients. Keep Tailscale state backups encrypted and access restricted. An inference-key rotation does not rotate the Tailscale node's credentials.

For a security report, do not post live credentials or exploitation against someone else's NAS. Share a redacted description or minimal local reproduction. If credentials were exposed, revoke them before discussing the incident publicly. No private reporting channel is promised by this repository.
