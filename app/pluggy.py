"""Cliente mínimo da API do Pluggy (Open Finance). Docs: https://docs.pluggy.ai"""
import time

import httpx

from . import config


class PluggyError(RuntimeError):
    pass


class PluggyClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 base_url: str | None = None, http: httpx.Client | None = None):
        self.client_id = client_id or config.PLUGGY_CLIENT_ID
        self.client_secret = client_secret or config.PLUGGY_CLIENT_SECRET
        self.base_url = base_url or config.PLUGGY_BASE_URL
        self.http = http or httpx.Client(timeout=30)
        self._api_key: str | None = None
        self._api_key_at = 0.0

    def _auth(self) -> str:
        # a apiKey vale 2h; renovamos a cada 1h50
        if self._api_key and time.time() - self._api_key_at < 6600:
            return self._api_key
        if not (self.client_id and self.client_secret):
            raise PluggyError("Defina PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no .env")
        r = self.http.post(f"{self.base_url}/auth",
                           json={"clientId": self.client_id, "clientSecret": self.client_secret})
        if r.status_code != 200:
            raise PluggyError(f"Falha na autenticação Pluggy: {r.status_code}")
        self._api_key = r.json()["apiKey"]
        self._api_key_at = time.time()
        return self._api_key

    def _get(self, path: str, **params):
        r = self.http.get(f"{self.base_url}{path}", params=params,
                          headers={"X-API-KEY": self._auth()})
        if r.status_code != 200:
            raise PluggyError(f"GET {path} -> {r.status_code}")
        return r.json()

    def connect_token(self) -> str:
        r = self.http.post(f"{self.base_url}/connect_token", json={},
                           headers={"X-API-KEY": self._auth()})
        if r.status_code not in (200, 201):
            raise PluggyError(f"connect_token -> {r.status_code}")
        return r.json()["accessToken"]

    def item(self, item_id: str) -> dict:
        return self._get(f"/items/{item_id}")

    def accounts(self, item_id: str) -> list[dict]:
        return self._get("/accounts", itemId=item_id)["results"]

    def transactions(self, account_id: str, date_from: str | None = None):
        page = 1
        while True:
            params = {"accountId": account_id, "page": page, "pageSize": 500}
            if date_from:
                params["from"] = date_from
            data = self._get("/transactions", **params)
            yield from data["results"]
            if page >= data.get("totalPages", 1):
                return
            page += 1
