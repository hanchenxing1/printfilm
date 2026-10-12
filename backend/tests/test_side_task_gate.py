"""单镜侧任务门禁：整片流水线才拦截，残留 IMAGING / 其它镜任务不拦。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.projects import _ensure_side_task_allowed


def _project(*tasks: SimpleNamespace, status: str = "SCRIPT_READY") -> SimpleNamespace:
    return SimpleNamespace(status=status, active_tasks=list(tasks))


def _task(task_type: str, status: str = "running", cancel_requested: bool = False) -> SimpleNamespace:
    return SimpleNamespace(task_type=task_type, status=status, cancel_requested=cancel_requested)


def test_side_task_allows_leftover_imaging_without_tasks():
    _ensure_side_task_allowed(_project(status="IMAGING"))


def test_side_task_allows_parallel_shot_regen():
    _ensure_side_task_allowed(_project(_task("shot_regen_image"), status="IMAGING"))


def test_side_task_blocks_project_pipeline():
    with pytest.raises(HTTPException) as exc:
        _ensure_side_task_allowed(_project(_task("project_pipeline"), status="SCRIPTING"))
    assert exc.value.status_code == 409


def test_side_task_blocks_shot_regen_audio():
    with pytest.raises(HTTPException) as exc:
        _ensure_side_task_allowed(_project(_task("shot_regen_audio"), status="AUDIOING"))
    assert exc.value.status_code == 409


def test_side_task_blocks_compose():
    with pytest.raises(HTTPException) as exc:
        _ensure_side_task_allowed(_project(_task("project_compose_only"), status="COMPOSING"))
    assert exc.value.status_code == 409


def test_side_task_blocks_cancel_requested_pipeline():
    with pytest.raises(HTTPException) as exc:
        _ensure_side_task_allowed(
            _project(_task("project_pipeline", status="cancel_requested", cancel_requested=True))
        )
    assert exc.value.status_code == 409


def test_side_task_allows_terminal_cancelled_pipeline():
    _ensure_side_task_allowed(_project(_task("project_pipeline", status="cancelled", cancel_requested=True)))
