"""Session and turn keys: keyed hashes of values the anonymizer erases, so they can't be rebuilt later (§12.5)."""

from __future__ import annotations

import hashlib
import hmac
import re

from conversation_analyzer.secrets import hash_key

_ANSWER_NAME = re.compile(r"/engines/(?P<engine>[^/]+)/sessions/(?P<session>[^/]+)/assistAnswers/(?P<answer>[^/]+)$")


def _keyed(*parts: str) -> str:
    return hmac.new(hash_key(), "\x1f".join(parts).encode(), hashlib.sha256).hexdigest()[:32]


def session_key(engine: str, session_id: str) -> str:
    return _keyed("session", engine, session_id)


def turn_key(answer_name: str) -> str:
    return _keyed("turn", answer_name)


def user_key(email: str) -> str:
    """The user, pseudonymous: turns of one person can be grouped, never named (§8.4)."""
    return _keyed("user", email)


def parse_answer_name(answer_name: str) -> tuple[str, str] | None:
    """Engine and session ID from `.../engines/<e>/sessions/<s>/assistAnswers/<a>`."""
    m = _ANSWER_NAME.search(answer_name or "")
    return (m["engine"], m["session"]) if m else None


def session_from_name(session_name: str) -> tuple[str, str] | None:
    """Engine and session ID from a feedback record's `.../engines/<e>/sessions/<s>`."""
    m = re.search(r"/engines/([^/]+)/sessions/([^/]+)$", session_name or "")
    return (m[1], m[2]) if m else None


def stable_fraction(value: str) -> float:
    """A deterministic number in [0, 1) from a key, used for samples such as the second-model check."""
    return int(hashlib.sha256(value.encode()).hexdigest()[:8], 16) / 2**32
