"""计费/管理端集成测试：PostgreSQL + 开启 billing。

安全约定：集成测试永不直连业务库。db_session 自动把 DATABASE_URL 的库名
派生为 ``<库名>_test``（如 printfilm → printfilm_test），不存在则自动创建；
已指向含 "test" 的库时原样使用（CI 可直接注入测试库 URL）。
每个用例仍跑在外层事务回滚里，测试数据不落库。
"""
from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import Base
from app.models import User
from app.models_tasks import TaskRun

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _resolve_test_database_url(raw_url: str) -> tuple[str, str]:
    """业务库 URL → (测试库 URL, 测试库名)；库名非法时直接拒绝。"""
    parsed = make_url(raw_url)
    name = parsed.database or "postgres"
    if "test" in name:
        return raw_url, name
    test_name = f"{name}_test"
    if not _DB_NAME_RE.fullmatch(test_name):
        raise RuntimeError(f"拒绝在非法库名上创建测试库: {test_name!r}")
    return parsed.set(database=test_name).render_as_string(hide_password=False), test_name


async def _ensure_test_database(test_url: str, test_name: str) -> None:
    """连维护库 postgres 检查并创建测试库（AUTOCOMMIT，CREATE DATABASE 不能入事务）。"""
    maint_url = make_url(test_url).set(database="postgres").render_as_string(hide_password=False)
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": test_name},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{test_name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def skip_tokenfree_pricing_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """单测不打 TokenFree 公开价目，避免预估被外网拖慢或改数。"""

    async def _empty(_settings=None):
        """返回空价目，预估走本地回退。"""
        return {}

    monkeypatch.setattr("app.services.tokenfree_pricing.ensure_official_rates", _empty)
    monkeypatch.setattr("app.services.billing.estimates.ensure_official_rates", _empty)
    from app.services.tokenfree_pricing import set_cached_rates

    set_cached_rates(None)


@pytest.fixture
def billing_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试环境强制开启计费，buffer=1 便于断言。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.0)


@pytest_asyncio.fixture
async def db_session(billing_enabled: None) -> AsyncIterator[AsyncSession]:
    """每个用例外层事务回滚；session.commit 只提交 savepoint，不落库。"""
    # 注册全部 ORM 表
    import app.models  # noqa: F401
    import app.models_agent  # noqa: F401
    import app.models_api  # noqa: F401
    import app.models_drama  # noqa: F401
    import app.models_settings  # noqa: F401
    import app.models_tasks  # noqa: F401

    url = (get_settings().database_url or "").strip()
    if not url.startswith("postgresql"):
        raise RuntimeError("集成测试需要 PostgreSQL DATABASE_URL（postgresql+asyncpg://...）")

    # 强制隔离到独立测试库，杜绝污染/损坏开发库真实数据
    test_url, test_name = _resolve_test_database_url(url)
    await _ensure_test_database(test_url, test_name)

    engine = create_async_engine(test_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 增量列直接复用 main._apply_schema_patches（权威清单，避免测试补丁与线上漂移）；
    # 该函数闭包 app.main.engine，临时指向测试 engine 后再还原。
    import app.main as main_module

    original_engine = main_module.engine
    main_module.engine = engine
    try:
        await main_module._apply_schema_patches()
    finally:
        main_module.engine = original_engine

    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()

    await engine.dispose()


async def make_user(
    db: AsyncSession,
    *,
    balance_fen: int = 100_000,
    frozen_fen: int = 0,
) -> User:
    """创建测试用户。"""
    user = User(
        email=f"billing-{uuid.uuid4().hex[:10]}@test.local",
        hashed_password="test",
        balance_fen=balance_fen,
        frozen_fen=frozen_fen,
    )
    db.add(user)
    await db.flush()
    return user


async def make_task(
    db: AsyncSession,
    user: User,
    *,
    domain: str = "api",
    task_type: str = "v1_image",
    status: str = "pending",
    billing_status: str = "none",
    provider_task_id: str | None = None,
) -> TaskRun:
    """创建测试 TaskRun（无业务 FK）。"""
    task = TaskRun(
        domain=domain,
        task_type=task_type,
        status=status,
        requested_by=user.id,
        provider_task_id=provider_task_id,
        billing_status=billing_status,
        payload={},
    )
    db.add(task)
    await db.flush()
    return task
