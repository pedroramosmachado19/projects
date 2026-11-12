import os
from pathlib import Path


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

PLUGGY_CLIENT_ID = os.getenv("PLUGGY_CLIENT_ID", "")
PLUGGY_CLIENT_SECRET = os.getenv("PLUGGY_CLIENT_SECRET", "")
PLUGGY_BASE_URL = "https://api.pluggy.ai"
DB_PATH = os.getenv("FINANCE_DB", "finance.db")
# Postgres (Neon/Vercel): se definido, substitui o SQLite
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""

# Mercado Livre (OAuth) — app criado em developers.mercadolivre.com.br
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")  # ex.: https://meu-app.onrender.com
