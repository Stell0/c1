"""Server-side sessions and login transactions (M12 D3).

Access and refresh tokens stay server-side: the browser holds an opaque random
session ID in an ``HttpOnly`` cookie. A validated ID token may be an RP logout
hint for the identity provider. A restart ends every C1 session.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

LOGIN_TTL_S = 300
MAX_SESSIONS = 10_000
MAX_LOGINS = 1_000


@dataclass
class Tokens:
    access_token: str = field(repr=False)
    access_expires_at: float
    refresh_token: str | None = field(default=None, repr=False)
    refresh_expires_at: float | None = None
    identity_token: str | None = field(default=None, repr=False)


@dataclass
class Session:
    id: str = field(repr=False)
    tokens: Tokens
    csrf: str = field(repr=False)
    created: float
    last_seen: float
    subject: str = ""
    display_name: str = ""


@dataclass
class LoginTransaction:
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    return_to: str
    created: float


def _key(value: str) -> str:
    """Store only a digest of a bearer-like browser value as the table key."""
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore:
    def __init__(
        self,
        *,
        idle_s: int,
        max_s: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_s, self.max_s, self.clock = idle_s, max_s, clock
        self._sessions: dict[str, Session] = {}
        self._logins: dict[str, LoginTransaction] = {}

    # Login transactions -------------------------------------------------

    def begin_login(self, return_to: str) -> tuple[str, LoginTransaction]:
        self._purge()
        if len(self._logins) >= MAX_LOGINS:
            oldest = min(self._logins, key=lambda k: self._logins[k].created)
            del self._logins[oldest]
        handle = secrets.token_urlsafe(32)
        login = LoginTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            verifier=secrets.token_urlsafe(64),
            return_to=return_to,
            created=self.clock(),
        )
        self._logins[_key(handle)] = login
        return handle, login

    def finish_login(self, handle: str | None, state: str | None) -> LoginTransaction | None:
        """Consume the transaction exactly once; ``None`` for unknown, expired or wrong state."""
        if not handle:
            return None
        login = self._logins.pop(_key(handle), None)
        if login is None or self.clock() - login.created > LOGIN_TTL_S:
            return None
        if not state or not hmac.compare_digest(login.state, state):
            return None
        return login

    # Sessions ------------------------------------------------------------

    def create(self, tokens: Tokens, *, subject: str = "", display_name: str = "") -> str:
        self._purge()
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].last_seen)
            del self._sessions[oldest]
        session_id = secrets.token_urlsafe(32)
        now = self.clock()
        self._sessions[_key(session_id)] = Session(
            id=session_id,
            tokens=tokens,
            csrf=secrets.token_urlsafe(32),
            created=now,
            last_seen=now,
            subject=subject,
            display_name=display_name,
        )
        return session_id

    def get(self, session_id: str | None) -> Session | None:
        if not session_id or len(session_id) > 128:
            return None
        key = _key(session_id)
        session = self._sessions.get(key)
        if session is None:
            return None
        now = self.clock()
        if now - session.last_seen > self.idle_s or now - session.created > self.max_s:
            del self._sessions[key]
            return None
        session.last_seen = now
        return session

    def delete(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        return self._sessions.pop(_key(session_id), None)

    def __len__(self) -> int:
        return len(self._sessions)

    def _purge(self) -> None:
        now = self.clock()
        for key in [
            k
            for k, s in self._sessions.items()
            if now - s.last_seen > self.idle_s or now - s.created > self.max_s
        ]:
            del self._sessions[key]
        for key in [k for k, t in self._logins.items() if now - t.created > LOGIN_TTL_S]:
            del self._logins[key]


def csrf_matches(session: Session, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(session.csrf, str(supplied))
