class VendusError(Exception):
    """Erro base da integração Vendus."""


class VendusRateLimited(VendusError):
    """429 / créditos de rate-limit esgotados."""


class VendusUnavailable(VendusError):
    """Vendus inacessível (timeout/conexão/5xx)."""


class VendusHTTPError(VendusError):
    """Resposta HTTP de erro (4xx não-429)."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Vendus HTTP {status_code}: {body[:300]}")
