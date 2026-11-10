"""Agent endpoints: list agents, run one on a task, and review past runs (audit trail)."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import registry, runner
from app.agents.tools import TOOLS, ToolContext
from app.database import get_db
from app.models import AgentRun
from app.schemas import AgentInfo, AgentRunList, AgentRunOut, AgentRunRequest
from app.services.embeddings import Embedder, get_embedder
from app.services.llm import ChatModel, get_chat

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
def list_agents():
    return [
        AgentInfo(
            name=a.name,
            title=a.title,
            description=a.description,
            allowed_tools=list(a.allowed_tools),
            max_steps=a.max_steps,
        )
        for a in registry.AGENTS.values()
    ]


@router.get("/runs", response_model=AgentRunList)
def list_runs(
    agent: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    stmt = select(AgentRun)
    count_stmt = select(func.count()).select_from(AgentRun)
    if agent:
        stmt = stmt.where(AgentRun.agent == agent)
        count_stmt = count_stmt.where(AgentRun.agent == agent)
    total = db.scalar(count_stmt) or 0
    items = db.scalars(stmt.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)).all()
    return AgentRunList(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.post("/{name}/run", response_model=AgentRunOut)
def run_agent(
    name: str,
    request: AgentRunRequest,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    chat: ChatModel = Depends(get_chat),
):
    spec = registry.get_agent(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{name}'.")

    started = time.perf_counter()
    result = runner.run_agent(spec, request.task, chat, ToolContext(db=db, embedder=embedder), TOOLS)
    run = AgentRun(
        id=uuid.uuid4().hex,
        agent=spec.name,
        task=request.task,
        status=result.status,
        answer=result.answer,
        steps=result.steps,
        sources=result.sources,
        model=result.model,
        error=result.error,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(run)
    db.commit()  # the run is recorded even when it failed (audit trail)

    if result.status == "failed":
        raise HTTPException(status_code=503, detail=result.error or "The AI engine is unavailable.")
    return run
