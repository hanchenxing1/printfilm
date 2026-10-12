"""Drama episode / fragment endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import (
    DramaEpisode,
    DramaEpisodeFragment,
    DramaProject,
)
from app.schemas_drama import (
    DramaActivateVideoVersionRequest,
    DramaComposeEpisodeRequest,
    DramaConfirmEpisodeOut,
    DramaConfirmEpisodeRequest,
    DramaEpisodeOut,
    DramaEpisodeUpdate,
    DramaFragmentOut,
    DramaGenerateRequest,
    DramaPlanFragmentsRequest,
    DramaSaveFragmentsRequest,
)
from app.schemas_tasks import TaskCreateRequest, TaskTargetBind
from app.services.agent.compose import parse_skill_ids
from app.services.billing import run_billed_ephemeral
from app.services.billing.http import http_exception_for_value_error
from app.services.drama.access import (
    count_user_inflight_fragment_video_tasks,
    detach_task_fragment_refs,
    filter_valid_project_asset_ids,
    get_owned_drama_project,
    get_owned_episode,
    load_episode_fragments,
    replace_fragment_asset_refs,
    match_fragments_for_generate,
)
from app.services.drama.generation import (
    activate_fragment_video_version,
    collect_active_fragment_ids_from_tasks,
    fragment_generation_status,
    overlay_fragment_status_with_active_task,
    ensure_fragment_last_frame_url,
    project_link_last_frame_enabled,
    read_fragment_last_frame_url,
    reconcile_orphaned_fragment_generations,
)
from app.services.drama.build_fragments import prepare_fragment_content
from app.services.drama.fragment_content_duration import resolve_seedance_duration_from_content
from app.services.drama.billing_util import record_seed_assets_llm_usage
from app.services.drama.jobs import (
    cancel_all_episode_video_jobs,
    cancel_episode_video_jobs,
    clear_episode_video_cancelled,
    reconcile_applied_fragment_video_tasks,
)
from app.config import get_settings
from app.services.drama.seed import (
    require_confirmable_episode_body,
    seed_assets_from_script,
    seed_episodes_from_script,
    seed_single_episode_from_script,
)
from app.services.tasks.service import (
    cancel_fragment_video_tasks_for_fragments,
    cancel_tasks_for_scope,
    create_task,
    list_active_tasks_for_owner,
    rebalance_project_fragment_video_queue,
)

router = APIRouter()
logger = logging.getLogger("app.drama.episodes")


def _fragment_out(frag: DramaEpisodeFragment) -> DramaFragmentOut:
    asset_ids = [r.asset_id for r in (frag.asset_references or [])]
    content = prepare_fragment_content(
        frag.content or "",
        duration_sec=int(frag.duration_sec or 0) or None,
        is_opening=int(frag.sort_order or 0) == 0,
    )
    return DramaFragmentOut(
        id=frag.id,
        episode_id=frag.episode_id,
        sort_order=frag.sort_order,
        content=content,
        cover=frag.cover or "",
        video=frag.video or "",
        duration_sec=frag.duration_sec,
        params=frag.params,
        asset_ids=asset_ids,
    )


def _episode_out(ep: DramaEpisode) -> DramaEpisodeOut:
    frags = sorted(ep.fragments or [], key=lambda f: f.sort_order)
    return DramaEpisodeOut(
        id=ep.id,
        name=ep.name,
        params=ep.params,
        project_id=ep.project_id,
        fragments=[_fragment_out(f) for f in frags],
        active_tasks=list(getattr(ep, "active_tasks", []) or []),
    )


def _expand_episode_task_items(active_tasks: list) -> list[dict]:
    """把平台任务展开成分集页可直接消费的任务摘要。"""
    items: list[dict] = []
    for task in active_tasks:
        target_fragments = [
            int(target.target_id)
            for target in (getattr(task, "targets", []) or [])
            if getattr(target, "target_type", "") == "fragment" and isinstance(target.target_id, int)
        ]
        if task.task_type == "fragment_video" and target_fragments:
            for fragment_id in target_fragments:
                items.append(
                    {
                        "id": task.id,
                        "domain": task.domain,
                        "task_type": task.task_type,
                        "status": task.status,
                        "current_step_key": task.current_step_key,
                        "current_step_status": task.current_step_status,
                        "progress_percent": task.progress_percent,
                        "cancel_requested": task.cancel_requested,
                        "provider_task_id": task.provider_task_id,
                        "error_message": task.error_message,
                        "project_id": task.project_id,
                        "drama_project_id": task.drama_project_id,
                        "episode_id": task.episode_id,
                        "fragment_id": fragment_id,
                        "asset_id": task.asset_id,
                        "shot_id": task.shot_id,
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                    }
                )
            continue
        items.append(
            {
                "id": task.id,
                "domain": task.domain,
                "task_type": task.task_type,
                "status": task.status,
                "current_step_key": task.current_step_key,
                "current_step_status": task.current_step_status,
                "progress_percent": task.progress_percent,
                "cancel_requested": task.cancel_requested,
                "provider_task_id": task.provider_task_id,
                "error_message": task.error_message,
                "project_id": task.project_id,
                "drama_project_id": task.drama_project_id,
                "episode_id": task.episode_id,
                "fragment_id": task.fragment_id,
                "asset_id": task.asset_id,
                "shot_id": task.shot_id,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
        )
    return items


# 给分集挂上统一任务中心活动任务，便于查询侧逐步切换
async def _episode_out_with_tasks(
    db: AsyncSession,
    user: User,
    ep: DramaEpisode,
) -> DramaEpisodeOut:
    active_tasks = await list_active_tasks_for_owner(
        db,
        user.id,
        drama_project_id=ep.project_id,
    )
    # 单集详情只挂本集任务；勿把全项目活跃任务混入，否则其他集生成中会误锁「重新分镜」
    ep.active_tasks = _expand_episode_task_items(
        [task for task in active_tasks if int(task.episode_id or 0) == int(ep.id)]
    )
    return _episode_out(ep)


@router.get("/episodes", response_model=list[DramaEpisodeOut])
async def list_episodes(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DramaEpisodeOut]:
    await get_owned_drama_project(db, project_id, user)
    from app.services.drama.seed import merge_duplicate_episodes_by_number

    # 打开分镜页时顺手合并同号重复行
    merged = await merge_duplicate_episodes_by_number(db, project_id)
    if merged:
        await db.commit()
    result = await db.execute(
        select(DramaEpisode)
        .where(DramaEpisode.project_id == project_id)
        .options(
            selectinload(DramaEpisode.fragments).selectinload(DramaEpisodeFragment.asset_references)
        )
        .order_by(DramaEpisode.id.asc())
    )
    episodes = list(result.scalars().all())
    episodes.sort(
        key=lambda ep: (
            int((ep.params or {}).get("episodeNumber") or 0) if isinstance(ep.params, dict) else 0,
            int(ep.id or 0),
        )
    )
    active_tasks = await list_active_tasks_for_owner(db, user.id, drama_project_id=project_id)
    by_episode_id: dict[int, list] = {}
    for task in active_tasks:
        if task.episode_id is None:
            continue
        by_episode_id.setdefault(int(task.episode_id), []).append(task)
    for ep in episodes:
        ep.active_tasks = _expand_episode_task_items(by_episode_id.get(int(ep.id), []))
    return [_episode_out(ep) for ep in episodes]


@router.post("/episodes/seed_from_script", response_model=list[DramaEpisodeOut])
async def seed_episodes(
    project_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DramaEpisodeOut]:
    project = await get_owned_drama_project(db, project_id, user, with_script=True)
    logger.info(
        "按剧本切分镜 project_id=%s force=%s user_id=%s",
        project_id,
        force,
        user.id,
    )
    try:
        await seed_episodes_from_script(db, project, force=force)
    except ValueError as exc:
        logger.warning("切分镜失败 project_id=%s err=%s", project_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await db.execute(
        select(DramaEpisode)
        .where(DramaEpisode.project_id == project_id)
        .options(
            selectinload(DramaEpisode.fragments).selectinload(DramaEpisodeFragment.asset_references)
        )
        .order_by(DramaEpisode.id.asc())
    )
    episodes = result.scalars().all()
    frag_total = sum(len(ep.fragments or []) for ep in episodes)
    logger.info(
        "切分镜完成 project_id=%s episodes=%s fragments=%s",
        project_id,
        len(episodes),
        frag_total,
    )
    active_tasks = await list_active_tasks_for_owner(db, user.id, drama_project_id=project_id)
    by_episode_id: dict[int, list] = {}
    for task in active_tasks:
        if task.episode_id is None:
            continue
        by_episode_id.setdefault(int(task.episode_id), []).append(task)
    for episode in episodes:
        episode.active_tasks = _expand_episode_task_items(by_episode_id.get(int(episode.id), []))
    return [_episode_out(episode) for episode in episodes]


@router.post("/episodes/confirm_from_script", response_model=DramaConfirmEpisodeOut)
async def confirm_episode_from_script(
    body: DramaConfirmEpisodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaConfirmEpisodeOut:
    """确认一集剧本：增量抽取资产并只切该集分镜。"""
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script:
        raise HTTPException(status_code=400, detail="缺少剧本")
    try:
        require_confirmable_episode_body(project.script.episode_content, body.episode_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    locked = (
        await db.execute(
            select(DramaProject).where(DramaProject.id == project.id).with_for_update()
        )
    ).scalar_one()
    params = dict(locked.params or {}) if isinstance(locked.params, dict) else {}
    if str(params.get("assets_seed_status") or "") == "generating":
        raise HTTPException(status_code=409, detail="资产抽取进行中，请稍后再确认")

    params["assets_seed_status"] = "generating"
    params["assets_seed_generating_at"] = datetime.now(UTC).isoformat()
    params.pop("assets_seed_error", None)
    locked.params = params
    await db.commit()

    created_count = 0
    try:

        async def _do_confirm():
            project_inner = await get_owned_drama_project(
                db, body.project_id, user, with_script=True
            )
            seed_result = await seed_assets_from_script(db, project_inner)
            await record_seed_assets_llm_usage(db, user, body.project_id, seed_result)
            project_after = await get_owned_drama_project(
                db, body.project_id, user, with_script=True
            )
            episode = await seed_single_episode_from_script(
                db, project_after, body.episode_number
            )
            return seed_result, episode

        _task, pair = await run_billed_ephemeral(
            db,
            user,
            domain="drama",
            task_type="seed_assets",
            executor=_do_confirm,
            drama_project_id=body.project_id,
            payload={
                "sync": True,
                "confirm_episode": True,
                "episode_number": body.episode_number,
            },
            commit=False,
        )
        seed_result, episode = pair
        created_count = int(seed_result.created_count or 0)
        project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "done"
        params.pop("assets_seed_error", None)
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
    except ValueError as exc:
        project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = str(exc)[:500]
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise http_exception_for_value_error(exc) from exc
    except HTTPException:
        project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = "确认分集未完成"
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise
    except Exception:
        project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = "确认分集失败"
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise

    ep = await get_owned_episode(db, int(episode.id), user)
    out = await _episode_out_with_tasks(db, user, ep)
    logger.info(
        "确认分集完成 project_id=%s episode_number=%s episode_id=%s assets_created=%s",
        body.project_id,
        body.episode_number,
        ep.id,
        created_count,
    )
    return DramaConfirmEpisodeOut(
        episode=out,
        assets_status="done",
        created_count=created_count,
    )


@router.get("/episodes/{episode_id}", response_model=DramaEpisodeOut)
async def get_episode(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaEpisodeOut:
    ep = await get_owned_episode(db, episode_id, user)
    return await _episode_out_with_tasks(db, user, ep)


@router.patch("/episodes/{episode_id}", response_model=DramaEpisodeOut)
async def update_episode(
    episode_id: int,
    body: DramaEpisodeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaEpisodeOut:
    ep = await get_owned_episode(db, episode_id, user)
    if body.name is not None:
        ep.name = body.name.strip() or ep.name
    if body.params is not None:
        ep.params = body.params
    await db.commit()
    return await _episode_out_with_tasks(db, user, ep)


@router.post("/episodes/{episode_id}/plan_fragments", response_model=DramaEpisodeOut)
async def plan_episode_fragments(
    episode_id: int,
    body: DramaPlanFragmentsRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaEpisodeOut:
    # 入队单集 LLM 分镜；前端轮询 episode.params.fragment_plan_status
    req = body or DramaPlanFragmentsRequest()
    ep = await get_owned_episode(db, episode_id, user)
    await get_owned_drama_project(db, ep.project_id, user)

    params = dict(ep.params or {})
    existing = str(params.get("fragment_plan_status") or "")
    # force 时允许重入队（避免旧任务异常后卡在 generating）
    if existing == "generating" and not req.force:
        logger.info("单集分镜已在进行中 episode_id=%s", episode_id)
        return await _episode_out_with_tasks(db, user, ep)
    if existing == "generating" and req.force:
        logger.warning("单集分镜强制重入队 episode_id=%s prev_status=generating", episode_id)

    if not req.force:
        # 非 force：有保护分镜则拒绝
        protected = any(
            (f.video or "").strip()
            or (isinstance(f.params, dict) and f.params.get("user_edited"))
            for f in (ep.fragments or [])
        )
        if protected:
            raise HTTPException(
                status_code=409,
                detail="本集含已生成视频或手改分镜，请确认后强制重新分镜",
            )

    params["fragment_plan_status"] = "generating"
    params.pop("fragment_plan_error", None)
    params["fragment_plan_mode"] = "llm"
    if req.subtitle_enabled is not None:
        params["subtitleEnabled"] = bool(req.subtitle_enabled)
        params["subtitleMode"] = "model" if bool(req.subtitle_enabled) else "post"
    if req.skill_ids is None:
        params.pop("fragment_plan_skill_ids", None)
    else:
        params["fragment_plan_skill_ids"] = parse_skill_ids(req.skill_ids) or []
    ep.params = params

    try:
        task = await create_task(
            db,
            user,
            TaskCreateRequest(
                domain="drama",
                task_type="fragment_plan",
                dedupe_key=f"drama:fragment_plan:episode:{episode_id}:force:{int(bool(req.force))}",
                payload={
                    "project_id": ep.project_id,
                    "episode_id": episode_id,
                    "fallback_rules": bool(req.fallback_rules),
                    "force": bool(req.force),
                    "skill_ids": parse_skill_ids(req.skill_ids) if req.skill_ids is not None else None,
                    "subtitle_enabled": bool(req.subtitle_enabled) if req.subtitle_enabled is not None else None,
                },
                drama_project_id=ep.project_id,
                episode_id=episode_id,
                targets=[
                    TaskTargetBind(target_type="drama_project", target_id=ep.project_id),
                    TaskTargetBind(target_type="episode", target_id=episode_id),
                ],
            ),
        )
    except ValueError as exc:
        await db.rollback()
        raise http_exception_for_value_error(exc) from exc
    logger.info(
        "已创建单集 LLM 分镜任务 episode_id=%s force=%s task_id=%s",
        episode_id,
        req.force,
        task.id,
    )
    # 再取一次带 fragments 的 episode
    ep = await get_owned_episode(db, episode_id, user)
    return await _episode_out_with_tasks(db, user, ep)


@router.post("/episodes/{episode_id}/fragments", response_model=DramaEpisodeOut)
async def save_fragments(
    episode_id: int,
    body: DramaSaveFragmentsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaEpisodeOut:
    """按 id 更新已有分镜、新增无 id 项、删除未提交项；删除时作废旧视频任务，避免 ID 轮转导致上下文丢失。"""
    ep = await get_owned_episode(db, episode_id, user)
    existing = {int(f.id): f for f in (ep.fragments or [])}
    keep_ids: set[int] = set()

    for item in body.fragments:
        item_id = int(item.id) if item.id else 0
        frag = existing.get(item_id) if item_id > 0 else None
        if frag is None:
            # 先挂上空集合，flush 后不要再 lazy load asset_references
            frag = DramaEpisodeFragment(episode_id=ep.id)
            frag.asset_references = []
            ep.fragments.append(frag)
            await db.flush()
        frag.sort_order = item.sort_order
        frag.content = prepare_fragment_content(
            item.content or "",
            duration_sec=int(item.duration_sec or 0) or None,
            is_opening=int(item.sort_order or 0) == 0,
        )
        frag.cover = (item.cover or "")[:1024]
        frag.video = (item.video or "")[:1024]
        frag.duration_sec = item.duration_sec
        frag.params = item.params
        keep_ids.add(int(frag.id))

        asset_ids = await filter_valid_project_asset_ids(
            db,
            ep.project_id,
            list(item.asset_ids or []),
        )
        await replace_fragment_asset_refs(db, frag, asset_ids)

    stale_ids = [fid for fid in existing if fid not in keep_ids]
    if stale_ids:
        await cancel_fragment_video_tasks_for_fragments(db, stale_ids)
        await detach_task_fragment_refs(db, stale_ids)
        for fid in stale_ids:
            old = existing.get(fid)
            if old is not None:
                await db.delete(old)
        await db.flush()

    await db.commit()
    frags = await load_episode_fragments(db, episode_id)
    logger.info(
        "已保存分镜 episode_id=%s count=%s ids=%s removed=%s",
        episode_id,
        len(frags),
        [f.id for f in frags],
        stale_ids,
    )
    ep.fragments = frags
    return await _episode_out_with_tasks(db, user, ep)


@router.post("/fragments/{fragment_id}/activate_video_version")
async def activate_video_version(
    fragment_id: int,
    body: DramaActivateVideoVersionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """将分镜历史成片版本切换为当前预览/导出所用视频。"""
    result = await db.execute(
        select(DramaEpisodeFragment).where(DramaEpisodeFragment.id == fragment_id)
    )
    fragment = result.scalar_one_or_none()
    if not fragment:
        raise HTTPException(status_code=404, detail="分镜不存在")
    await get_owned_episode(db, fragment.episode_id, user)
    status = str(fragment_generation_status(fragment).get("status") or "")
    if status in {"queued", "running", "generating"}:
        raise HTTPException(status_code=409, detail="分镜正在生成，请完成后再切换版本")
    try:
        payload = activate_fragment_video_version(fragment, body.version_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(fragment)
    return {"ok": True, **payload}


@router.post("/episodes/{episode_id}/generate")
async def generate_episode(
    episode_id: int,
    body: DramaGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 入队统一任务平台，前端用 generate_status 轮询
    ep = await get_owned_episode(db, episode_id, user)
    project = await get_owned_drama_project(db, ep.project_id, user)
    all_frags = await load_episode_fragments(db, episode_id)
    frags = match_fragments_for_generate(all_frags, body.fragment_ids)
    if not frags:
        logger.warning(
            "没有可生成的分镜 episode_id=%s requested=%s available=%s",
            episode_id,
            body.fragment_ids,
            [f.id for f in all_frags],
        )
        raise HTTPException(
            status_code=400,
            detail="没有可生成的分镜（保存后分镜已更新，请再点一次生成）",
        )

    # 已在排队/生成的分镜跳过；其余按镜序入队（衔接时后一镜等上一镜尾帧）
    idle_frags = [
        f
        for f in frags
        if fragment_generation_status(f).get("status") not in {"queued", "running", "generating"}
    ]
    idle_frags.sort(key=lambda f: int(f.sort_order or 0))
    if not idle_frags:
        raise HTTPException(
            status_code=409,
            detail="所选分镜正在生成，请等待完成后再试",
        )

    # 尾帧衔接：上一镜在生成/排队时可先入队本镜，由任务队列按镜序等待；未开上一镜则仍拒绝
    if project_link_last_frame_enabled(project):
        all_sorted = sorted(all_frags, key=lambda f: (int(f.sort_order or 0), int(f.id or 0)))
        index_by_id = {int(f.id): i for i, f in enumerate(all_sorted) if f.id is not None}
        idle_ids = {int(f.id) for f in idle_frags if f.id is not None}
        for frag in idle_frags:
            if frag.id is None:
                continue
            idx = index_by_id.get(int(frag.id))
            if idx is None or idx <= 0:
                continue
            prev = all_sorted[idx - 1]
            if prev.id is not None and int(prev.id) in idle_ids:
                continue
            prev_st = str(fragment_generation_status(prev).get("status") or "")
            if prev_st in {"queued", "running", "generating"}:
                continue
            prev_last = read_fragment_last_frame_url(prev)
            if not prev_last:
                prev_last = await ensure_fragment_last_frame_url(project, prev)
            if not prev_last and not (prev.video or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="已开启尾帧衔接：请先生成上一镜并等待尾帧就绪后，再点本镜生成",
                )

    # 清除进程内「本集已取消」标记，避免旧取消态把新入队任务立刻作废
    clear_episode_video_cancelled(episode_id)

    # 全部入队；超过单用户并发上限的镜保持 pending 排队，由调度器按空位激活
    limit = max(1, int(get_settings().drama_user_video_job_limit or 12))
    inflight = await count_user_inflight_fragment_video_tasks(db, user.id)
    activate_slots = max(0, limit - inflight)

    sequential = project_link_last_frame_enabled(project)
    frag_ids = [f.id for f in idle_frags]
    batch_key = f"drama:episode:{episode_id}:video:{uuid.uuid4().hex[:12]}"
    queued_at = datetime.now(UTC).isoformat()
    for f in idle_frags:
        params = dict(f.params or {})
        # 用户主动点生成：清零内部重试计数（上限只约束同一次任务内的自动重试）
        params.pop("generation_attempts", None)
        params["generation"] = {"status": "queued", "queued_at": queued_at, "message": "已入队"}
        f.params = params

    created_tasks: list[int] = []
    deferred_count = 0
    for index, f in enumerate(idle_frags):
        # 串行：先入队再由 rebalance 按镜序激活；并行：仅前 activate_slots 镜立即执行
        if sequential:
            defer_activation = True
        else:
            defer_activation = index >= activate_slots
        if defer_activation:
            deferred_count += 1
        has_video = bool((f.video or "").strip())
        duration_sec = resolve_seedance_duration_from_content(
            f.content or "",
            fallback=int(f.duration_sec or 8),
        )
        try:
            task = await create_task(
                db,
                user,
                TaskCreateRequest(
                    domain="drama",
                    task_type="fragment_video",
                    dedupe_key=f"drama:fragment_video:fragment:{f.id}",
                    batch_key=batch_key,
                    defer_activation=defer_activation,
                    payload={
                        "project_id": ep.project_id,
                        "episode_id": episode_id,
                        "fragment_ids": [f.id],
                        "sequential": sequential,
                        "batch_key": batch_key,
                        "batch_index": index,
                        "replace_existing_video": has_video,
                        "duration_sec": duration_sec,
                        "model_id": (body.model_id or "").strip() or None,
                    },
                    drama_project_id=ep.project_id,
                    episode_id=episode_id,
                    fragment_id=f.id,
                    targets=[
                        TaskTargetBind(target_type="drama_project", target_id=ep.project_id),
                        TaskTargetBind(target_type="episode", target_id=episode_id),
                        TaskTargetBind(target_type="fragment", target_id=f.id, sort_order=index),
                    ],
                ),
                commit=False,
            )
        except ValueError as exc:
            await db.rollback()
            raise http_exception_for_value_error(exc) from exc
        created_tasks.append(task.id)
    await db.commit()
    if sequential:
        await rebalance_project_fragment_video_queue(
            db,
            int(ep.project_id),
            sequential=True,
            user_id=int(user.id),
        )
    logger.info(
        "已创建分集视频任务 episode_id=%s project_id=%s fragments=%s activated=%s deferred=%s task_ids=%s",
        episode_id,
        ep.project_id,
        len(frag_ids),
        len(frag_ids) - deferred_count,
        deferred_count,
        created_tasks,
    )
    return {
        "ok": True,
        "fragment_ids": frag_ids,
        "status": "pending",
        "task_id": created_tasks[0] if created_tasks else None,
        "task_ids": created_tasks,
        "batch_key": batch_key,
        "provider_task_id": None,
        "user_active_jobs": inflight + (len(frag_ids) - deferred_count),
        "user_job_limit": limit,
        "deferred_count": deferred_count,
        "remaining_not_queued": 0,
    }


@router.get("/episodes/{episode_id}/generate_status")
async def generate_status(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ep = await get_owned_episode(db, episode_id, user)
    active_tasks = await list_active_tasks_for_owner(
        db,
        user.id,
        drama_project_id=ep.project_id,
    )
    episode_tasks = [task for task in active_tasks if task.episode_id == episode_id]
    await reconcile_applied_fragment_video_tasks(db, episode_tasks)
    # 补完成后刷新本集仍活跃任务，避免前端继续看到僵尸 awaiting_poll
    active_tasks = await list_active_tasks_for_owner(
        db,
        user.id,
        drama_project_id=ep.project_id,
    )
    episode_tasks = [task for task in active_tasks if task.episode_id == episode_id]
    await reconcile_orphaned_fragment_generations(
        db,
        list(ep.fragments or []),
        collect_active_fragment_ids_from_tasks(episode_tasks),
    )
    # 附带本集近期终态分镜视频任务，供队列点开详情（含失败原因）
    from app.models_tasks import TaskRun
    from app.services.tasks.service import TERMINAL_TASK_STATUSES, task_detail_options

    recent_terminal = list(
        (
            await db.execute(
                select(TaskRun)
                .options(*task_detail_options())
                .where(
                    TaskRun.requested_by == user.id,
                    TaskRun.domain == "drama",
                    TaskRun.task_type == "fragment_video",
                    TaskRun.episode_id == episode_id,
                    TaskRun.status.in_(tuple(TERMINAL_TASK_STATUSES)),
                )
                .order_by(TaskRun.id.desc())
                .limit(40)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    # 分镜 params 可能仍停在 queued，而任务已 awaiting_poll：用任务态校正对外状态
    task_status_by_frag: dict[int, str] = {}
    for task in episode_tasks:
        if getattr(task, "task_type", None) != "fragment_video":
            continue
        if getattr(task, "cancel_requested", False):
            continue
        fid = getattr(task, "fragment_id", None)
        if fid is None:
            continue
        task_status_by_frag[int(fid)] = str(getattr(task, "status", "") or "")

    items = []
    done = 0
    failed = 0
    running = 0
    for f in sorted(ep.fragments or [], key=lambda x: x.sort_order):
        st = overlay_fragment_status_with_active_task(
            fragment_generation_status(f),
            task_status_by_frag.get(int(f.id)),
        )
        items.append({"fragment_id": f.id, **st})
        s = st.get("status")
        if s == "done":
            done += 1
        elif s == "failed":
            failed += 1
        elif s in {"running", "queued", "generating"}:
            running += 1
    return {
        "episode_id": episode_id,
        "done": done,
        "failed": failed,
        "running": running,
        "total": len(items),
        "tasks": [
            item
            for item in _expand_episode_task_items([*episode_tasks, *recent_terminal])
        ],
        "fragments": items,
    }


@router.post("/episodes/{episode_id}/compose")
async def compose_episode(
    episode_id: int,
    body: DramaComposeEpisodeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """统一画幅重编码后拼接本集分镜，供浏览器无损失败时回退。"""
    from app.services.drama.episode_compose import compose_episode_video, load_episode_for_compose

    ep = await get_owned_episode(db, episode_id, user)
    project = await get_owned_drama_project(db, ep.project_id, user)
    episode = await load_episode_for_compose(db, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="分集不存在")
    req = body or DramaComposeEpisodeRequest()
    try:
        url = await compose_episode_video(
            db,
            episode=episode,
            project=project,
            fragment_ids=req.fragment_ids,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("episode compose failed episode_id=%s", episode_id)
        raise HTTPException(status_code=500, detail=f"全片合成失败：{exc}") from exc
    return {"ok": True, "video_url": url, "episode_id": episode_id}


@router.post("/episodes/{episode_id}/cancel_generate")
async def cancel_generate_episode(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """取消本集全部分镜视频生成（排队/进行中）。"""
    ep = await get_owned_episode(db, episode_id, user)
    await get_owned_drama_project(db, ep.project_id, user)
    await cancel_tasks_for_scope(
        db,
        user.id,
        domain="drama",
        task_type="fragment_video",
        drama_project_id=ep.project_id,
        episode_id=episode_id,
    )
    result = await cancel_episode_video_jobs(episode_id)
    logger.info(
        "已取消分集视频 episode_id=%s project_id=%s result=%s",
        episode_id,
        ep.project_id,
        result,
    )
    return result


@router.post("/cancel_video_jobs")
async def cancel_all_video_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """取消当前用户触发的全部漫剧分镜视频任务。"""
    await cancel_tasks_for_scope(db, user.id, domain="drama", task_type="fragment_video")
    result = await cancel_all_episode_video_jobs(user.id)
    logger.info("已取消全部视频任务 user_id=%s result=%s", user.id, result)
    return result
