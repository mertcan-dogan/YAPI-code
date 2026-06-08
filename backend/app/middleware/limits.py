"""Targeted rate limits & login lockout (CR-002-I 10.2).

In-memory, resettable for tests. For multi-instance production back these with
Redis. Provides:
  - login lockout: N failed attempts per IP -> temporary lock
  - per-user sliding-window limits for expensive endpoints (import, ai-import)
"""
import time
from collections import defaultdict, deque

from app.config import settings
from app.responses import APIError

# --- Login lockout state ---
_failed_logins: dict[str, list[float]] = defaultdict(list)
_locked_until: dict[str, float] = {}

# --- Per-user sliding windows: key=(user_id, bucket) ---
_user_windows: dict[tuple[str, str], deque] = defaultdict(deque)


def reset_limits() -> None:
    _failed_logins.clear()
    _locked_until.clear()
    _user_windows.clear()


# --- Login lockout ---
def is_login_locked(ip: str) -> int:
    """Return remaining lock seconds for an IP, or 0 if not locked."""
    until = _locked_until.get(ip)
    if until and until > time.monotonic():
        return int(until - time.monotonic())
    return 0


def record_failed_login(ip: str) -> None:
    now = time.monotonic()
    window = settings.login_lockout_seconds
    attempts = [t for t in _failed_logins[ip] if t > now - window]
    attempts.append(now)
    _failed_logins[ip] = attempts
    if len(attempts) >= settings.login_max_attempts:
        _locked_until[ip] = now + settings.login_lockout_seconds


def clear_failed_logins(ip: str) -> None:
    _failed_logins.pop(ip, None)
    _locked_until.pop(ip, None)


# --- Per-user endpoint limits ---
def enforce_user_limit(user_id: str, bucket: str, limit: int, window_seconds: float = 60.0) -> None:
    now = time.monotonic()
    q = _user_windows[(str(user_id), bucket)]
    while q and q[0] <= now - window_seconds:
        q.popleft()
    if len(q) >= limit:
        retry = int(window_seconds - (now - q[0])) + 1
        raise APIError(429, "RATE_LIMITED", f"Çok fazla istek. {retry} saniye sonra tekrar deneyin.")
    q.append(now)
