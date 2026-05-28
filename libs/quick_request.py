"""
quick_request.py
~~~~~~~~~~~~~~~~
Lightweight HTTP helpers for AUV modules to read/write the DB API.

Usage
-----
    from quick_request import AUVClient

    client = AUVClient()                        # defaults to localhost:8000
    client = AUVClient("http://192.168.1.10:8000")

    # POST  ──────────────────────────────────────────
    client.post("inputs",  SURGE=0, SWAY=0, HEAVE=0, ROLL=0, PITCH=0, YAW=0,
                           S1=0, S2=0, S3=0)
    client.post("depth",   DEPTH=1.23)
    client.post("imu",     ACCEL_X=0.1, ACCEL_Y=0.2, ACCEL_Z=9.8,
                           GYRO_X=0.0, GYRO_Y=0.0, GYRO_Z=0.0,
                           MAG_X=0.0, MAG_Y=0.0, MAG_Z=0.0)

    # GET latest / by id / paginated list
    row   = client.latest("depth")
    row   = client.get("depth", id=3)
    page  = client.list("imu", limit=100, offset=0)
    page  = client.list("inputs", start="2025-01-01T00:00:00Z",
                                  end="2025-12-31T23:59:59Z")

    # DELETE
    client.delete("inputs", id=7)
"""

from __future__ import annotations

from typing import Any

import requests


class AUVRequestError(RuntimeError):
    """Raised when the API returns a non-2xx status."""
    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} → {status}: {body}")
        self.status = status
        self.body = body


class AUVClient:
    # All tables exposed by the DB API
    TABLES = frozenset(
        ["inputs", "outputs", "depth", "imu", "power_safety", "pid_gains", "detections"],
    )

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post(self, table: str, **fields: Any) -> dict:
        """
        Insert a new row into *table*.
        Pass column values as keyword arguments (case-insensitive keys are
        normalised to UPPER_CASE to match the API).

        Returns the inserted row as a dict.
        """
        self._check_table(table)
        data = {k.upper(): v for k, v in fields.items()}
        return self._request("POST", f"/{table}", data=data)

    def latest(self, table: str) -> dict | None:
        """Return the most-recent row from *table*, or None if empty."""
        self._check_table(table)
        return self._request("GET", f"/{table}/latest")

    def get(self, table: str, id1: int) -> dict:
        """Return a single row by primary key.  Raises AUVRequestError on 404."""
        self._check_table(table)
        return self._request("GET", f"/{table}/{id1}")

    def list(
        self,
        table: str,
        *,
        limit: int = 50,
        offset: int = 0,
        start: str | None = None,
        end:   str | None = None,
    ) -> dict:
        """
        Return a paginated list of rows from *table*.

        Response shape: {"items": [...], "total": int, "limit": int, "offset": int}

        *start* / *end* are optional ISO-8601 UTC strings to filter by TIMESTAMP.
        """
        self._check_table(table)
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._request("GET", f"/{table}", params=params)

    def delete(self, table: str, id1: int) -> None:
        """Delete a row by primary key.  Raises AUVRequestError on 404."""
        self._check_table(table)
        self._request("DELETE", f"/{table}/{id1}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_table(self, table: str) -> None:
        if table not in self.TABLES:
            raise ValueError(
                f"Unknown table '{table}'. Valid tables: {sorted(self.TABLES)}",
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        data:   dict | None = None,
        params: dict | None = None,
    ) -> Any:
        url = self.base_url + path
        resp = self._session.request(
            method,
            url,
            data=data,         # sent as form-encoded (matches Form(...) endpoints)
            params=params,
            timeout=self.timeout,
        )
        if not resp.ok:
            raise AUVRequestError(method, url, resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._session.close()

    # Support use as a context manager
    def __enter__(self) -> AUVClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level convenience functions (for quick one-off calls without
# keeping a client instance around)
# ---------------------------------------------------------------------------
_default_client: AUVClient | None = None


def _get_default() -> AUVClient:
    global _default_client
    if _default_client is None:
        _default_client = AUVClient()
    return _default_client


def configure(base_url: str = "http://localhost:8000", timeout: float = 5.0) -> None:
    """Override the default client settings (call once at startup)."""
    global _default_client
    _default_client = AUVClient(base_url=base_url, timeout=timeout)


def post(table: str, **fields: Any) -> dict:
    return _get_default().post(table, **fields)


def latest(table: str) -> dict | None:
    return _get_default().latest(table)


def get(table: str, id1: int) -> dict:
    return _get_default().get(table, id1)


def list_rows(
    table: str,
    *,
    limit:  int = 50,
    offset: int = 0,
    start:  str | None = None,
    end:    str | None = None,
) -> dict:
    return _get_default().list(table, limit=limit, offset=offset, start=start, end=end)


def delete(table: str, id_1: int) -> None:
    _get_default().delete(table, id_1)