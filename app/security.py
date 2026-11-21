"""F-03: JWT (PyJWT) - wydawanie tokenu i guard endpointów."""
import hmac
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config

_bearer = HTTPBearer(auto_error=False)


def require_configured() -> None:
    s = config.settings
    if not s.jwt_secret or not s.auth_password:
        raise HTTPException(503, "Autoryzacja włączona, ale JWT_SECRET lub AUTH_PASSWORD nie są ustawione")


def check_credentials(username: str, password: str) -> bool:
    s = config.settings
    return hmac.compare_digest(username.encode(), s.auth_user.encode()) & hmac.compare_digest(
        password.encode(), s.auth_password.encode()
    )


def create_token(username: str) -> str:
    require_configured()
    s = config.settings
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes)
    return jwt.encode({"sub": username, "exp": exp}, s.jwt_secret, algorithm=s.jwt_algorithm)


def require_auth(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str | None:
    s = config.settings
    if not s.auth_enabled:
        return None
    require_configured()
    if cred is None:
        raise HTTPException(401, "Brak tokenu", headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(cred.credentials, s.jwt_secret, algorithms=[s.jwt_algorithm])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Nieprawidłowy lub wygasły token", headers={"WWW-Authenticate": "Bearer"})


_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    """S-01: najwyżej RATE_LIMIT_PER_MINUTE żądań na IP i ścieżkę w oknie 60 s (0 = bez limitu)."""
    # shortcut: licznik w pamięci jednego procesu - przy kilku workerach/replikach każdy liczy osobno; wtedy limit na proxy albo Redis
    limit = config.settings.rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    q = _hits[(request.client.host if request.client else "", request.url.path)]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Za dużo zapytań, spróbuj ponownie za minutę", headers={"Retry-After": "60"})
    q.append(now)
