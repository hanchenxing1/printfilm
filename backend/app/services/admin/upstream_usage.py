"""管理端：官方上游用量快照与本地成本对照（TokenFree / New API）。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import UpstreamUsageDaily, UsageEvent
from app.services.tokenfree_usage import (
    day_start_used_quota_from_raw_json,
    fetch_tokenfree_account,
    fetch_tokenfree_daily_usage,
    quota_to_cost_fen,
    tokenfree_usage_configured,
    used_quota_from_raw_json,
)


def _utc_today() -> date:
    """UTC 当天日期，与快照 usage_date 对齐。"""
    return datetime.now(UTC).date()


async def _local_usage_daily(
    db: AsyncSession,
    *,
    since: date,
    until: date,
) -> dict[str, dict[str, int]]:
    """按日聚合全部本地 usage_events（TokenFree 覆盖全部模型）。"""
    day_expr = cast(UsageEvent.created_at, Date)
    rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .where(
                day_expr >= since,
                day_expr <= until,
            )
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        key = str(row.day)[:10]
        out[key] = {
            "local_cost_fen": int(row.cost_fen or 0),
            "local_tokens": int(row.tokens or 0),
        }
    return out


async def _latest_used_quota_before(
    db: AsyncSession,
    *,
    before: date,
) -> int | None:
    """取 before 日之前最近一条快照里的累计 used_quota。"""
    row = (
        await db.execute(
            select(UpstreamUsageDaily)
            .where(UpstreamUsageDaily.usage_date < before)
            .order_by(UpstreamUsageDaily.usage_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return used_quota_from_raw_json(row.raw_json)


async def _today_from_cumulative(
    db: AsyncSession,
    *,
    today: date,
    used_quota: int,
    settings: Any,
) -> dict[str, Any]:
    """当 New API 不按日返回用量时，用累计 used_quota 差分记到今天。"""
    existing = (
        await db.execute(select(UpstreamUsageDaily).where(UpstreamUsageDaily.usage_date == today))
    ).scalar_one_or_none()
    baseline = day_start_used_quota_from_raw_json(existing.raw_json if existing else None)
    if baseline is None:
        baseline = await _latest_used_quota_before(db, before=today)
    if baseline is None:
        return {
            "quota": 0,
            "tokens": 0,
            "cost_fen": 0,
            "used_quota": used_quota,
            "day_start_used_quota": used_quota,
            "source": "baseline",
        }
    delta = max(0, int(used_quota) - int(baseline))
    return {
        "quota": delta,
        "tokens": 0,
        "cost_fen": quota_to_cost_fen(delta, settings),
        "used_quota": used_quota,
        "day_start_used_quota": baseline,
        "source": "cumulative_delta",
    }


async def sync_upstream_usage(
    db: AsyncSession,
    *,
    days: int = 30,
    force: bool = False,
) -> dict[str, Any]:
    """拉取 TokenFree 官方日用量并写入 upstream_usage_daily。"""
    if not tokenfree_usage_configured():
        return {"configured": False, "synced": 0, "skipped": 0}

    s = get_settings()
    today = _utc_today()
    start = today - timedelta(days=max(1, int(days)) - 1)
    local_map = await _local_usage_daily(db, since=start, until=today)

    official_daily = await fetch_tokenfree_daily_usage(start, today, settings=s)
    account: dict[str, Any] | None = None
    try:
        account = await fetch_tokenfree_account(settings=s)
    except RuntimeError:
        if not official_daily:
            raise
    if not official_daily and account and account.get("used_quota") is not None:
        official_daily = {
            today.isoformat(): await _today_from_cumulative(
                db,
                today=today,
                used_quota=int(account["used_quota"]),
                settings=s,
            )
        }

    synced = 0
    skipped = 0
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    cur = start
    while cur <= today:
        day_key = cur.isoformat()
        existing = (
            await db.execute(select(UpstreamUsageDaily).where(UpstreamUsageDaily.usage_date == cur))
        ).scalar_one_or_none()
        hit = official_daily.get(day_key)
        if (
            existing
            and not force
            and hit is None
            and existing.fetched_at
            and existing.fetched_at.replace(tzinfo=UTC) >= one_hour_ago
        ):
            skipped += 1
            cur += timedelta(days=1)
            continue
        if (
            existing
            and not force
            and hit is None
            and cur < today
        ):
            skipped += 1
            cur += timedelta(days=1)
            continue

        local_hit = local_map.get(day_key) or {"local_cost_fen": 0, "local_tokens": 0}
        row = existing or UpstreamUsageDaily(usage_date=cur)
        if hit is not None:
            row.official_tokens = int(hit.get("tokens") or 0)
            row.official_cost_fen = int(hit.get("cost_fen") or 0)
        elif existing is None:
            row.official_tokens = 0
            row.official_cost_fen = 0
        row.local_cost_fen = int(local_hit["local_cost_fen"])
        row.local_tokens = int(local_hit["local_tokens"])
        raw: dict[str, Any] = {"day": day_key, "source": "tokenfree"}
        if hit:
            raw.update({k: v for k, v in hit.items() if k != "tokens"})
        if account and cur == today:
            raw["used_quota"] = account.get("used_quota")
            raw["remain_quota"] = account.get("quota")
        row.raw_json = json.dumps(raw, ensure_ascii=False)[:4000]
        row.fetched_at = now
        if existing is None:
            db.add(row)
        synced += 1
        cur += timedelta(days=1)

    await db.commit()
    return {"configured": True, "synced": synced, "skipped": skipped, "last_sync_at": now.isoformat()}


async def build_upstream_usage_compare(
    db: AsyncSession,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """返回近 N 日官方/本地成本对照序列。"""
    today = _utc_today()
    start = today - timedelta(days=max(1, int(days)) - 1)
    rows = (
        await db.execute(
            select(UpstreamUsageDaily)
            .where(UpstreamUsageDaily.usage_date >= start)
            .order_by(UpstreamUsageDaily.usage_date.asc())
        )
    ).scalars().all()
    row_map = {r.usage_date.isoformat(): r for r in rows}
    local_map = await _local_usage_daily(db, since=start, until=today)

    series: list[dict[str, Any]] = []
    cur = start
    last_sync_at: str | None = None
    while cur <= today:
        key = cur.isoformat()
        snap = row_map.get(key)
        local_hit = local_map.get(key) or {"local_cost_fen": 0, "local_tokens": 0}
        official_tokens = int(snap.official_tokens if snap else 0)
        official_cost = int(snap.official_cost_fen if snap else 0)
        local_cost = int(snap.local_cost_fen if snap else local_hit["local_cost_fen"])
        local_tokens = int(snap.local_tokens if snap else local_hit["local_tokens"])
        delta_fen = local_cost - official_cost
        delta_pct: float | None = None
        if official_cost > 0:
            delta_pct = round(delta_fen / official_cost * 100.0, 2)
        elif local_cost > 0:
            delta_pct = None
        series.append(
            {
                "date": key,
                "local_cost_fen": local_cost,
                "local_tokens": local_tokens,
                "official_tokens": official_tokens,
                "official_cost_fen": official_cost,
                "delta_fen": delta_fen,
                "delta_pct": delta_pct,
            }
        )
        if snap and snap.fetched_at:
            last_sync_at = snap.fetched_at.isoformat()
        cur += timedelta(days=1)

    return {
        "configured": tokenfree_usage_configured(),
        "days": int(days),
        "last_sync_at": last_sync_at,
        "series": series,
    }
