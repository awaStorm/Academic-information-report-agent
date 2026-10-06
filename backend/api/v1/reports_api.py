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
    # 安全：拒绝路径遍历。Windows 下 URL 编码的 %5C（反斜杠）可穿过路由通配，
    # 若直接 os.path.join(REPORTS_DIR, filename)，攻击者可读取 .env / configs 凭证等任意文件
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename or safe_name.startswith("."):
        raise HTTPException(status_code=404, detail="报告不存在")
    if not safe_name.endswith(".md"):
        raise HTTPException(status_code=404, detail="报告不存在")

    file_path = os.path.join(REPORTS_DIR, safe_name)
    # 双保险：解析真实路径后确认仍位于报告目录内
    real_dir = os.path.normcase(os.path.realpath(REPORTS_DIR))
    real_file = os.path.normcase(os.path.realpath(file_path))
    if os.path.dirname(real_file) != real_dir:
        raise HTTPException(status_code=404, detail="报告不存在")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "data": {"filename": safe_name, "content": content}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
