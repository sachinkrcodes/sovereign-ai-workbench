"""Agent endpoints: list agents, run one on a task, and review past runs (audit trail)."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import registry, runner
from app.agents.tools import TOOLS, ToolContext
from app.config import Settings, get_settings
from app.database import get_db
from app.deps import enforce_token_budget, require_role
from app.models import AgentRun, User
from app.schemas import AgentInfo, AgentRunList, AgentRunOut, AgentRunRequest
from app.services import audit, usage
from app.services.embeddings import Embedder, get_embedder
from app.services.llm import ChatModel, get_chat

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _with_notice(run: AgentRun) -> AgentRun:
    run.notice = runner.citation_notice(run.answer, run.sources or [])  # computed, not stored
    return run


@router.get("", response_model=list[AgentInfo], dependencies=[Depends(require_role("viewer"))])
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
    user: User = Depends(require_role("viewer")),
):
    """Admins see every run; everyone else sees only their own."""
    conditions = []
    if agent:
        conditions.append(AgentRun.agent == agent)
    if user.role != "admin":
        conditions.append(AgentRun.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(AgentRun).where(*conditions)) or 0
    items = db.scalars(
        select(AgentRun).where(*conditions).order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return AgentRunList(items=[_with_notice(i) for i in items], total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    run = db.get(AgentRun, run_id)
    # Someone else's run looks exactly like a missing one (do not reveal that it exists).
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=404, detail="Run not found.")
    return _with_notice(run)


@router.post("/{name}/run", response_model=AgentRunOut)
def run_agent(
    name: str,
    body: AgentRunRequest,
    request: Request,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    chat: ChatModel = Depends(get_chat),
    settings: Settings = Depends(get_settings),
):
    spec = registry.get_agent(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{name}'.")
    enforce_token_budget(db, user, settings, request)

    started = time.perf_counter()
    result = runner.run_agent(spec, body.task, chat, ToolContext(db=db, embedder=embedder), TOOLS)
    duration_ms = int((time.perf_counter() - started) * 1000)
    run = AgentRun(
        id=uuid.uuid4().hex,
        agent=spec.name,
        task=body.task,
        status=result.status,
        answer=result.answer,
        steps=result.steps,
        sources=result.sources,
        model=result.model,
        error=result.error,
        user_id=user.id,
        duration_ms=duration_ms,
    )
    db.add(run)
    db.commit()  # the run is recorded even when it failed (audit trail)

    if result.prompt_tokens or result.completion_tokens:
        usage.record_usage(
            db, user=user, kind="agent_run", model=result.model,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            duration_ms=duration_ms, ref=run.id,
        )
    audit.record(
        db,
        action="agent.run",
        status="failed" if result.status == "failed" else "success",
        user=user,
        resource_type="agent_run",
        resource_id=run.id,
        detail={
            "agent": spec.name,
            "task": audit.clip(body.task),
            "run_status": result.status,
            "tool_calls": len(result.steps),
            "denied_tool_calls": sum(1 for s in result.steps if s["status"] == "denied"),
        },
        request=request,
    )

    if result.status == "failed":
        raise HTTPException(status_code=503, detail=result.error or "The AI engine is unavailable.")
    return _with_notice(run)
