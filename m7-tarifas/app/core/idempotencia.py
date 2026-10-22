"""Idempotency-Key (RF-7.6, RNF-08): una solicitud repetida no cobra ni reembolsa dos veces.

Quien llama manda una clave única en el encabezado Idempotency-Key. La primera
vez que llega una clave se hace la operación y se guarda su respuesta. Si la
misma clave vuelve a llegar:
- con el mismo cuerpo, se devuelve la respuesta guardada, sin repetir nada (200);
- con otro cuerpo, 422;
- si la primera todavía se está procesando, 409.
"""

import hashlib
import json
from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeDominio
from app.models.idempotencia import ClaveIdempotencia


def ejecutar_una_vez(
    sesion: Session,
    operacion: str,
    clave: str,
    cuerpo: dict,
    hacer: Callable[[], dict],
) -> tuple[dict, bool]:
    """Hace `hacer()` una sola vez por clave. Devuelve (respuesta, es_nueva).

    Se llama antes de tocar nada en la sesión. `cuerpo` es lo que identifica a
    la solicitud (el cuerpo y, si hay, el id de la ruta). `hacer()` agrega a la
    sesión lo que tenga que guardar, sin hacer commit, y devuelve la respuesta
    ya lista para JSON: lo que guarda y la respuesta se confirman juntos.
    """
    huella = _huella(cuerpo)
    guardada = _reservar(sesion, operacion, clave, huella)
    if guardada is not None:
        return guardada, False

    try:
        respuesta = hacer()
        reserva = sesion.get(ClaveIdempotencia, (operacion, clave))
        reserva.respuesta = respuesta
        sesion.commit()
    except Exception:
        _liberar(sesion, operacion, clave)
        raise
    return respuesta, True


def _huella(cuerpo: dict) -> str:
    # Con las claves ordenadas, el mismo cuerpo da la misma huella aunque sus
    # campos lleguen en otro orden.
    texto = json.dumps(cuerpo, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _reservar(sesion: Session, operacion: str, clave: str, huella: str) -> dict | None:
    """Anota la clave como "en proceso". Si ya existía, devuelve su respuesta guardada."""
    sesion.add(ClaveIdempotencia(operacion=operacion, clave=clave, huella=huella))
    try:
        # Se confirma ya, para que otra solicitud con la misma clave la vea.
        sesion.commit()
        return None
    except IntegrityError:
        # La base no deja guardar dos veces la misma clave: ya se había usado.
        sesion.rollback()

    existente = sesion.get(ClaveIdempotencia, (operacion, clave))
    if existente is not None and existente.huella != huella:
        raise ErrorDeDominio(
            422,
            "/errores/idempotency-key-con-otro-cuerpo",
            "La Idempotency-Key ya se usó con otro cuerpo",
        )
    if existente is None or existente.respuesta is None:
        raise ErrorDeDominio(
            409,
            "/errores/idempotency-key-en-proceso",
            "Todavía se está procesando una solicitud con esta Idempotency-Key",
        )
    return existente.respuesta


def _liberar(sesion: Session, operacion: str, clave: str) -> None:
    """La operación falló: se borra la clave, así se puede reintentar con la misma."""
    sesion.rollback()
    sesion.execute(
        delete(ClaveIdempotencia).where(
            ClaveIdempotencia.operacion == operacion, ClaveIdempotencia.clave == clave
        )
    )
    sesion.commit()
