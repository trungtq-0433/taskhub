"""Liveness probe for the container runtime. Outside the API prefix and the schema."""

from fastapi import APIRouter

router = APIRouter(include_in_schema=False)


@router.get("/health")
async def health() -> dict[str, str]:
    """200 while the process serves HTTP — liveness, not readiness.

    It checks no dependency on purpose. A database outage already answers 503 on
    real requests; probing it here would mark a healthy process unhealthy and
    spend a pool connection every interval.
    """
    return {"status": "ok"}
