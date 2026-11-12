"""Importa CSV exportado do app do Nubank (fatura do cartão ou extrato da conta)."""
import csv
import hashlib
import io
import unicodedata
from datetime import datetime

from . import categorizer
from .sync import store_transaction

ITEM_ID, ACCOUNT_ID = "csv-import", "csv-nubank"


class ImportError_(ValueError):
    pass


def _norm(h: str) -> str:
    h = unicodedata.normalize("NFKD", h.strip().lower().lstrip("﻿"))
    return "".join(c for c in h if not unicodedata.combining(c))


def _num(s: str) -> float:
    s = s.strip().replace("R$", "").replace(" ", "")
    if "," in s:  # formato BR: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ImportError_(f"Data inválida: {s!r}")


def parse(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    reader.fieldnames = [_norm(h) for h in (reader.fieldnames or [])]
    cols = set(reader.fieldnames)
    seen: dict[str, int] = {}
    out = []
    if {"date", "title", "amount"} <= cols:      # fatura do cartão: compra = valor positivo
        kind = "card"
    elif {"data", "valor", "descricao"} <= cols:  # extrato da conta: saída = valor negativo
        kind = "account"
    else:
        raise ImportError_("Formato não reconhecido. Use o CSV da fatura ou do extrato do Nubank.")
    for row in reader:
        if kind == "card":
            date, desc, raw = _date(row["date"]), row["title"].strip(), _num(row["amount"])
            type_ = "DEBIT" if raw > 0 else "CREDIT"
            ident = None
        else:
            date, desc, raw = _date(row["data"]), row["descricao"].strip(), _num(row["valor"])
            type_ = "DEBIT" if raw < 0 else "CREDIT"
            ident = (row.get("identificador") or "").strip() or None
        if ident is None:  # mesma compra repetida no mesmo dia é legítima: conta ocorrências
            base = f"{kind}|{date}|{desc}|{raw}"
            seen[base] = seen.get(base, 0) + 1
            ident = hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()
        out.append({"id": f"csv-{ident}", "date": date, "description": desc,
                    "amount": raw, "type": type_, "category": None})
    return out


def import_csv(conn, text: str) -> int:
    txs = parse(text)
    conn.execute("INSERT INTO items(id, connector) VALUES(?, 'Importação CSV') "
                 "ON CONFLICT(id) DO NOTHING", (ITEM_ID,))
    conn.execute("INSERT INTO accounts(id, item_id, name, type, institution) "
                 "VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING", (ACCOUNT_ID, ITEM_ID, "Nubank (CSV)", "BANK", "Nubank"))
    rules = categorizer.load_user_rules(conn)
    for tx in txs:
        store_transaction(conn, ACCOUNT_ID, tx, rules)
    return len(txs)
