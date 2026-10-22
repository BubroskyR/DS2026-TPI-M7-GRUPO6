"""Configuración de M7, leída de variables de entorno (RNF-06)."""

from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env está en la raíz del repo, al lado de docker-compose.yml. Dentro de
# Docker no hay .env: las variables llegan desde docker-compose.yml.
RAIZ_DEL_REPO = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=RAIZ_DEL_REPO / ".env", extra="ignore")

    # Conexión a la base propia de M7 (RNF-05). No tiene valor por defecto
    # porque lleva la clave de la base.
    database_url: str

    # Keycloak (M1): quién emite los tokens y de dónde se bajan sus claves.
    keycloak_issuer_uri: str = "http://localhost:8080/realms/ds-2026-realm"
    keycloak_jwks_uri: str = "http://localhost:8080/realms/ds-2026-realm/protocol/openid-connect/certs"
    # Solo para desarrollar: saltea la validación del token.
    auth_disabled: bool = False

    # Clave que manda la pasarela simulada en el encabezado X-Webhook-Secret.
    pasarela_webhook_secret: str | None = None

    # Porcentaje de comisión de la plataforma en las liquidaciones (RF-7.8).
    comision_plataforma: Decimal = Decimal("0.20")


settings = Settings()
