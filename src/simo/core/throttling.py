from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import BaseThrottle


@dataclass(frozen=True)
class ThrottleRule:
    window_seconds: int
    limit_authenticated: int
    limit_anonymous: int


DEFAULT_RULES_GLOBAL: tuple[ThrottleRule, ...] = (
    ThrottleRule(window_seconds=10, limit_authenticated=4000, limit_anonymous=80),
    ThrottleRule(window_seconds=60, limit_authenticated=20000, limit_anonymous=300),
    ThrottleRule(window_seconds=300, limit_authenticated=60000, limit_anonymous=800),
)

DEFAULT_RULES_DEFAULT_SCOPE: tuple[ThrottleRule, ...] = (
    ThrottleRule(window_seconds=10, limit_authenticated=1200, limit_anonymous=40),
    ThrottleRule(window_seconds=60, limit_authenticated=4000, limit_anonymous=120),
    ThrottleRule(window_seconds=300, limit_authenticated=12000, limit_anonymous=400),
)


def _now() -> int:
    return int(time.time())


def _hub_key() -> str:
    # Per-hub identifier for shared cache keys.
    # SECRET_KEY is per-installation and avoids DB access.
    secret = getattr(settings, 'SECRET_KEY', '') or ''
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


def _get_client_ip(request) -> str:
    meta = getattr(request, 'META', {}) or {}
    xff = meta.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return meta.get('REMOTE_ADDR') or 'unknown'


def _is_authenticated(request) -> bool:
    user = getattr(request, 'user', None)
    return bool(getattr(user, 'is_authenticated', False))


def _user_id(request) -> int | None:
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return None
    return int(getattr(user, 'id', 0) or 0) or None


def _subject(request) -> str:
    """Throttle subject key.

    - Authenticated: per-user only (safe behind proxies, avoids shared-IP bans)
    - Anonymous: per-IP
    """
    uid = _user_id(request)
    if uid:
        return f'u:{uid}'
    return f'ip:{_get_client_ip(request)}'


def _ban_seconds() -> int:
    cfg = getattr(settings, 'SIMO_THROTTLE', None)
    if isinstance(cfg, dict):
        try:
            return int(cfg.get('ban_seconds', 300))
        except Exception:
            return 300
    return 300


def _parse_rules(raw, fallback: tuple[ThrottleRule, ...]) -> tuple[ThrottleRule, ...]:
    if not isinstance(raw, (list, tuple)):
        return fallback
    parsed: list[ThrottleRule] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        try:
            parsed.append(
                ThrottleRule(
                    window_seconds=int(r['window_seconds']),
                    limit_authenticated=int(r['limit_authenticated']),
                    limit_anonymous=int(r['limit_anonymous']),
                )
            )
        except Exception:
            continue
    return tuple(parsed) if parsed else fallback


def _rules_for(scope: str) -> tuple[ThrottleRule, ...]:
    cfg = getattr(settings, 'SIMO_THROTTLE', None)
    if isinstance(cfg, dict):
        scopes = cfg.get('scopes')
        if isinstance(scopes, dict) and scope in scopes:
            return _parse_rules(scopes.get(scope), DEFAULT_RULES_DEFAULT_SCOPE)
        defaults = cfg.get('default_rules')
        if defaults is not None:
            return _parse_rules(defaults, DEFAULT_RULES_DEFAULT_SCOPE)
    return DEFAULT_RULES_DEFAULT_SCOPE


def _rules_global() -> tuple[ThrottleRule, ...]:
    cfg = getattr(settings, 'SIMO_THROTTLE', None)
    if isinstance(cfg, dict) and cfg.get('global_rules') is not None:
        return _parse_rules(cfg.get('global_rules'), DEFAULT_RULES_GLOBAL)
    return DEFAULT_RULES_GLOBAL


def _ban_key(subject: str) -> str:
    # Per-user-per-hub ban (across all scopes and instances).
    return f'simo:ban:{_hub_key()}:{subject}'


def _counter_key(subject: str, scope: str, window_seconds: int) -> str:
    return f'simo:rate:{_hub_key()}:{subject}:{scope}:{window_seconds}'


def _is_banned(subject: str) -> int:
    try:
        ban_until = cache.get(_ban_key(subject))
    except Exception:
        return 0
    if not ban_until:
        return 0
    try:
        ban_until = int(ban_until)
    except Exception:
        return 0
    wait = ban_until - _now()
    return int(wait) if wait > 0 else 0


def _set_ban(subject: str) -> int:
    seconds = max(1, _ban_seconds())
    ban_until = _now() + seconds
    try:
        cache.set(_ban_key(subject), ban_until, timeout=seconds)
    except Exception:
        # Cache down => fail open (no ban)
        return 0
    return seconds


def check_throttle(*, request, scope: str) -> int:
    """Return wait seconds (0 means allowed).

    Fail-open behavior: if cache is down/unavailable, returns 0.
    """
    subject = _subject(request)
    wait = _is_banned(subject)
    if wait:
        return wait

    is_auth = _is_authenticated(request)
    scopes_to_check = ('global', scope)

    for sc in scopes_to_check:
        rules = _rules_global() if sc == 'global' else _rules_for(sc)
        for rule in rules:
            limit = rule.limit_authenticated if is_auth else rule.limit_anonymous
            key = _counter_key(subject, sc, rule.window_seconds)
            try:
                # Ensure key exists with TTL before incr.
                cache.add(key, 0, timeout=rule.window_seconds)
                count = cache.incr(key)
            except Exception:
                # Cache unavailable => don't block
                continue
            if int(count) > limit:
                return _set_ban(subject)

    return 0


class SimoAdaptiveThrottle(BaseThrottle):
    """DRF throttle using SIMO adaptive per-user bans."""

    _wait: int | None = None

    def allow_request(self, request, view):
        scope = getattr(view, 'throttle_scope', None)
        if not scope:
            scope = getattr(view, 'basename', None) or view.__class__.__name__
        self._wait = check_throttle(request=request, scope=str(scope))
        return self._wait <= 0

    def wait(self):
        return self._wait


class SimpleRequest:
    """Minimal request-like wrapper for non-HTTP entry points."""

    def __init__(self, *, user=None, meta=None, headers=None):
        self.user = user
        self.META = meta or {}
        self.headers = headers or {}

