from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Optional

_DEFAULT_BASE = "https://www.vendus.pt/ws/v1.1/"


@dataclass(frozen=True)
class VendusConfig:
    api_key: str
    base_url: str
    mode: str
    register_id: Optional[int]

    @staticmethod
    def load(env: Mapping[str, str]) -> "VendusConfig":
        api_key = env.get("VENDUS_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "VENDUS_API_KEY em falta. Defina-a em backend/.env "
                "(Vendus: Configuracao > Utilizadores > Opcoes > API)."
            )
        base = (env.get("VENDUS_BASE_URL") or _DEFAULT_BASE).rstrip("/") + "/"
        mode = env.get("VENDUS_MODE") or "tests"
        reg = env.get("VENDUS_REGISTER_ID")
        return VendusConfig(
            api_key=api_key,
            base_url=base,
            mode=mode,
            register_id=int(reg) if reg else None,
        )
