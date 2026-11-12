# Assistente de Finanças

Conecta Nubank e Mercado Pago/Mercado Livre via **Open Finance (Pluggy)**, importa
as transações e categoriza tudo automaticamente. Você corrige uma categoria e o
sistema aprende o estabelecimento.

## Usar no celular (PWA)

1. No Nubank: exporte o CSV da fatura ou do extrato e guarde no celular.
2. Hospede o app (Dockerfile pronto; `render.yaml` para o Render) com as variáveis
   `APP_PASSWORD` (obrigatória), e opcionalmente `PLUGGY_CLIENT_ID/SECRET`.
   O banco precisa de disco persistente (`/data`), senão some a cada deploy.
3. Abra a URL (HTTPS) no Chrome → menu → *Adicionar à tela inicial*.
4. Toque em **Importar CSV**. Reimportar o mesmo arquivo não duplica.

Local: `APP_PASSWORD=sua-senha uvicorn app.main:app` (ou `ALLOW_NO_AUTH=1` só em localhost).

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
