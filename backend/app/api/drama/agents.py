"""Drama agent endpoints: summary, episode script, route, chat."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_drama import (
    DramaAddEpisodeRequest,
    DramaChatRequest,
    DramaEpisodeScriptRequest,
    DramaRouteRequest,
    DramaScriptOut,
    DramaScriptSummaryRequest,
)
from app.services.billing import run_billed_ephemeral
from app.services.drama.access import get_owned_drama_project
from app.services.drama.agents import (
    MAX_DRAMA_EPISODES,
    append_manual_episode,
    count_completed_episodes,
    resolve_episode_target,
)
from app.services.billing.http import http_exception_for_value_error
from app.services.drama.jobs import dispatch_episode_scripts_job, dispatch_script_summary_job
from app.services.drama.llm import DramaLlmUnavailableError, drama_chat_text

router = APIRouter()
logger = logging.getLogger("app.drama.agents")

# summary_generating_at 超过该时长仍无结果，允许重新入队
SUMMARY_GENERATING_STALE_MINUTES = 25


def _summary_generating_is_stale(params: dict) -> bool:
    # 判断 generating 是否已超时（避免 Celery 失败/丢任务后前端永久转圈）
    started_raw = params.get("summary_generating_at")
    if not started_raw:
        return True
    try:
        started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > timedelta(minutes=SUMMARY_GENERATING_STALE_MINUTES)


@router.post("/agents/script_summary")
async def script_summary(
    body: DramaScriptSummaryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 入队摘要任务，立即返回；前端轮询 script.params.summary_status
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script:
        raise HTTPException(status_code=400, detail="缺少剧本")
    creative = (body.creative or project.script.source or "").strip()
    if len(creative) < 20:
        raise HTTPException(status_code=400, detail="创意文案至少 20 字")

    project.script.source = creative
    params = dict(project.script.params or {})
    if body.episode_count:
        params["episode_count"] = int(body.episode_count)
        proj_params = dict(project.params or {})
        proj_params["episode_count"] = int(body.episode_count)
        project.params = proj_params
    if body.image_style_id:
        params["image_style_id"] = str(body.image_style_id)
        proj_params = dict(project.params or {})
        proj_params["image_style_id"] = str(body.image_style_id)
        project.params = proj_params
    existing_status = str(params.get("summary_status") or "")
    if existing_status == "generating" and not _summary_generating_is_stale(params):
        logger.info(
            "剧本摘要已在生成中，跳过重复入队 project_id=%s user_id=%s",
            project.id,
            user.id,
        )
        await db.commit()
        return {
            "ok": True,
            "queued": True,
            "status": "generating",
            "task_id": None,
            "script": DramaScriptOut.model_validate(project.script).model_dump(),
        }
    if existing_status == "generating":
        logger.warning(
            "剧本摘要 generating 超时，允许重新入队 project_id=%s user_id=%s started=%s",
            project.id,
            user.id,
            params.get("summary_generating_at"),
        )
    params["summary_status"] = "generating"
    params["summary_generating_at"] = datetime.now(timezone.utc).isoformat()
    params.pop("summary_error", None)
    project.script.params = params

    try:
        task_id = await dispatch_script_summary_job(db, user, project.id)
    except ValueError as exc:
        await db.rollback()
        raise http_exception_for_value_error(exc) from exc
    logger.info(
        "已入队剧本摘要 project_id=%s user_id=%s task_id=%s creative_len=%s",
        project.id,
        user.id,
        task_id,
        len(creative),
    )
    return {
        "ok": True,
        "queued": True,
        "status": "generating",
        "task_id": task_id,
        "script": DramaScriptOut.model_validate(project.script).model_dump(),
    }


@router.post("/agents/episode_script")
async def episode_script(
    body: DramaEpisodeScriptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 入队完整分集生成或单集优化；前端轮询 episode_content_status / episode_optimize_status
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script or not project.script.summary:
        raise HTTPException(status_code=400, detail="请先生成剧本摘要")

    summary = project.script.summary if isinstance(project.script.summary, dict) else {}
    total = resolve_episode_target(summary, project.params, project.script.params)
    if summary.get("episodeCount") != total:
        summary = {**summary, "episodeCount": total}
        project.script.summary = summary

    params = dict(project.script.params or {})
    episode_number = int(body.episode_number) if body.episode_number else None
    draft = (body.draft or "").strip() or None
    generate_mode = (body.generate_mode or "").strip().lower() or None
    if generate_mode in {"", "optimize", "draft"}:
        generate_mode = "optimize" if episode_number else None
    if generate_mode and generate_mode not in {"optimize", "summary", "body", "full", "brief"}:
        raise HTTPException(status_code=400, detail="generate_mode 须为 optimize/summary/body/full/brief")

    if episode_number:
        if str(params.get("episode_content_status") or "") == "generating":
            raise HTTPException(status_code=409, detail="全集剧本正在生成，请稍后再优化单集")
        if str(params.get("episode_optimize_status") or "") == "generating":
            logger.info(
                "单集剧本已在优化，跳过重复入队 project_id=%s episode_number=%s",
                project.id,
                episode_number,
            )
            await db.commit()
            return {
                "ok": True,
                "queued": True,
                "status": "generating",
                "task_id": None,
                "episodes": [],
                "total_generated": count_completed_episodes(
                    _existing_episodes(project.script.episode_content), total
                ),
                "total_target": total,
                "done": False,
                "script": DramaScriptOut.model_validate(project.script).model_dump(),
            }

        existing = _existing_episodes(project.script.episode_content)
        # 生成前可写入本集创意/标题
        creative_in = (body.creative or "").strip()
        title_in = (body.title or "").strip()
        if creative_in or title_in:
            from app.services.drama.agents import merge_episode_bodies

            patch: dict = {"episodeNumber": episode_number, "body": ""}
            cur = next(
                (
                    x
                    for x in existing
                    if isinstance(x, dict) and int(x.get("episodeNumber") or 0) == episode_number
                ),
                None,
            )
            if cur:
                patch["body"] = str(cur.get("body") or "")
                patch["summary"] = str(cur.get("summary") or "")
                patch["creative"] = creative_in or str(cur.get("creative") or "")
                patch["title"] = title_in or str(cur.get("title") or f"第 {episode_number} 集")
                if str(cur.get("origin") or "") == "manual":
                    patch["origin"] = "manual"
            else:
                patch["creative"] = creative_in
                patch["title"] = title_in or f"第 {episode_number} 集"
                patch["origin"] = "manual"
            existing = merge_episode_bodies(existing, [patch], prefer_incoming=True)
            project.script.episode_content = {"episodes": existing}

        mode = generate_mode or "optimize"
        if mode == "optimize":
            if not draft:
                raise HTTPException(status_code=400, detail="请先输入本集剧本草稿，再让 AI 优化")
            if len(draft) < 20:
                raise HTTPException(status_code=400, detail="剧本草稿至少 20 字")
        elif mode in {"summary", "full"}:
            cur_creative = creative_in
            if not cur_creative:
                cur = next(
                    (
                        x
                        for x in existing
                        if isinstance(x, dict) and int(x.get("episodeNumber") or 0) == episode_number
                    ),
                    None,
                )
                cur_creative = str((cur or {}).get("creative") or "").strip()
            if len(cur_creative) < 20:
                raise HTTPException(status_code=400, detail="请先填写本集原始创意（至少 20 字）")
        elif mode == "body":
            # 与 run_episode_body_from_brief 门槛一致：创意≥10 或摘要≥40，否则任务必败
            cur = next(
                (
                    x
                    for x in existing
                    if isinstance(x, dict) and int(x.get("episodeNumber") or 0) == episode_number
                ),
                None,
            )
            cur_creative = creative_in or str((cur or {}).get("creative") or "").strip()
            cur_summary = str((cur or {}).get("summary") or "").strip()
            if len(cur_creative) < 10 and len(cur_summary) < 40:
                raise HTTPException(status_code=400, detail="请先填写本集创意或摘要")
        elif mode == "brief":
            cur = next(
                (
                    x
                    for x in existing
                    if isinstance(x, dict) and int(x.get("episodeNumber") or 0) == episode_number
                ),
                None,
            )
            cur_body = str((cur or {}).get("body") or (cur or {}).get("content") or "").strip()
            if len(cur_body) < 80:
                raise HTTPException(status_code=400, detail="请先有本集剧本内容，再补齐创意与摘要")

        params["episode_optimize_status"] = "generating"
        params["episode_optimize_number"] = episode_number
        params["episode_optimize_mode"] = mode
        params.pop("episode_optimize_error", None)
        project.script.params = params
        try:
            task_id = await dispatch_episode_scripts_job(
                db,
                user,
                project.id,
                force=False,
                episode_number=episode_number,
                draft=draft,
                generate_mode=mode,
            )
        except ValueError as exc:
            await db.rollback()
            raise http_exception_for_value_error(exc) from exc
        logger.info(
            "已入队单集剧本 project_id=%s episode_number=%s mode=%s task_id=%s",
            project.id,
            episode_number,
            mode,
            task_id,
        )
        return {
            "ok": True,
            "queued": True,
            "status": "generating",
            "task_id": task_id,
            "episodes": [],
            "total_generated": count_completed_episodes(
                _existing_episodes(project.script.episode_content), total
            ),
            "total_target": total,
            "done": False,
            "assets_created_count": 0,
            "script": DramaScriptOut.model_validate(project.script).model_dump(),
        }

    if str(params.get("episode_content_status") or "") == "generating" and not body.force:
        existing = _existing_episodes(project.script.episode_content)
        generated = count_completed_episodes(existing, total)
        logger.info(
            "分集剧本已在生成中，跳过重复入队 project_id=%s progress=%s/%s",
            project.id,
            generated,
            total,
        )
        await db.commit()
        return {
            "ok": True,
            "queued": True,
            "status": "generating",
            "task_id": None,
            "episodes": [],
            "total_generated": generated,
            "total_target": total,
            "done": False,
            "script": DramaScriptOut.model_validate(project.script).model_dump(),
        }

    params["episode_content_status"] = "generating"
    params["episode_count"] = total
    params.pop("episode_content_error", None)
    if body.force:
        existing = _existing_episodes(project.script.episode_content)
        if existing:
            project.script.episode_content = {
                "episodes": [
                    {
                        "episodeNumber": int(item.get("episodeNumber") or 0),
                        "title": str(item.get("title") or f"第 {item.get('episodeNumber')} 集"),
                        "body": "",
                    }
                    for item in existing
                    if isinstance(item, dict) and int(item.get("episodeNumber") or 0) >= 1
                ]
            }
        params["episode_content_progress"] = {"done": 0, "total": total}
    project.script.params = params

    try:
        task_id = await dispatch_episode_scripts_job(db, user, project.id, force=bool(body.force))
    except ValueError as exc:
        await db.rollback()
        raise http_exception_for_value_error(exc) from exc
    existing = _existing_episodes(project.script.episode_content)
    generated = count_completed_episodes(existing, total)
    logger.info(
        "已入队分集剧本 project_id=%s user_id=%s task_id=%s force=%s target=%s done=%s",
        project.id,
        user.id,
        task_id,
        bool(body.force),
        total,
        generated,
    )
    return {
        "ok": True,
        "queued": True,
        "status": "generating",
        "task_id": task_id,
        "episodes": [],
        "total_generated": generated,
        "total_target": total,
        "done": False,
        "script": DramaScriptOut.model_validate(project.script).model_dump(),
    }


def _existing_episodes(content: object) -> list:
    # 从 episode_content 取出分集数组
    if isinstance(content, dict) and isinstance(content.get("episodes"), list):
        return list(content["episodes"])
    if isinstance(content, list):
        return list(content)
    return []


def _apply_episode_count(project, script, total: int) -> None:
    # 同步项目 / 剧本 / 摘要上的目标集数
    summary = dict(script.summary) if isinstance(script.summary, dict) else {}
    summary["episodeCount"] = int(total)
    script.summary = summary
    sparams = dict(script.params or {})
    sparams["episode_count"] = int(total)
    script.params = sparams
    pparams = dict(project.params or {})
    pparams["episode_count"] = int(total)
    project.params = pparams


@router.post("/agents/add_episode")
async def add_episode(
    body: DramaAddEpisodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """手动追加一集空分集，供用户粘贴剧本后再 AI 优化。"""
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script or not project.script.summary:
        raise HTTPException(status_code=400, detail="请先生成剧本摘要")
    params = dict(project.script.params or {})
    if str(params.get("episode_content_status") or "") == "generating":
        raise HTTPException(status_code=409, detail="全集剧本正在生成，请完成后再加集")
    existing = _existing_episodes(project.script.episode_content)
    if len(existing) >= MAX_DRAMA_EPISODES:
        raise HTTPException(status_code=400, detail=f"最多 {MAX_DRAMA_EPISODES} 集")
    try:
        episodes, episode_number = append_manual_episode(existing, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.script.episode_content = {"episodes": episodes}
    current_total = resolve_episode_target(
        project.script.summary if isinstance(project.script.summary, dict) else {},
        project.params,
        project.script.params,
    )
    _apply_episode_count(
        project,
        project.script,
        max(current_total, episode_number, len(episodes)),
    )
    await db.commit()
    await db.refresh(project.script)
    logger.info(
        "手动加集 project_id=%s episode_number=%s total=%s",
        project.id,
        episode_number,
        episode_number,
    )
    return {
        "ok": True,
        "episode_number": episode_number,
        "script": DramaScriptOut.model_validate(project.script).model_dump(),
    }


@router.post("/agents/route")
async def route_agent(body: DramaRouteRequest, user: User = Depends(get_current_user)) -> dict:
    _ = user
    msg = (body.message or "").strip().lower()
    if any(k in msg for k in ("剧本", "短剧", "漫剧", "分集", "大纲", "编剧")):
        return {"agent": "drama_script", "action": "create_project"}
    if any(k in msg for k in ("画布", "节点", "自由创作")):
        return {"agent": "canvas", "action": "open_canvas"}
    return {"agent": "chat", "action": "chat"}


@router.post("/ai/chat")
async def ai_chat(
    body: DramaChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    logger.info("漫剧聊天 user_id=%s project_id=%s", user.id, body.project_id)

    async def _do_chat() -> str:
        from app.services.billing import record_line

        try:
            reply = await drama_chat_text(
                "你是 PRINTFILM 漫剧创作助手，帮助用户构思短剧创意、人物与分集结构。用简洁中文回答。",
                body.message,
            )
        except DramaLlmUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await record_line(
            db,
            user_id=user.id,
            billing_key="llm_chat",
            model=get_settings().model_llm,
            estimated=True,
            drama_project_id=body.project_id,
            domain="drama",
        )
        return reply

    try:
        task, reply = await run_billed_ephemeral(
            db,
            user,
            domain="drama",
            task_type="agent_chat",
            executor=_do_chat,
            payload={"message_len": len(body.message or "")},
            drama_project_id=body.project_id,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return {"reply": reply, "task_id": task.id}
