"""Liveness and readiness probes. AWS load balancers and Kubernetes call these later."""

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict:
    """Is the process alive? (Does not touch the database.)"""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    """Can the app serve traffic? (Checks the database.)"""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    return {"status": "ready", "database": "up"}


@router.get("/health/ai")
def ai_health(settings: Settings = Depends(get_settings)) -> dict:
    """Is Ollama running, and are the two models installed? (Handy when something fails.)"""
    base = settings.ollama_base_url.rstrip("/")
    try:
        response = httpx.get(f"{base}/api/tags", timeout=3)
        response.raise_for_status()
        installed = [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:
        return {
            "ollama": "down",
            "base_url": base,
            "hint": "Install and start Ollama from https://ollama.com, then run the pull commands.",
        }

    def check(model: str) -> dict:
        present = model in installed or f"{model}:latest" in installed
        result = {"name": model, "installed": present}
        if not present:
            result["fix"] = f"ollama pull {model}"
        return result

    embedding = check(settings.embedding_model)
    chat = check(settings.chat_model)
    return {
        "ollama": "up",
        "base_url": base,
        "embedding_model": embedding,
        "chat_model": chat,
        "ready": embedding["installed"] and chat["installed"],
    }
