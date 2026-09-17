"""Aggregate router mounted under the configured API prefix."""

from fastapi import APIRouter

from app.api.routers import health

api_router = APIRouter()
api_router.include_router(health.router)
