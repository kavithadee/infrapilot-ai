from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }
