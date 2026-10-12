"""Unit tests for project list runtime status projection."""

from types import SimpleNamespace

from app.api.projects import _project_runtime_view
from app.models import ProjectStatus


def _proj(**kwargs):
    return SimpleNamespace(
        status=kwargs.get("status", ProjectStatus.VIDEOING),
        progress=kwargs.get("progress", 81),
        error_msg=kwargs.get("error_msg"),
        active_tasks=kwargs.get("active_tasks", []),
    )


def _task(*, task_type="project_pipeline", status="running", phase="videos", progress=0):
    return SimpleNamespace(
        task_type=task_type,
        status=status,
        progress_percent=progress,
        error_message=None,
        payload={"phase": phase, "project_id": 404},
    )


def test_pipeline_videos_phase_shows_videoing_not_scripting():
    p = _proj(active_tasks=[_task(phase="videos")])
    status, progress, _err = _project_runtime_view(p)
    assert status == ProjectStatus.VIDEOING
    assert progress == 81


def test_pipeline_assets_phase_shows_imaging():
    p = _proj(status=ProjectStatus.IMAGING, progress=40, active_tasks=[_task(phase="assets")])
    status, _, _ = _project_runtime_view(p)
    assert status == ProjectStatus.IMAGING


def test_pipeline_script_phase_shows_scripting():
    p = _proj(status=ProjectStatus.SCRIPTING, progress=5, active_tasks=[_task(phase="script")])
    status, _, _ = _project_runtime_view(p)
    assert status == ProjectStatus.SCRIPTING


def test_no_active_task_keeps_project_status():
    p = _proj(status=ProjectStatus.VIDEOING, progress=81, active_tasks=[])
    status, progress, _ = _project_runtime_view(p)
    assert status == ProjectStatus.VIDEOING
    assert progress == 81
