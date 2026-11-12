"""Roda o fluxo completo em Postgres real. Defina TEST_DATABASE_URL para habilitar."""
import os

import pytest

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL não definido")

CARD = ("date,category,title,amount\n2026-11-03,x,Ifood,42.50\n2026-11-03,x,Ifood,42.50\n"
        "2026-11-05,,Pagamento recebido,-900.00\n2026-11-02,x,MERCADOLIVRE*FONE,150.00\n")


@pytest.fixture
def client(monkeypatch):
    import psycopg
    from app import config, db
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    monkeypatch.setattr(config, "DATABASE_URL", URL)
    monkeypatch.setattr(db, "_pg_ready", False)
    monkeypatch.setenv("APP_PASSWORD", "segredo-teste")
    from fastapi.testclient import TestClient
    from app import main
    return TestClient(main.app, follow_redirects=False)


def test_full_flow_on_postgres(client):
    from app import db, mercadolivre as ml
    assert client.get("/api/summary?month=2026-11").status_code == 401
    assert client.post("/login", json={"password": "errada"}).status_code == 401
    assert client.post("/login", json={"password": "segredo-teste"}).status_code == 200
    assert client.post("/api/import", content=CARD, headers={"Content-Type": "text/plain"}).json() == {"imported": 4}
    assert client.post("/api/import", content=CARD, headers={"Content-Type": "text/plain"}).json() == {"imported": 4}
    s = client.get("/api/summary?month=2026-11").json()
    assert s["spent"] == 235.0                      # 42,5*2 + 150, sem duplicar na reimportação
    txs = client.get("/api/transactions?month=2026-11").json()
    assert len(txs) == 4 and isinstance(txs[0]["amount"], float)
    ifood = next(t for t in txs if t["description"] == "Ifood")
    assert client.patch(f"/api/transactions/{ifood['id']}", json={"category": "Lazer"}).json() == {"updated": 2}
    # casamento de pedido do ML com a transação (SQL mais complexo)
    with db.session() as conn:
        conn.execute("INSERT INTO ml_orders(id,date,total,title,category) VALUES('1','2026-11-01',150.0,'Fone','Eletrônicos')")
        assert ml.match_orders(conn) == 1
    cats = {t["category"] for t in client.get("/api/transactions?month=2026-11").json()}
    assert "Eletrônicos" in cats and "Lazer" in cats


def test_lockout_persists_in_db(client):
    for _ in range(8):
        client.post("/login", json={"password": "errada"})
    assert client.post("/login", json={"password": "segredo-teste"}).status_code == 429
