"""CR-012 cron entrypoint — POST the internal run-due endpoint on a schedule.

Run by an external scheduler (Railway native Cron or cron-job.org). Uses httpx
(already a backend dependency) instead of curl, which is NOT in the backend image
(the old `curl ...` cron command crashed with 'curl: not found'). One-shot: exits
0 on HTTP 200, non-zero otherwise so a bad run shows up in the cron logs.

Env vars (set on the cron service):
  INTERNAL_CRON_SECRET  shared secret; MUST equal the API service's value
  RUN_DUE_URL           full endpoint URL, e.g.
                        https://yapi-code-production.up.railway.app/api/v1/internal/automations/run-due
"""
import os
import sys

import httpx


def main() -> int:
    secret = os.environ.get("INTERNAL_CRON_SECRET", "")
    url = os.environ.get("RUN_DUE_URL", "")
    if not secret or not url:
        print("[run_due_cron] set INTERNAL_CRON_SECRET and RUN_DUE_URL", file=sys.stderr)
        return 1
    try:
        resp = httpx.post(url, headers={"X-Internal-Secret": secret}, timeout=120)
    except Exception as exc:  # network/DNS error
        print(f"[run_due_cron] request failed: {exc}", file=sys.stderr)
        return 1
    print(f"[run_due_cron] {resp.status_code} {resp.text}")
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
