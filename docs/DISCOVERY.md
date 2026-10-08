# Finding the UGREEN inference service

The original NAS used systemd services, not a visible model container:

```text
aiconsole_serv.service
  aiconsole_serv (model manager)

llama_serv_sycl@aiconsole.service
  infer_gateway_s (service MainPID)
    .llama-server (worker child)

ugreen_rag_serv@aiconsole.service
  rag_ai_sdk_tool
```

The `@aiconsole` suffix is a systemd instance name, not a process-parent declaration. Inspect `PPID`, `MainPID`, and cgroup membership rather than inferring process relationships from unit names. These are observations from one installation, not required topology on all firmware.

## Read-only discovery

Activate the local model in the NAS application first, then run as an administrator:

```bash
ps -eo pid,ppid,user,comm | grep -Ei 'llama|infer_gateway|aiconsole|rag_ai'
systemctl show llama_serv_sycl@aiconsole.service \
  -p Id -p MainPID -p ActiveState -p ControlGroup
sudo ss -lntp | grep -E 'infer_gateway|llama'
sudo ss -xlpn | grep -E 'infer_gateway|llama'
```

For the actual worker PID, not a stale example PID:

```bash
PID=REPLACE_WITH_CURRENT_WORKER_PID
sudo readlink -f "/proc/$PID/exe"
sudo cat "/proc/$PID/cgroup"
sudo cat "/proc/$PID/cmdline" | tr '\0' '\n' | awk '
  take { print "  " $0; take=0; next }
  /^(--host|--port|--api-prefix|--model|--alias|-m|-a)$/ { print; take=1; next }
  /^--(host|port|api-prefix|model|alias)=/ { print }
'
```

Only selected arguments are printed. Do not replace this with an unrestricted environment or configuration dump for a public issue.

Observed paths included a vendor `llamacppSycl` directory, model files under `/opt/ugreen/ai/models/`, and a worker socket under `/run/ugreen/llama-gw-socks/`. The exact socket filename and PID are runtime details. A leading dot in `.llama-server` does not make the process hidden from `ps`.

The working gateway port was `62891`. Its `/v1/models` request returned a Qwen entry plus an `mmproj-BF16` entry. Its `/health` route returned 404 while chat completions succeeded. Do not substitute a projector ID for the chat model or interpret that 404 as a model-health verdict.

If no TCP listener is visible, check Unix sockets and network namespaces before concluding there is no API. Upstream llama.cpp can use a Unix socket path in `--host`, but vendor builds can differ. Prefer the verified gateway over exposing a worker socket directly, since vendor routing/lifecycle behavior may be important.

A process RSS value alone does not establish model size, device allocation, or actual accelerator use. Loaded SYCL/Level Zero libraries are clues, not a performance measurement.

## Evidence to contribute

Record hardware and firmware version, AI package/runtime version when available, worker fingerprint, model ID, gateway bind address/port, HTTP results, and test origin. Keep credentials and personal network identifiers out of public reports. Only call a capability verified after exercising it: catalog discovery is not chat, text chat is not vision, and one short request is not a sustained throughput test.

Sources: [systemd unit instances](https://man7.org/linux/man-pages/man5/systemd.unit.5.html), [proc command lines](https://man7.org/linux/man-pages/man5/proc_pid_cmdline.5.html), [ss](https://man7.org/linux/man-pages/man8/ss.8.html), and [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
