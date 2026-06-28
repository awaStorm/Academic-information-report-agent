"""
backend/api/v1/preferences.py - 偏好设置 API
"""
import sys
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.database import get_preferences as db_get_preferences
from src.agent.database import update_preferences as db_update_preferences

router = APIRouter()


class PreferencesUpdate(BaseModel):
    categories: List[str]


@router.get("/")
async def get_prefs():
    """获取用户偏好设置"""
    result = db_get_preferences()
    return {"success": True, "data": result}


@router.post("/")
async def update_prefs(body: PreferencesUpdate):
    """更新用户偏好设置"""
    result = db_update_preferences(body.categories)
    return {"success": True, "data": result}
