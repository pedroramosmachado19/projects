from app import categorizer as c, db
from app.sync import signed_amount, store_transaction


def test_builtin_rules():
    assert c.categorize("IFOOD *RESTAURANTE", -40)[0] == "Alimentação"
    assert c.categorize("Uber *TRIP", -20)[0] == "Transporte"
    assert c.categorize("Netflix.com", -39.9)[0] == "Assinaturas"
    assert c.categorize("MERCADO LIVRE*ABC 02/10", -100)[0] == "Compras"


def test_invoice_payment_is_not_spending():
    assert c.categorize("Pagamento de fatura", -500)[0] == "Pagamento de fatura"


def test_provider_fallback_and_default():
    assert c.categorize("XYZ LTDA", -10, "Pharmacy") == ("Saúde", "provider")
    assert c.categorize("XYZ LTDA", -10) == ("Outros", "default")
    assert c.categorize("XYZ LTDA", 10)[0] == "Renda"


def test_signed_amount_ignores_provider_sign():
    assert signed_amount({"amount": 50, "type": "DEBIT"}) == -50
    assert signed_amount({"amount": -50, "type": "DEBIT"}) == -50
    assert signed_amount({"amount": 50, "type": "CREDIT"}) == 50


def test_learning_and_resync_keeps_user_choice(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO accounts(id,item_id) VALUES('a','i')")
    tx = {"id": "1", "date": "2026-11-01T00:00:00Z", "description": "PADARIA DO ZE 01/03",
          "amount": 30, "type": "DEBIT"}
    store_transaction(conn, "a", tx, {})
    assert conn.execute("SELECT category FROM transactions").fetchone()[0] == "Alimentação"
    assert c.learn(conn, "PADARIA DO ZE 01/03", "Lazer") == 1
    store_transaction(conn, "a", tx, c.load_user_rules(conn))  # re-sync
    row = conn.execute("SELECT category, category_source FROM transactions").fetchone()
    assert tuple(row) == ("Lazer", "user")
    # nova compra no mesmo estabelecimento já nasce com a regra aprendida
    assert c.categorize("PADARIA DO ZE 02/03", -30, None, c.load_user_rules(conn))[0] == "Lazer"
