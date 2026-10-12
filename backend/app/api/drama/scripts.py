"""Drama script endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_drama import DramaScriptOut
from app.services.drama.access import get_owned_drama_project

router = APIRouter()


class ScriptUpdateBody(BaseModel):
    source: str | None = None
    summary: dict | None = None
    episode_content: dict | list | None = None
    image_style_id: str | None = None
    name: str | None = None


@router.get("/scripts/{project_id}", response_model=DramaScriptOut)
async def get_script(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaScriptOut:
    project = await get_owned_drama_project(db, project_id, user, with_script=True)
    if not project.script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return DramaScriptOut.model_validate(project.script)


@router.patch("/scripts/{project_id}", response_model=DramaScriptOut)
async def update_script(
    project_id: int,
    body: ScriptUpdateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaScriptOut:
    project = await get_owned_drama_project(db, project_id, user, with_script=True)
    if not project.script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    script = project.script
    if body.source is not None:
        script.source = body.source
    if body.summary is not None:
        prev_summary = script.summary if isinstance(script.summary, dict) else {}
        script.summary = body.summary
        from app.services.drama.agents import normalize_series_title, pick_auto_project_title

        new_series = normalize_series_title(body.summary.get("seriesTitle"))
        old_series = normalize_series_title(prev_summary.get("seriesTitle"))
        # 用户在摘要里主动改了剧名 → 同步项目名；否则仅覆盖「默认/截断」标题
        if new_series and new_series != old_series:
            project.title = new_series
            script.name = new_series
        else:
            auto_title = pick_auto_project_title(
                body.summary,
                creative=(script.source or "").strip(),
                current_title=project.title or "",
            )
            if auto_title:
                project.title = auto_title
                script.name = auto_title
    if body.episode_content is not None:
        script.episode_content = body.episode_content
    if body.name is not None:
        script.name = body.name
    if body.image_style_id is not None:
        params = dict(script.params or {})
        params["image_style_id"] = body.image_style_id
        script.params = params
        pparams = dict(project.params or {})
        pparams["image_style_id"] = body.image_style_id
        project.params = pparams
    await db.commit()
    await db.refresh(script)
    return DramaScriptOut.model_validate(script)
