from pathlib import Path

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import auth, categorizer, config, db, importer
from .pluggy import PluggyClient, PluggyError
from .sync import sync_item

app = FastAPI(title="Assistente de Finanças")
STATIC = Path(__file__).parent / "static"
_client: PluggyClient | None = None


def client() -> PluggyClient:
    global _client
    if _client is None:
        _client = PluggyClient()
    return _client


class ItemIn(BaseModel):
    item_id: str
    date_from: str | None = None  # YYYY-MM-DD


class RecategorizeIn(BaseModel):
    category: str


PUBLIC = {"/login", "/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png"}

if not auth.enabled() and os.getenv("ALLOW_NO_AUTH") != "1":
    raise RuntimeError("Defina APP_PASSWORD (ou ALLOW_NO_AUTH=1 só para uso local em localhost).")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if auth.enabled() and path not in PUBLIC and not auth.valid(request.cookies.get(auth.COOKIE)):
        if path.startswith("/api"):
            return JSONResponse({"detail": "Não autenticado"}, status_code=401)
        return RedirectResponse("/login")
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


class LoginIn(BaseModel):
    password: str


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.post("/login")
def login(body: LoginIn, request: Request):
    if auth.locked():
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    if not auth.check_password(body.password):
        raise HTTPException(401, "Senha incorreta")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True,
                    samesite="strict", secure=request.url.scheme == "https"
                    or request.headers.get("x-forwarded-proto") == "https")
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/icon-{size}.png")
def icon(size: int):
    if size not in (192, 512):
        raise HTTPException(404)
    return FileResponse(STATIC / f"icon-{size}.png")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def get_config():
    return {"pluggy": bool(config.PLUGGY_CLIENT_ID and config.PLUGGY_CLIENT_SECRET)}


@app.post("/api/import")
async def import_file(request: Request):
    """Recebe o texto do CSV do Nubank (fatura ou extrato)."""
    raw = await request.body()
    if len(raw) > 5_000_000:
        raise HTTPException(413, "Arquivo grande demais")
    try:
        with db.session() as conn:
            n = importer.import_csv(conn, raw.decode("utf-8", errors="replace"))
    except (importer.ImportError_, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"imported": n}


@app.post("/api/connect-token")
def connect_token():
    try:
        return {"accessToken": client().connect_token()}
    except PluggyError as e:
        raise HTTPException(502, str(e))


@app.post("/api/items")
def add_item(body: ItemIn):
    """Chamado após o widget Pluggy Connect devolver o itemId. Sincroniza tudo."""
    try:
        with db.session() as conn:
            n = sync_item(conn, client(), body.item_id, body.date_from)
    except PluggyError as e:
        raise HTTPException(502, str(e))
    return {"synced": n}


@app.post("/api/sync")
def sync_all():
    try:
        with db.session() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM items")]
            n = sum(sync_item(conn, client(), i) for i in ids)
    except PluggyError as e:
        raise HTTPException(502, str(e))
    return {"items": len(ids), "synced": n}


@app.get("/api/transactions")
def transactions(month: str | None = None, category: str | None = None, limit: int = 200):
    q, args = ("SELECT t.*, a.institution, a.name AS account FROM transactions t "
               "LEFT JOIN accounts a ON a.id = t.account_id WHERE 1=1"), []
    if month:
        q += " AND substr(t.date,1,7) = ?"; args.append(month)
    if category:
        q += " AND t.category = ?"; args.append(category)
    q += " ORDER BY t.date DESC LIMIT ?"; args.append(min(limit, 1000))
    with db.session() as conn:
        return [dict(r) for r in conn.execute(q, args)]


@app.get("/api/summary")
def summary(month: str):
    """Gastos por categoria (sem transferências/fatura) + totais do mês."""
    skip = ("Pagamento de fatura", "Transferências", "Investimentos")
    with db.session() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) AS total, COUNT(*) AS n FROM transactions "
            "WHERE substr(date,1,7) = ? GROUP BY category", (month,)).fetchall()
    by_cat = [dict(r) for r in rows]
    spent = -sum(r["total"] for r in by_cat if r["total"] < 0 and r["category"] not in skip)
    income = sum(r["total"] for r in by_cat if r["total"] > 0 and r["category"] not in skip)
    cats = sorted(
        ({"category": r["category"], "spent": -r["total"], "count": r["n"]}
         for r in by_cat if r["total"] < 0 and r["category"] not in skip),
        key=lambda r: -r["spent"])
    return {"month": month, "spent": spent, "income": income, "balance": income - spent,
            "categories": cats}


@app.get("/api/categories")
def categories():
    return sorted(set(categorizer.BUILTIN_RULES) | {categorizer.DEFAULT})


@app.patch("/api/transactions/{tx_id}")
def recategorize(tx_id: str, body: RecategorizeIn):
    """Corrige a categoria e aprende: transações parecidas (mesmo estabelecimento) mudam junto."""
    with db.session() as conn:
        row = conn.execute("SELECT description FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Transação não encontrada")
        changed = categorizer.learn(conn, row["description"], body.category)
    return {"updated": changed}
