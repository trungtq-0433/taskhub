"""Aggregate router mounted under the configured API prefix."""

from fastapi import APIRouter

from app.api.routers import projects, tags

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(tags.router)
