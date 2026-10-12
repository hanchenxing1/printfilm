"""保存分镜时对齐资产引用：只补缺、只删多余。"""

from unittest.mock import AsyncMock

import pytest

from app.models_drama import DramaEpisodeFragment, DramaFragmentAssetRef
from app.services.drama.access import replace_fragment_asset_refs


@pytest.mark.asyncio
async def test_replace_keeps_existing_refs_without_reinsert():
    db = AsyncMock()
    frag = DramaEpisodeFragment(episode_id=1)
    frag.id = 18275
    keep = DramaFragmentAssetRef(fragment_id=18275, asset_id=4657)
    drop = DramaFragmentAssetRef(fragment_id=18275, asset_id=1)
    frag.asset_references = [keep, drop]

    await replace_fragment_asset_refs(db, frag, [4657, 4665, 4657])

    db.execute.assert_not_awaited()
    assert [row.asset_id for row in frag.asset_references] == [4657, 4665]
    assert frag.asset_references[0] is keep


@pytest.mark.asyncio
async def test_replace_empty_collection_only_appends():
    db = AsyncMock()
    frag = DramaEpisodeFragment(episode_id=1)
    frag.id = 99
    frag.asset_references = []

    await replace_fragment_asset_refs(db, frag, [5, 5, 7, 0, -1])

    db.execute.assert_not_awaited()
    assert [row.asset_id for row in frag.asset_references] == [5, 7]
