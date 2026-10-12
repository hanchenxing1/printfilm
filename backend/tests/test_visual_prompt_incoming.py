"""资产生图：本次 prompt 不被旧 visualPrompt 覆盖。"""

from __future__ import annotations

import pytest

from app.models_drama import DramaAsset, DramaProject
from app.services.drama.visual_prompt import resolve_visual_prompt_for_asset


@pytest.mark.asyncio
async def test_incoming_prompt_beats_stored_visual_prompt():
    """任务里新写的角色描述必须用于生图，不能静默沿用库内旧 visualPrompt。"""
    project = DramaProject(id=1, user_id=1, title="t", params={})
    old = (
        "外貌：约十七八岁，脸型清瘦偏长，眉骨微微隆起，未展开的长眉，窄长眼眶微凸，"
        "皮肤透时显出青筋，只剩一边浑浊的右眼，下唇习惯性咬出的齿痕。头发半束半披散，"
        "发尾沾着泥点，额前碎发扫过眉骨，耳后露出晒伤的头皮。"
    )
    asset = DramaAsset(
        id=5266,
        project_id=1,
        type="character",
        name="新角色",
        params={"visualPrompt": old, "visualImage": old},
    )
    incoming = (
        "年轻气质美女数学老师站在讲台后，中景，镜头距主体2米，正面朝向学生，"
        "黑色长发，简约得体白色职业衬衫，面带温和微笑，教室空间，固定镜头，"
        "柔和侧逆光从左侧窗户打入，面部明亮，整体氛围专业亲切。"
    )
    resolved = await resolve_visual_prompt_for_asset(asset, project, incoming)
    assert "数学老师" in resolved
    assert "十七八岁" not in resolved
    assert resolved == incoming


@pytest.mark.asyncio
async def test_no_incoming_keeps_strong_stored_prompt():
    """未传新文案时，仍可复用库内已有完整 visualPrompt。"""
    project = DramaProject(id=1, user_id=1, title="t", params={})
    stored = (
        "外貌：约十七八岁，脸型清瘦偏长，眉骨微微隆起，未展开的长眉，窄长眼眶微凸，"
        "皮肤透时显出青筋，只剩一边浑浊的右眼，下唇习惯性咬出的齿痕。头发半束半披散，"
        "发尾沾着泥点，额前碎发扫过眉骨，耳后露出晒伤的头皮。身上洗得发白的旧棉袄，"
        "腰系磨毛绳，脚踏破口布鞋。"
    )
    asset = DramaAsset(
        id=1,
        project_id=1,
        type="character",
        name="新角色",
        params={"visualPrompt": stored},
    )
    resolved = await resolve_visual_prompt_for_asset(asset, project, None)
    assert resolved == stored
