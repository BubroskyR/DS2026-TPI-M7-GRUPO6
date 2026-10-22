"""GET /health: disponibilidad del servicio y de su base."""

from fastapi import APIRouter

from app.core import db
from app.core.errores import ServicioNoDisponible
from app.schemas.salud import Salud

router = APIRouter(tags=["Salud"])


@router.get(
    "/health",
    response_model=Salud,
    operation_id="verificarSalud",
    summary="Verificar que el servicio responde",
)
def verificar_salud() -> Salud:
    """No exige token. Responde 200 si el servicio y su base están disponibles; si no, 503."""
    if not db.base_disponible():
        raise ServicioNoDisponible()
    return Salud(status="ok")
