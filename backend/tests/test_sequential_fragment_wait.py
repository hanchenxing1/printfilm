"""开启尾帧衔接后，连续点各镜生成必须按镜序等待，不能各自当首镜开跑。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tasks.service import (
    _sequential_fragment_video_project_id,
    pick_sequential_episode_head,
    reconcile_sequential_batches,
    sequential_fragment_video_needs_episode_rebalance,
    sequential_task_blocked_by_previous_fragment,
)


def _task(**kwargs):
    """构造分镜视频任务替身。"""
    payload = kwargs.pop("payload", {"sequential": True, "batch_index": 0})
    defaults = {
        "id": 1,
        "task_type": "fragment_video",
        "status": "pending",
        "next_action_at": None,
        "requested_by": 9,
        "drama_project_id": 100,
        "fragment_id": 1,
        "episode_id": 7,
        "payload": payload,
        "current_step_key": "submit",
        "cancel_requested": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _rows(items):
    """模拟 SQLAlchemy scalars().all()。"""

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return list(items)

    return _Result()


def test_sequential_fragment_video_needs_episode_rebalance():
    assert sequential_fragment_video_needs_episode_rebalance(
        "fragment_video", {"sequential": True}
    )
    assert not sequential_fragment_video_needs_episode_rebalance(
        "fragment_video", {"sequential": False}
    )
    assert not sequential_fragment_video_needs_episode_rebalance(
        "asset_image", {"sequential": True}
    )


def test_pick_head_keeps_running_first_shot():
    shot1 = _task(id=11, fragment_id=1, status="awaiting_poll")
    shot2 = _task(id=12, fragment_id=2, status="pending")
    head = pick_sequential_episode_head(
        [shot2, shot1],
        {1: 0, 2: 1},
    )
    assert head is shot1


def test_pick_head_activates_next_after_previous_leaves_queue():
    shot2 = _task(id=12, fragment_id=2, status="pending")
    shot3 = _task(id=13, fragment_id=3, status="pending")
    head = pick_sequential_episode_head(
        [shot3, shot2],
        {2: 1, 3: 2},
    )
    assert head is shot2


def test_project_id_falls_back_to_payload():
    task = _task(drama_project_id=None, payload={"sequential": True, "project_id": "355"})
    assert _sequential_fragment_video_project_id(task, task.payload) == 355
    assert _sequential_fragment_video_project_id(
        _task(drama_project_id=None, payload={"sequential": True}),
        {"sequential": True},
    ) is None


def _frag(fid: int, sort_order: int, *, video: str = "", last_frame: str = ""):
    """构造分镜替身。"""
    params: dict = {}
    if last_frame:
        params["lastFrameUrl"] = last_frame
    return SimpleNamespace(id=fid, sort_order=sort_order, video=video, params=params)


def test_later_shot_waits_when_previous_failed_without_last_frame():
    shot2 = _task(id=12, fragment_id=2, status="pending")
    prev = _frag(1, 0)
    current = _frag(2, 1)
    assert sequential_task_blocked_by_previous_fragment(shot2, [current, prev])


def test_later_shot_unblocked_when_previous_has_last_frame():
    shot2 = _task(id=12, fragment_id=2, status="pending")
    prev = _frag(1, 0, last_frame="https://example.com/last.png")
    current = _frag(2, 1)
    assert not sequential_task_blocked_by_previous_fragment(shot2, [current, prev])


@pytest.mark.asyncio
async def test_reconcile_does_not_activate_each_click_as_batch_head():
    """连续点击会各建 batch_index=0；调和不得把后镜当独立首镜点亮。"""
    shot1 = _task(id=11, fragment_id=1)
    shot2 = _task(id=12, fragment_id=2)
    db = SimpleNamespace(commit=AsyncMock())
    db.execute = AsyncMock(
        side_effect=[
            _rows(["batch-click-1", "batch-click-2"]),
            _rows([shot1]),
            _rows([shot2]),
        ]
    )
    rebalance = AsyncMock(return_value={"pending": 2, "activated": 0, "deferred": 1})
    activate_next = AsyncMock()
    append_event = AsyncMock()

    with (
        patch(
            "app.services.tasks.service.rebalance_project_fragment_video_queue",
            new=rebalance,
        ),
        patch(
            "app.services.tasks.service.activate_next_sequential_task",
            new=activate_next,
        ),
        patch("app.services.tasks.service.append_task_event", new=append_event),
        patch(
            "app.config.get_settings",
            return_value=SimpleNamespace(drama_user_video_job_limit=12),
        ),
    ):
        await reconcile_sequential_batches(db)

    assert shot1.next_action_at is None
    assert shot2.next_action_at is None
    append_event.assert_not_awaited()
    activate_next.assert_not_awaited()
    rebalance.assert_awaited_once()
    assert rebalance.await_args.args[1] == 100
    assert rebalance.await_args.kwargs["sequential"] is True


@pytest.mark.asyncio
async def test_reconcile_uses_payload_project_id_when_column_missing():
    """drama_project_id 为空时仍按 payload.project_id 收口重排。"""
    shot = _task(
        id=31,
        fragment_id=2,
        drama_project_id=None,
        payload={"sequential": True, "batch_index": 0, "project_id": 355},
    )
    db = SimpleNamespace(commit=AsyncMock())
    db.execute = AsyncMock(side_effect=[_rows(["batch-no-col"]), _rows([shot])])
    rebalance = AsyncMock(return_value={"pending": 1, "activated": 0, "deferred": 1})

    with (
        patch(
            "app.services.tasks.service.rebalance_project_fragment_video_queue",
            new=rebalance,
        ),
        patch("app.services.tasks.service.append_task_event", new=AsyncMock()),
        patch(
            "app.config.get_settings",
            return_value=SimpleNamespace(drama_user_video_job_limit=12),
        ),
    ):
        await reconcile_sequential_batches(db)

    assert shot.next_action_at is None
    rebalance.assert_awaited_once()
    assert rebalance.await_args.args[1] == 355


@pytest.mark.asyncio
async def test_reconcile_still_activates_non_fragment_sequential_head():
    """非分镜视频的串行 batch 仍按 batch_index=0 补激活。"""
    other = _task(id=21, task_type="other_job", fragment_id=None)
    db = SimpleNamespace(commit=AsyncMock())
    db.execute = AsyncMock(side_effect=[_rows(["batch-other"]), _rows([other])])
    rebalance = AsyncMock(return_value={"pending": 0, "activated": 0, "deferred": 0})
    append_event = AsyncMock()

    with (
        patch(
            "app.services.tasks.service.rebalance_project_fragment_video_queue",
            new=rebalance,
        ),
        patch("app.services.tasks.service.append_task_event", new=append_event),
        patch(
            "app.services.drama.access.count_user_inflight_fragment_video_tasks",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.config.get_settings",
            return_value=SimpleNamespace(drama_user_video_job_limit=12),
        ),
    ):
        await reconcile_sequential_batches(db)

    assert other.next_action_at is not None
    append_event.assert_awaited()
    rebalance.assert_not_awaited()
