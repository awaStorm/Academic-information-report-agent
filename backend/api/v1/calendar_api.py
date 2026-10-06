"""
backend/api/v1/calendar_api.py - 事件日历 API
- GET /api/v1/calendar?month=YYYY-MM
- 合并 CTF 赛事（ctf_cache.json）与情报推送记录（pushed_records），按日期分组
- CTF 跨天赛事展开为其覆盖的每一天（钳制在所选月内）
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.database import AgentMemory
from backend.api.v1.ctf import (
    load_cache,
    compute_status,
    _as_utc,
    _try_parse_event_time,
    _try_parse_date_text,
)

router = APIRouter()


def _month_bounds(month: str):
    """'YYYY-MM' -> (首日 datetime, 末日 datetime)"""
    year, mon = int(month[:4]), int(month[5:7])
    first = datetime(year, mon, 1)
    nxt = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)
    return first, nxt - timedelta(days=1)


def _resolve_event_times(event: dict):
    """解析 CTF 事件的起止时间（ISO 优先，纯文本兜底），统一 UTC"""
    start = _try_parse_event_time(event, "start_time")
    end = _try_parse_event_time(event, "end_time")
    if start is None:
        start = _try_parse_date_text(event.get("date", ""), as_end=False)
    if end is None:
        end = _try_parse_date_text(event.get("date", ""), as_end=True)
    return (
        _as_utc(start) if start else None,
        _as_utc(end) if end else None,
    )


@router.get("")
async def get_calendar(
    month: Optional[str] = Query(None, description="月份，格式 YYYY-MM，默认当月"),
):
    """获取指定月份的事件日历（CTF 赛事 + 情报推送）"""
    if not month or len(month) != 7 or month[4] != "-":
        month = datetime.now().strftime("%Y-%m")
    try:
        month_first, month_last = _month_bounds(month)
    except ValueError:
        month = datetime.now().strftime("%Y-%m")
        month_first, month_last = _month_bounds(month)

    days: dict = {}

    def _day(date_str: str) -> dict:
        if date_str not in days:
            days[date_str] = {"ctf": [], "intel": []}
        return days[date_str]

    # ---- CTF 赛事 ----
    cache = load_cache()
    ctf_total = 0
    for e in cache.get("events", []):
        # 读取时重算状态（缓存值只是抓取快照）；重算失败回退缓存值。
        # 只过滤 unknown（脏数据）；expired 为合法第四态，日历同样展示为"已结束"，
        # 与 get_events 的过滤口径保持一致。
        status = compute_status(e)
        if status == "unknown":
            status = e.get("status") or "unknown"
        if status == "unknown":
            continue
        start_dt, end_dt = _resolve_event_times(e)
        if not start_dt:
            continue
        end_date = (end_dt or start_dt).date()
        # 展开为覆盖的每一天（钳制在所选月内；跨天赛事最多展开 14 天防脏数据刷屏）
        span_end = min(end_date, start_dt.date() + timedelta(days=13))
        cur = start_dt.date()
        while cur <= span_end:
            if month_first.date() <= cur <= month_last.date():
                day = _day(cur.strftime("%Y-%m-%d"))
                day["ctf"].append({
                    "id": e.get("id", ""),
                    "name": e.get("name", ""),
                    "status": status,
                    "ctftime_url": e.get("ctftime_url", ""),
                    "official_url": e.get("official_url", ""),
                    "format": e.get("format", ""),
                    "location": e.get("location", ""),
                    "weight": e.get("weight", 0.0),
                    "start_time": start_dt.isoformat() if start_dt else None,
                    "end_time": end_dt.isoformat() if end_dt else None,
                })
                ctf_total += 1
            cur += timedelta(days=1)

    # ---- 情报推送记录（按事件发生日期 event_date 分组，非获取时间 push_time）----
    # event_date / timeline 节点都可能在 push_time 之后（如提前数月通知的竞赛，
    # 8 月推送、12 月决赛），查询窗口放宽：push_time 从当月首日往前 180 天到
    # 当月末日往后 30 天，再按事件日期/节点日期过滤到当月
    memory = AgentMemory()
    try:
        records = memory.get_pushed_records_by_date_range(
            (month_first - timedelta(days=180)).strftime("%Y-%m-%d"),
            (month_last + timedelta(days=30)).strftime("%Y-%m-%d"),
        )
    finally:
        memory.close()

    intel_total = 0
    month_start = month_first.date()
    month_end = month_last.date()

    def _intel_payload(r: dict, node=None) -> dict:
        """组装日历情报卡片；node 为 None 表示主事件打点，否则为 timeline 节点打点"""
        return {
            "title": r.get("title", ""),
            "platform": r.get("platform", ""),
            "category": r.get("category", ""),
            "brief": r.get("brief", ""),
            "link": r.get("link", ""),
            "links": r.get("links", []),
            "status": r.get("status", ""),
            "push_time": r.get("push_time", ""),
            "event_date": r.get("event_date"),
            "timeline": r.get("timeline", []),
            # 该卡片出现在当天的原因：主事件=None；timeline 节点打点={label,time}
            "timeline_node": node,
        }

    for r in records:
        placed_dates: set = set()  # 同一记录同一天只放一张卡片（主日期与节点去重）

        # 主事件日期打点
        event_date = r.get("event_date")
        if event_date and isinstance(event_date, str) and len(event_date) >= 10:
            date_str = event_date.strip().replace("/", "-")[:10]  # 斜杠日期归一（双保险）
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                d = None
            if d and month_start <= d <= month_end:
                _day(date_str)["intel"].append(_intel_payload(r))
                placed_dates.add(date_str)
                intel_total += 1

        # 第二阶段：timeline 每个节点（报名/初赛/决赛…）在其日期独立打点。
        # 注意：即使主 event_date 缺失或不在当月，只要节点本身带有效日期，
        # 仍按节点日期打点——节点日期明确即说明事件日期可识别，符合「可识别才打点」原则。
        for node in r.get("timeline") or []:
            if not isinstance(node, dict):
                continue
            nd_raw = node.get("date")
            if not nd_raw or not isinstance(nd_raw, str) or len(nd_raw) < 10:
                continue
            nd = nd_raw.strip().replace("/", "-")[:10]  # 斜杠日期归一（双保险）
            try:
                ndate = datetime.strptime(nd, "%Y-%m-%d").date()
            except ValueError:
                continue
            if not (month_start <= ndate <= month_end) or nd in placed_dates:
                continue
            _day(nd)["intel"].append(_intel_payload(r, node={
                "label": node.get("label", ""),
                "time": node.get("time", ""),
            }))
            placed_dates.add(nd)
            intel_total += 1  # 节点卡片计入总数（与主事件卡片口径一致）

    return {
        "success": True,
        "month": month,
        "days": days,
        "totals": {"ctf": ctf_total, "intel": intel_total},
    }
