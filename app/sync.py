import sqlite3

from . import categorizer
from .pluggy import PluggyClient


def signed_amount(tx: dict) -> float:
    """DEBIT = saída (negativo), CREDIT = entrada (positivo), independente do sinal do provedor."""
    amount = abs(float(tx["amount"]))
    return -amount if tx.get("type") == "DEBIT" else amount


def store_transaction(conn: sqlite3.Connection, account_id: str, tx: dict,
                      user_rules: dict[str, str]) -> None:
    amount = signed_amount(tx)
    description = tx.get("description") or tx.get("descriptionRaw") or "(sem descrição)"
    category, source = categorizer.categorize(description, amount, tx.get("category"), user_rules)
    # Não sobrescreve correção manual do usuário em re-sincronizações.
    conn.execute(
        """INSERT INTO transactions(id, account_id, date, description, amount, category,
                                    category_source, raw_category)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             amount = excluded.amount, date = excluded.date,
             description = CASE WHEN transactions.category_source = 'ml'
                             THEN transactions.description ELSE excluded.description END,
             category = CASE WHEN transactions.category_source IN ('user','ml')
                             THEN transactions.category ELSE excluded.category END,
             category_source = CASE WHEN transactions.category_source IN ('user','ml')
                             THEN transactions.category_source ELSE excluded.category_source END""",
        (tx["id"], account_id, tx["date"][:10], description, amount, category, source,
         tx.get("category")),
    )


def sync_item(conn: sqlite3.Connection, client: PluggyClient, item_id: str,
              date_from: str | None = None) -> int:
    item = client.item(item_id)
    connector = (item.get("connector") or {}).get("name", "")
    conn.execute("INSERT INTO items(id, connector) VALUES(?,?) "
                 "ON CONFLICT(id) DO UPDATE SET connector = excluded.connector", (item_id, connector))
    rules = categorizer.load_user_rules(conn)
    total = 0
    for acc in client.accounts(item_id):
        conn.execute(
            "INSERT INTO accounts(id, item_id, name, type, institution) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (acc["id"], item_id, acc.get("name"), acc.get("type"), connector),
        )
        for tx in client.transactions(acc["id"], date_from):
            store_transaction(conn, acc["id"], tx, rules)
            total += 1
    return total
