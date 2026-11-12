"""Categorização de transações.

Prioridade: regra do usuário (aprendida) > regras embutidas > categoria do
provedor (Pluggy) > "Outros".
"""
import re
import unicodedata

DEFAULT = "Outros"
TRANSFER = "Transferências"

# categoria -> palavras-chave (já normalizadas: minúsculas, sem acento)
BUILTIN_RULES: dict[str, list[str]] = {
    "Pagamento de fatura": ["pagamento de fatura", "pagamento recebido", "pagamento fatura"],
    "Alimentação": ["ifood", "rappi", "restaurante", "lanchonete", "padaria", "mcdonald",
                    "burger king", "subway", "starbucks", "pizzaria", "outback"],
    "Mercado": ["supermercado", "carrefour", "pao de acucar", "assai", "atacadao",
                "mercado extra", "dia supermercado", "hortifruti", "sam's club", "mercadinho", "minimercado"],
    "Transporte": ["uber", "99app", "99 tecnologia", "cabify", "posto", "shell", "ipiranga",
                   "sem parar", "conectcar", "estacionamento", "metro", "bilhete unico"],
    "Assinaturas": ["netflix", "spotify", "amazon prime", "disney", "hbo", "max.com",
                    "youtube premium", "apple.com/bill", "google one", "icloud", "deezer"],
    "Moradia": ["aluguel", "condominio", "enel", "light servicos", "sabesp", "cpfl", "comgas",
                "vivo fibra", "claro", "tim ", "net ", "internet"],
    "Saúde": ["farmacia", "drogaria", "drogasil", "raia", "pague menos", "unimed",
              "hospital", "clinica", "laboratorio", "dental"],
    "Educação": ["udemy", "alura", "coursera", "faculdade", "escola", "curso", "livraria"],
    "Lazer": ["cinema", "ingresso", "steam", "playstation", "xbox", "nintendo", "sympla",
              "airbnb", "booking", "hotel", "decolar"],
    "Compras": ["mercado livre", "mercadolivre", "mercpago", "amazon", "shopee", "aliexpress",
                "magalu", "magazine luiza", "americanas", "shein", "zara", "renner", "c&a"],
    "Renda": ["salario", "folha de pagamento", "pro-labore", "rendimento", "dividendo", "cashback"],
    "Investimentos": ["rdb", "cdb", "tesouro", "aplicacao", "resgate", "xp invest", "nuinvest"],
    "Transferências": ["pix", "transferencia", "ted ", "doc "],
    "Taxas": ["tarifa", "iof", "anuidade", "juros", "multa"],
}

# Categorias do Pluggy (inglês) -> nossas categorias
PROVIDER_MAP = {
    "groceries": "Mercado", "eating out": "Alimentação", "food delivery": "Alimentação",
    "transport": "Transporte", "taxi and ride-hailing": "Transporte", "gas stations": "Transporte",
    "streaming": "Assinaturas", "digital services": "Assinaturas",
    "pharmacy": "Saúde", "health": "Saúde", "education": "Educação",
    "shopping": "Compras", "online shopping": "Compras", "entertainment": "Lazer",
    "travel": "Lazer", "income": "Renda", "salary": "Renda", "investments": "Investimentos",
    "transfers": "Transferências", "same person transfer": "Transferências",
    "bank fees": "Taxas", "taxes": "Taxas", "housing": "Moradia", "utilities": "Moradia",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def merchant_key(description: str) -> str:
    """Chave estável para aprender regras: remove números/parcelas ('LOJA 02/10')."""
    key = re.sub(r"\d+([/\-.]\d+)*", " ", normalize(description))
    return re.sub(r"\s+", " ", key).strip()


def load_user_rules(conn) -> dict[str, str]:
    return {r["keyword"]: r["category"] for r in conn.execute("SELECT keyword, category FROM user_rules")}


def categorize(
    description: str,
    amount: float,
    provider_category: str | None = None,
    user_rules: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Retorna (categoria, fonte)."""
    desc = normalize(description)
    key = merchant_key(description)

    for kw, cat in (user_rules or {}).items():
        if kw and kw in key:
            return cat, "user"

    # Pagamento de fatura vem antes das demais (ex.: "pagamento" + nome do banco)
    for cat in ("Pagamento de fatura", "Renda", "Investimentos"):
        if any(k in desc for k in BUILTIN_RULES[cat]):
            return cat, "rule"

    for cat, kws in BUILTIN_RULES.items():
        if any(k in desc for k in kws):
            return cat, "rule"

    if provider_category:
        mapped = PROVIDER_MAP.get(normalize(provider_category))
        if mapped:
            return mapped, "provider"

    if amount > 0:
        return "Renda", "default"
    return DEFAULT, "default"


def learn(conn, description: str, category: str) -> int:
    """Guarda uma regra e recategoriza transações parecidas. Retorna quantas mudaram."""
    key = merchant_key(description)
    if not key:
        return 0
    conn.execute(
        "INSERT INTO user_rules(keyword, category) VALUES(?, ?) "
        "ON CONFLICT(keyword) DO UPDATE SET category = excluded.category",
        (key, category),
    )
    changed = 0
    for row in conn.execute("SELECT id, description FROM transactions").fetchall():
        if key in merchant_key(row["description"]):
            conn.execute(
                "UPDATE transactions SET category = ?, category_source = 'user' WHERE id = ?",
                (category, row["id"]),
            )
            changed += 1
    return changed
