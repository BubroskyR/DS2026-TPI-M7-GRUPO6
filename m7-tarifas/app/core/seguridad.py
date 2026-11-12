"""Tokens de Keycloak (M1): quién hace cada solicitud y qué puede hacer (RF-1.3, RNF-12).

Cada ruta pide un permiso (scope) del contrato, por ejemplo `pagos:write`. M7
valida el token con las claves públicas de Keycloak, como el ejemplo de la
cátedra: la firma, que no esté vencido y que lo haya emitido el realm
configurado. Si el token es de una persona, también mira su rol: un cliente o
un conductor solo ve y cambia lo suyo.

- Sin token, o con uno inválido o vencido: 401.
- Sin el permiso de la ruta, o una persona que pide lo de otra: 403.
- Si Keycloak no responde, M7 no puede validar el token: 503.

Con AUTH_DISABLED=true no se valida nada: solo para desarrollar.
"""

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errores import NoAutenticado, ServicioNoDisponible, SinPermiso

log = logging.getLogger("m7")

# Los permisos (scopes) del contrato.
PERMISOS = frozenset(
    {
        "tarifas:read",
        "tarifas:write",
        "pagos:read",
        "pagos:write",
        "liquidaciones:read",
        "liquidaciones:write",
    }
)
# Los roles de las personas (RF-1.3). Los módulos usan cuentas de servicio, sin estos roles.
CLIENTE = "CLIENTE"
CONDUCTOR = "CONDUCTOR"
OPERADOR = "OPERADOR"
ROLES_DE_PERSONA = frozenset({CLIENTE, CONDUCTOR, OPERADOR})

# Si Keycloak no contesta en este tiempo, M7 no se queda esperando.
ESPERA_MAXIMA_SEGUNDOS = 3


@dataclass(frozen=True)
class Usuario:
    """Quién hace la solicitud, según su token."""

    # Identificador de la persona o de la cuenta de servicio del módulo.
    sub: str
    permisos: frozenset[str]
    roles: frozenset[str]

    @property
    def solo_lo_propio(self) -> bool:
        """True si es una persona que no es operador: un cliente o un conductor."""
        return bool(self.roles & ROLES_DE_PERSONA) and OPERADOR not in self.roles

    @property
    def id_persona(self) -> uuid.UUID | None:
        """El `sub` como UUID: es el `cliente_id` o el `beneficiario_id` de la persona."""
        try:
            return uuid.UUID(self.sub)
        except ValueError:
            return None


# Con AUTH_DISABLED=true, todas las solicitudes las hace este usuario, que tiene todos los permisos.
SIN_AUTENTICACION = Usuario(sub="sin-autenticacion", permisos=PERMISOS, roles=frozenset())

# Lee el encabezado Authorization: Bearer <token>. Si falta, devuelve None y M7 responde 401.
_bearer = HTTPBearer(auto_error=False, description="Token de Keycloak (M1)")


@lru_cache
def _claves_de_keycloak(jwks_uri: str) -> jwt.PyJWKClient:
    # Baja las claves públicas de Keycloak y las guarda 5 minutos, para no
    # pedirlas en cada solicitud. Si llega un token firmado con una clave nueva,
    # las vuelve a pedir.
    return jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=300, timeout=ESPERA_MAXIMA_SEGUNDOS)


def usuario_del_token(credenciales: HTTPAuthorizationCredentials | None) -> Usuario:
    """Valida el token y devuelve quién es. Si falta o no es válido, 401."""
    if settings.auth_disabled:
        return SIN_AUTENTICACION
    if credenciales is None:
        raise NoAutenticado("Falta el token: Authorization: Bearer <token>.")
    token = credenciales.credentials

    try:
        clave = _claves_de_keycloak(settings.keycloak_jwks_uri).get_signing_key_from_jwt(token)
        datos = jwt.decode(
            token,
            clave.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer_uri,
            # Como el ejemplo de la cátedra, no se controla el destinatario (aud).
            options={"require": ["exp", "iss"], "verify_aud": False},
        )
    except jwt.PyJWKClientConnectionError:
        log.error("Keycloak no responde en %s", settings.keycloak_jwks_uri)
        raise ServicioNoDisponible(
            detalle="No se pudo validar el token: Keycloak (M1) no responde."
        ) from None
    except jwt.ExpiredSignatureError:
        raise NoAutenticado("El token está vencido.") from None
    except jwt.PyJWTError:
        raise NoAutenticado("El token no es válido.") from None

    # Keycloak manda los permisos separados por espacios ("openid pagos:read")
    # y los roles del realm en realm_access.roles.
    acceso = datos.get("realm_access")
    roles = acceso.get("roles", []) if isinstance(acceso, dict) else []
    return Usuario(
        sub=str(datos.get("sub") or datos.get("azp") or ""),
        permisos=frozenset(str(datos.get("scope", "")).split()),
        roles=frozenset(str(rol).upper() for rol in roles if isinstance(rol, str)),
    )


def requiere(permiso: str):
    """Dependencia de una ruta: exige un token válido con `permiso`.

    Las personas también pueden usarla, pero solo sobre lo suyo: eso lo controla
    cada operación con `exigir_que_sea_suyo` o `solo_lo_suyo`.
    """

    def _usuario_con_permiso(
        credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Usuario:
        usuario = usuario_del_token(credenciales)
        if permiso not in usuario.permisos:
            raise SinPermiso(f"El token no tiene el permiso {permiso}.")
        return usuario

    return _usuario_con_permiso


def requiere_modulo_u_operador(permiso: str):
    """Como `requiere`, pero un cliente o un conductor reciben 403.

    Por ejemplo, los clientes tienen `pagos:write` solo para sus medios de pago
    (contrato): no pueden registrar pagos, cargos ni reembolsos.
    """
    con_permiso = requiere(permiso)

    def _modulo_u_operador(usuario: Annotated[Usuario, Depends(con_permiso)]) -> Usuario:
        if usuario.solo_lo_propio:
            raise SinPermiso("Esta operación es solo para los módulos y los operadores.")
        return usuario

    return _modulo_u_operador


def exigir_que_sea_suyo(usuario: Usuario, dueno_id: uuid.UUID) -> None:
    """Un cliente o un conductor solo accede a lo suyo (RF-1.3): si `dueno_id` no es
    su `sub`, 403."""
    if usuario.solo_lo_propio and dueno_id != usuario.id_persona:
        raise SinPermiso("Un cliente o un conductor solo puede acceder a lo suyo.")


def solo_lo_suyo(usuario: Usuario, pedido_id: uuid.UUID | None) -> uuid.UUID | None:
    """El filtro de una lista: un cliente o un conductor solo ve lo suyo.

    Si pide lo de otra persona, 403. Si no pide a nadie en particular, se le
    muestra lo suyo. A un módulo o un operador se le devuelve lo que pidió.
    """
    if not usuario.solo_lo_propio:
        return pedido_id
    if usuario.id_persona is None:
        raise SinPermiso("El token no identifica a la persona.")
    if pedido_id is not None:
        exigir_que_sea_suyo(usuario, pedido_id)
    return usuario.id_persona
