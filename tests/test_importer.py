import pytest
from app import db, importer

CARD = "date,category,title,amount\n2026-11-03,restaurante,Ifood,42.50\n2026-11-03,restaurante,Ifood,42.50\n2026-11-05,,Pagamento recebido,-900.00\n"
ACCOUNT = "Data,Valor,Identificador,Descrição\n05/11/2026,-18.50,abc-1,Compra no débito - Uber\n06/11/2026,5000.00,abc-2,Transferência recebida - Salario ACME\n"


def test_card_csv_keeps_duplicates_and_is_idempotent(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    assert importer.import_csv(conn, CARD) == 3
    importer.import_csv(conn, CARD)  # reimportar não duplica
    rows = conn.execute("SELECT description, amount, category FROM transactions ORDER BY date, amount").fetchall()
    assert len(rows) == 3
    assert [r["amount"] for r in rows if r["description"] == "Ifood"] == [-42.5, -42.5]
    assert any(r["category"] == "Pagamento de fatura" and r["amount"] == 900 for r in rows)


def test_account_csv(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    importer.import_csv(conn, ACCOUNT)
    got = {r["id"]: (r["amount"], r["category"]) for r in conn.execute("SELECT * FROM transactions")}
    assert got["csv-abc-1"] == (-18.5, "Transporte")
    assert got["csv-abc-2"][0] == 5000


def test_unknown_format():
    with pytest.raises(importer.ImportError_):
        importer.parse("a,b\n1,2\n")


def test_app_requires_login_and_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "segredo-teste")
    monkeypatch.setattr("app.config.DB_PATH", str(tmp_path / "a.db"))
    from fastapi.testclient import TestClient
    from app import main
    c = TestClient(main.app, follow_redirects=False)
    assert c.get("/api/summary?month=2026-11").status_code == 401      # sem login
    assert c.get("/").status_code == 307                                # redireciona
    assert c.post("/login", json={"password": "errada"}).status_code == 401
    assert c.post("/login", json={"password": "segredo-teste"}).status_code == 200
    r = c.post("/api/import", content=CARD, headers={"Content-Type": "text/plain"})
    assert r.json() == {"imported": 3}
    s = c.get("/api/summary?month=2026-11").json()
    assert s["spent"] == 85.0 and s["categories"][0]["category"] == "Alimentação"
    assert c.get("/manifest.webmanifest").status_code == 200            # público p/ instalar


def _fake_ml(handler):
    import httpx
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_mercadolivre_oauth_sync_and_match(tmp_path, monkeypatch):
    import httpx
    from app import config, mercadolivre as ml
    monkeypatch.setattr(config, "ML_CLIENT_ID", "id"); monkeypatch.setattr(config, "ML_CLIENT_SECRET", "sec")
    monkeypatch.setattr(config, "APP_BASE_URL", "https://x.test")
    conn = db.connect(str(tmp_path / "m.db"))
    conn.execute("INSERT INTO accounts(id,item_id) VALUES('a','i')")
    from app.sync import store_transaction
    # compra à vista + parcela 1/3 de outra, ambas na fatura como MERCADOLIVRE*
    store_transaction(conn, "a", {"id": "t1", "date": "2026-11-02", "description": "MERCADOLIVRE*FONE",
                                  "amount": 150.0, "type": "DEBIT"}, {})
    store_transaction(conn, "a", {"id": "t2", "date": "2026-11-20", "description": "MERCADOLIVRE*SOFA 1/3",
                                  "amount": 300.0, "type": "DEBIT"}, {})
    def handler(req: httpx.Request):
        p = req.url.path
        if p == "/oauth/token":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "user_id": 42, "expires_in": 21600})
        if p == "/orders/search":
            assert req.headers["authorization"] == "Bearer A" and req.url.params["buyer"] == "42"
            return httpx.Response(200, json={"paging": {"total": 2}, "results": [
                {"id": 1, "status": "paid", "date_created": "2026-11-01T10:00:00.000-04:00", "paid_amount": 150.0,
                 "order_items": [{"item": {"title": "Fone Bluetooth", "category_id": "MLB1"}}]},
                {"id": 2, "status": "paid", "date_created": "2026-10-15T10:00:00.000-04:00", "paid_amount": 900.0,
                 "order_items": [{"item": {"title": "Sofá 3 lugares", "category_id": "MLB2"}}]}]})
        if p == "/categories/MLB1":
            return httpx.Response(200, json={"path_from_root": [{"name": "Eletrônicos, Áudio e Vídeo"}]})
        return httpx.Response(200, json={"path_from_root": [{"name": "Casa, Móveis e Decoração"}]})
    http = _fake_ml(handler)
    ml.connect(conn, "CODE", http)
    assert ml.sync(conn, http) == {"orders": 2, "matched": 2}
    rows = {r["id"]: (r["category"], r["category_source"]) for r in conn.execute("SELECT * FROM transactions")}
    assert rows["t1"] == ("Eletrônicos", "ml") and rows["t2"] == ("Casa", "ml")
    # re-sync do Pluggy não desfaz o enriquecimento
    store_transaction(conn, "a", {"id": "t1", "date": "2026-11-02", "description": "MERCADOLIVRE*FONE",
                                  "amount": 150.0, "type": "DEBIT"}, {})
    d = conn.execute("SELECT category, description FROM transactions WHERE id='t1'").fetchone()
    assert d["category"] == "Eletrônicos" and "Fone Bluetooth" in d["description"]
