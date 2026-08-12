# routes package
from src.routes.leads import router as leads_router
from src.routes.history import router as history_router

__all__ = ["leads_router", "history_router"]
