"""Mercado Livre: login OAuth + compras item a item.

As compras NÃO viram transações novas (já aparecem na fatura/conta via Pluggy, e
contariam em dobro). Elas enriquecem a transação correspondente: categoria pelo
tipo do produto e o nome do item na descrição.
"""
import re
import time
from datetime import date, timedelta
from urllib.parse import urlencode

import httpx

from . import config

AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
API = "https://api.mercadolibre.com"
MARKERS = ("mercadolivre", "mercado livre", "mercpago", "mercado pago")

# palavra na categoria raiz do ML -> nossa categoria
ROOT_MAP = [
    (("celular", "eletr", "informat", "camera", "audio", "video"), "Eletrônicos"),
    (("casa", "movel", "eletrodom", "decora", "construc", "ferramenta"), "Casa"),
    (("moda", "roupa", "calcado", "joia", "relogio", "bolsa"), "Vestuário"),
    (("beleza", "cuidado pessoal", "saude"), "Saúde"),
    (("esporte", "brinquedo", "game", "hobby", "instrumento"), "Lazer"),
    (("livro", "revista", "curso"), "Educação"),
    (("veiculo", "carro", "moto"), "Transporte"),
    (("mercado", "alimento", "bebida"), "Mercado"),
]
EXTRA_CATEGORIES = ["Eletrônicos", "Casa", "Vestuário"]


class MLError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.ML_CLIENT_ID and config.ML_CLIENT_SECRET and config.APP_BASE_URL)


def redirect_uri() -> str:
    return f"{config.APP_BASE_URL}/ml/callback"


def authorize_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": config.ML_CLIENT_ID,
                                       "redirect_uri": redirect_uri(), "state": state})


def _save_tokens(conn, data: dict) -> None:
    conn.execute(
        "INSERT INTO ml_auth(id, user_id, access_token, refresh_token, expires_at) VALUES(1,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id, access_token=excluded.access_token, "
        "refresh_token=excluded.refresh_token, expires_at=excluded.expires_at",
        (str(data["user_id"]), data["access_token"], data["refresh_token"],
         time.time() + int(data.get("expires_in", 21600))))


def _token_request(http: httpx.Client, **form) -> dict:
    r = http.post(f"{API}/oauth/token", data={"client_id": config.ML_CLIENT_ID,
                  "client_secret": config.ML_CLIENT_SECRET, **form},
                  headers={"accept": "application/json"})
    if r.status_code != 200:
        raise MLError(f"Mercado Livre recusou o login ({r.status_code})")
    return r.json()


def connect(conn, code: str, http: httpx.Client | None = None) -> None:
    http = http or httpx.Client(timeout=30)
    _save_tokens(conn, _token_request(http, grant_type="authorization_code", code=code,
                                      redirect_uri=redirect_uri()))


def connected(conn) -> bool:
    return conn.execute("SELECT 1 FROM ml_auth").fetchone() is not None


def _access(conn, http) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM ml_auth WHERE id = 1").fetchone()
    if not row:
        raise MLError("Mercado Livre não conectado")
    if row["expires_at"] - 60 < time.time():
        data = _token_request(http, grant_type="refresh_token", refresh_token=row["refresh_token"])
        _save_tokens(conn, data)
        return data["access_token"], str(data["user_id"])
    return row["access_token"], row["user_id"]


def _get(http, path, token, **params):
    r = http.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise MLError(f"GET {path} -> {r.status_code}")
    return r.json()


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def our_category(root_name: str | None) -> str:
    n = _norm(root_name or "")
    for kws, cat in ROOT_MAP:
        if any(k in n for k in kws):
            return cat
    return "Compras"


def _root_category(http, token, category_id: str, cache: dict) -> str:
    if category_id not in cache:
        try:
            path = _get(http, f"/categories/{category_id}", token).get("path_from_root") or []
            cache[category_id] = our_category(path[0]["name"] if path else None)
        except MLError:
            cache[category_id] = "Compras"
    return cache[category_id]


def match_orders(conn) -> int:
    """Associa pedidos às transações da fatura/conta (à vista ou parcelado, até 12x)."""
    like = " OR ".join("lower(description) LIKE ?" for _ in MARKERS)
    marks = [f"%{m}%" for m in MARKERS]
    done = 0
    for o in conn.execute("SELECT * FROM ml_orders WHERE matched = 0").fetchall():
        od = date.fromisoformat(o["date"])
        for k in range(1, 13):
            end = od + timedelta(days=5 if k == 1 else 31 * k + 5)
            rows = conn.execute(
                f"SELECT id, description FROM transactions WHERE amount < 0 "
                f"AND ABS(ABS(amount) - ?) <= 0.02 AND date BETWEEN ? AND ? "
                f"AND category_source NOT IN ('user','ml') AND ({like}) "
                f"AND id NOT IN (SELECT tx_id FROM ml_matches) ORDER BY date LIMIT ?",
                (o["total"] / k, (od - timedelta(days=2)).isoformat(), end.isoformat(), *marks, k)
            ).fetchall()
            if rows:
                for r in rows:
                    conn.execute("UPDATE transactions SET category = ?, category_source = 'ml', "
                                 "description = ? WHERE id = ?",
                                 (o["category"], f"{r['description']} — {o['title'][:60]}", r["id"]))
                    conn.execute("INSERT INTO ml_matches(tx_id, order_id) VALUES(?,?)", (r["id"], o["id"]))
                conn.execute("UPDATE ml_orders SET matched = 1 WHERE id = ?", (o["id"],))
                done += 1
                break
    return done


def sync(conn, http: httpx.Client | None = None) -> dict:
    http = http or httpx.Client(timeout=30)
    token, user_id = _access(conn, http)
    cache: dict = {}
    n, offset = 0, 0
    while True:
        data = _get(http, "/orders/search", token, buyer=user_id, sort="date_desc",
                    offset=offset, limit=50)
        for o in data.get("results", []):
            if o.get("status") == "cancelled" or not o.get("order_items"):
                continue
            item = o["order_items"][0]["item"]
            title = " + ".join(i["item"]["title"] for i in o["order_items"])[:200]
            total = float(o.get("paid_amount") or o.get("total_amount") or 0)
            conn.execute(
                "INSERT INTO ml_orders(id, date, total, title, category) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET total=excluded.total, title=excluded.title",
                (str(o["id"]), o["date_created"][:10], total, title,
                 _root_category(http, token, item.get("category_id", ""), cache)))
            n += 1
        offset += 50
        if offset >= data.get("paging", {}).get("total", 0) or not data.get("results"):
            break
    return {"orders": n, "matched": match_orders(conn)}
