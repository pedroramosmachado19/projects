"""Login simples de usuário único: senha em APP_PASSWORD, sessão em cookie assinado."""
import hashlib
import hmac
import os
import time

COOKIE = "fa_session"
MAX_AGE = 30 * 86400


def enabled() -> bool:
    return bool(os.getenv("APP_PASSWORD"))


def _key() -> bytes:
    return (os.getenv("SECRET_KEY") or os.getenv("APP_PASSWORD", "")).encode()


def _sign(exp: str) -> str:
    return hmac.new(_key(), exp.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + MAX_AGE)
    return f"{exp}.{_sign(exp)}"


def valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sign(exp))


def locked() -> bool:
    """8 senhas erradas em 10 min bloqueiam novas tentativas (estado no banco: serverless não compartilha memória)."""
    from . import db
    now = time.time()
    with db.session() as conn:
        conn.execute("DELETE FROM login_fails WHERE ts < ?", (now - 600,))
        n = conn.execute("SELECT COUNT(*) AS n FROM login_fails").fetchone()["n"]
    return n >= 8


def check_password(password: str) -> bool:
    from . import db
    if locked():
        return False
    ok = hmac.compare_digest(password.encode(), os.getenv("APP_PASSWORD", "").encode())
    if not ok:
        with db.session() as conn:
            conn.execute("INSERT INTO login_fails(ts) VALUES(?)", (time.time(),))
    return ok

def make_state() -> str:
    exp = str(int(time.time()) + 600)
    return f"{exp}.{_sign('ml' + exp)}"


def valid_state(state: str) -> bool:
    if "." not in state:
        return False
    exp, sig = state.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sign("ml" + exp))
