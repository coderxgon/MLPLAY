"""Admin panel session auth — in-memory sessions + cookie."""
import secrets
from datetime import datetime, timedelta

SESSIONS: dict[str, datetime] = {}
COOKIE_NAME = "mlp_session"
SESSION_TTL = timedelta(days=30)


def create_session() -> str:
    tok = secrets.token_hex(24)
    SESSIONS[tok] = datetime.utcnow() + SESSION_TTL
    return tok


def destroy_session(tok: str | None):
    if tok:
        SESSIONS.pop(tok, None)


def check_session(tok: str | None) -> bool:
    if not tok:
        return False
    exp = SESSIONS.get(tok)
    if not exp:
        return False
    if datetime.utcnow() > exp:
        SESSIONS.pop(tok, None)
        return False
    return True