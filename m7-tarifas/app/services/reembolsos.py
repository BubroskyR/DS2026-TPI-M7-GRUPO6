"""Reembolsos (RF-7.5): la devolución de todo o parte de un pago cobrado."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeDominio, NoEncontrado
from app.core.idempotencia import ejecutar_una_vez
from app.core.paginacion import Paginacion, paginar
from app.core.seguridad import Usuario
from app.models.pagos import Pago, Reembolso
from app.schemas import pagos as esquemas
from app.services import pagos

# Solo se reembolsa lo que se cobró.
REEMBOLSABLES = ("aprobado", "reembolsado_parcial")


def reembolsar(
    sesion: Session,
    clave: str,
    pago_id: uuid.UUID,
    datos: esquemas.ReembolsoNuevo,
    usuario: Usuario,
) -> tuple[dict, bool]:
    """Reembolsa todo o parte de un pago, una sola vez por Idempotency-Key (RF-7.6).
    Devuelve (reembolso, es_nuevo)."""
    # El pago es parte de la solicitud: la misma clave para otro pago es otro cuerpo.
    cuerpo = {"pago_id": str(pago_id), **datos.model_dump(mode="json")}
    return ejecutar_una_vez(
        sesion,
        "reembolsarPago",
        clave,
        cuerpo,
        lambda: _reembolsar(sesion, pago_id, datos, usuario),
    )


def _reembolsar(
    sesion: Session, pago_id: uuid.UUID, datos: esquemas.ReembolsoNuevo, usuario: Usuario
) -> dict:
    # Se bloquea el pago hasta terminar: dos reembolsos a la vez no pueden
    # devolver más de lo que se pagó.
    pago = sesion.get(Pago, pago_id, with_for_update=True)
    if pago is None:
        raise NoEncontrado(f"No existe el pago {pago_id}.")
    if pago.estado not in REEMBOLSABLES:
        raise ErrorDeDominio(
            409,
            "/errores/pago-no-reembolsable",
            "El pago no se puede reembolsar",
            detail=f"Está {pago.estado}: solo se reembolsa uno aprobado o reembolsado en parte.",
        )
    queda = pago.monto - pago.monto_reembolsado
    # Sin monto, se reembolsa todo lo que queda.
    monto = queda if datos.monto is None else datos.monto
    if monto > queda:
        raise ErrorDeDominio(
            422,
            "/errores/reembolso-mayor-que-lo-que-queda",
            "El monto supera lo que queda por reembolsar",
            detail=f"Del pago quedan {queda} pesos por reembolsar.",
        )

    pago.monto_reembolsado += monto
    pago.estado = "reembolsado" if pago.monto_reembolsado == pago.monto else "reembolsado_parcial"
    reembolso = Reembolso(id=uuid.uuid4(), pago_id=pago.id, monto=monto, motivo=datos.motivo)
    sesion.add(reembolso)
    pagos.anotar(sesion, pago, "reembolso", usuario.sub, monto=monto, detalle=datos.motivo)
    sesion.flush()
    return esquemas.Reembolso.model_validate(reembolso).model_dump(mode="json")


def listar(sesion: Session, pago_id: uuid.UUID, paginacion: Paginacion, usuario: Usuario) -> dict:
    """Los reembolsos del pago. Un cliente solo ve los de sus propios pagos."""
    pagos.obtener(sesion, pago_id, usuario)
    consulta = (
        select(Reembolso)
        .where(Reembolso.pago_id == pago_id)
        .order_by(Reembolso.creado_en, Reembolso.id)
    )
    return paginar(sesion, consulta, paginacion)
