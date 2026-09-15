"""FastAPI router composition for the public HTTP API."""

from fastapi import APIRouter

from disaster_monitor.presentation.http.access_context_routes import (
    router as access_context_router,
)
from disaster_monitor.presentation.http.assistant_routes import (
    get_conversation_turn,
)
from disaster_monitor.presentation.http.assistant_routes import (
    router as assistant_router,
)
from disaster_monitor.presentation.http.catalog_routes import router as catalog_router
from disaster_monitor.presentation.http.earthquake_context_routes import (
    router as earthquake_context_router,
)
from disaster_monitor.presentation.http.field_report_routes import (
    router as field_report_router,
)
from disaster_monitor.presentation.http.ground_imagery_routes import (
    router as ground_imagery_router,
)
from disaster_monitor.presentation.http.incident_routes import (
    router as incident_router,
)
from disaster_monitor.presentation.http.interoperability_routes import (
    router as interoperability_router,
)
from disaster_monitor.presentation.http.operator_interop_routes import (
    router as operator_interop_router,
)
from disaster_monitor.presentation.http.system_routes import (
    get_operational_metrics,
)
from disaster_monitor.presentation.http.system_routes import (
    router as system_router,
)

router = APIRouter()
router.include_router(access_context_router)
router.include_router(system_router)
router.include_router(catalog_router)
router.include_router(earthquake_context_router)
router.include_router(field_report_router)
router.include_router(ground_imagery_router)
router.include_router(incident_router)
router.include_router(interoperability_router)
router.include_router(operator_interop_router)
router.include_router(assistant_router)

__all__ = ["get_conversation_turn", "get_operational_metrics", "router"]
