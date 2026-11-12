# Assistente de Finanças

Conecta Nubank e Mercado Pago/Mercado Livre via **Open Finance (Pluggy)**, importa
as transações e categoriza tudo automaticamente. Você corrige uma categoria e o
sistema aprende o estabelecimento.

## Rodando

```bash
pip install -r requirements.txt
cp .env.example .env      # preencha PLUGGY_CLIENT_ID / PLUGGY_CLIENT_SECRET
uvicorn app.main:app --reload
# abra http://localhost:8000 e clique em "Conectar banco"
pytest
```

Credenciais: crie uma aplicação em https://dashboard.pluggy.ai. Os dados ficam só
no seu `finance.db` (SQLite local). O `.env` e o `.db` estão no `.gitignore`.

## Como funciona

- `app/pluggy.py` – cliente da API (auth, connect token, contas, transações)
- `app/sync.py` – importa e normaliza (DEBIT = gasto, CREDIT = entrada)
- `app/categorizer.py` – regra do usuário > regras embutidas > categoria Pluggy > Outros
- `app/main.py` – API FastAPI + dashboard em `app/static/index.html`

Pagamento de fatura, transferências e investimentos não entram nos "gastos" do mês,
para não contar a mesma despesa duas vezes.

## Próximos passos

- Metas/orçamento por categoria e alertas
- Detecção de assinaturas recorrentes e parcelamentos
- Categorização com Claude para estabelecimentos desconhecidos
- Compras do Mercado Livre item a item (API oficial do ML, OAuth)
