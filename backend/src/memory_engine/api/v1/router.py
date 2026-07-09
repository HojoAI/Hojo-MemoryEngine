"""API v1 router aggregation."""

from fastapi import APIRouter

from memory_engine.api.v1 import (
    admin_routes,
    billing_routes,
    capability_routes,
    data_routes,
    governance_routes,
    internal_routes,
    llm_routes,
    onboarding_routes,
    orchestration_routes,
    schema_changelog_routes,
    schema_routes,
    user_routes,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(admin_routes.router)
api_router.include_router(onboarding_routes.router)
api_router.include_router(internal_routes.router)
api_router.include_router(capability_routes.router)
api_router.include_router(schema_changelog_routes.router)
api_router.include_router(schema_routes.router)
api_router.include_router(data_routes.router)
api_router.include_router(billing_routes.router)
api_router.include_router(llm_routes.router)
api_router.include_router(user_routes.router)
api_router.include_router(orchestration_routes.router)
api_router.include_router(governance_routes.router)
