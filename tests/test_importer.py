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
