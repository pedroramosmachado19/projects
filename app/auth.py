"""Login simples de usuário único: senha em APP_PASSWORD, sessão em cookie assinado."""
import hashlib
import hmac
import os
import time

COOKIE = "fa_session"
MAX_AGE = 30 * 86400
_fails: list[float] = []


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
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < 600]
    return len(_fails) >= 8  # 8 erros em 10 min bloqueiam tentativas


def check_password(password: str) -> bool:
    if locked():
        return False
    ok = hmac.compare_digest(password.encode(), os.getenv("APP_PASSWORD", "").encode())
    if not ok:
        _fails.append(time.time())
    return ok
