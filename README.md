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

## Hospedar no Vercel (grátis) + Neon

1. Vercel → *Add New → Project* → importe o repositório (branch desta feature ou a principal).
2. Aba *Storage* do projeto → *Create Database* → **Neon (Postgres)**. Isso cria `DATABASE_URL` sozinho.
3. *Settings → Environment Variables*: `APP_PASSWORD` (obrigatória), `PLUGGY_CLIENT_ID`,
   `PLUGGY_CLIENT_SECRET`. Faça *Redeploy*.
4. Abra a URL → adicionar à tela inicial → **Conectar banco** (Nubank e Mercado Pago, via Pluggy).

Com `DATABASE_URL` o app usa Postgres; sem ela, usa SQLite local (`finance.db`).
Testes em Postgres: `TEST_DATABASE_URL=postgresql://... pytest`.

## Mercado Livre (opcional, só se configurar as chaves)

(Para Mercado **Pago** não precisa disto: ele entra pelo Pluggy.)

Crie um app em https://developers.mercadolivre.com.br/devcenter e cadastre como URI de
redirecionamento `APP_BASE_URL/ml/callback`. Preencha `ML_CLIENT_ID`, `ML_CLIENT_SECRET`
e `APP_BASE_URL`. As compras enriquecem as transações da fatura (categoria pelo produto);
não viram transações novas, para não contar em dobro. Casamento por valor/data, até 12x.
Mercado Pago (conta/cartão) entra pelo Pluggy.

## Rodando

```bash
pip install -r requirements-dev.txt
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
