import httpx

from libs.db_manager.models import OutputsRead

DB_BASE_URL = "http://127.0.0.1:8000"


class DBConnection:
    def __init__(self, base_url: str = DB_BASE_URL):
        self._client = httpx.Client(base_url=base_url)

    def __enter__(self) -> "DBConnection":
        return self

    def __exit__(self, *_) -> None:
        self._client.close()

    def fetch_latest_outputs(self) -> OutputsRead | None:
        try:
            resp = self._client.get("/outputs/latest", timeout=1.0)
            resp.raise_for_status()
            data = resp.json()
            if data is None:
                return None
            return OutputsRead.model_validate(data)
        except Exception:
            return None
