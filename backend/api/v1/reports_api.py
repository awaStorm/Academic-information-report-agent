"""
backend/api/v1/reports.py - 报告管理 API
"""
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter()

REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")


@router.get("/")
async def list_reports():
    """列出所有报告文件"""
    if not os.path.exists(REPORTS_DIR):
        return {"success": True, "data": []}
    files = [f for f in os.listdir(REPORTS_DIR) if f.endswith(".md")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(REPORTS_DIR, f)), reverse=True)
    return {"success": True, "data": files}


@router.get("/{filename}")
async def get_report(filename: str):
    """获取报告内容"""
    file_path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "data": {"filename": filename, "content": content}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
