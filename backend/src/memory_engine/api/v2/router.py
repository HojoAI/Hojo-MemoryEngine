"""API v2 router aggregation."""

from fastapi import APIRouter

from memory_engine.api.v2 import memory_routes

api_v2_router = APIRouter(prefix="/api/v2")
api_v2_router.include_router(memory_routes.router)
