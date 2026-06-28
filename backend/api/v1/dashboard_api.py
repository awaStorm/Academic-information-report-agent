"""
backend/api/v1/dashboard.py - 仪表盘 API
"""
import sys
from pathlib import Path
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.database import AgentMemory

router = APIRouter()


@router.get("/records")
async def get_records(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    platform: str = Query(default="all"),
):
    """获取推送记录"""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    platform_map = {"all": None, "chaoxing": "chaoxing", "wechat": "wechat"}
    pf = platform_map.get(platform, None)

    memory = AgentMemory()
    try:
        records = memory.get_pushed_records_by_date_range(start_date, end_date, pf)
        return {"success": True, "data": records, "total": len(records)}
    finally:
        memory.close()


@router.get("/stats")
async def get_stats():
    """获取仪表盘统计数据"""
    memory = AgentMemory()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        today_records = memory.get_pushed_records_by_date_range(today, today, None)
        week_records = memory.get_pushed_records_by_date_range(week_ago, today, None)

        wechat_count = len([r for r in week_records if r["platform"] == "wechat"])
        chaoxing_count = len([r for r in week_records if r["platform"] == "chaoxing"])

        return {
            "success": True,
            "data": {
                "today": len(today_records),
                "week": len(week_records),
                "wechat": wechat_count,
                "chaoxing": chaoxing_count,
            }
        }
    finally:
        memory.close()
