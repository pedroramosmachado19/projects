from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import categorizer, db
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


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
