"""
backend/main.py - FastAPI 后端入口
替代原 app.py 中的 Gradio 服务，提供 RESTful API + WebSocket
"""
import sys
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# 将项目根目录加入 sys.path，使 backend 能导入 src/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.api.v1 import agents, config_api as config_router, dashboard_api as dashboard, reports_api as reports, preferences_api as preferences
from backend.ws.connection_manager import manager as ws_manager
from backend.core.agent_registry import registry
from backend.services.scheduler_service import SchedulerService

# 导入 agents 模块，触发 Agent 自动注册
import backend.agents  # noqa: F401

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backend")

# 全局调度器服务
scheduler_service = SchedulerService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 西电校园情报助手后端启动中...")
    # 启动时：初始化调度器
    scheduler_service.start()
    yield
    # 关闭时：停止调度器
    logger.info("🛑 正在关闭后端服务...")
    scheduler_service.stop()


app = FastAPI(
    title="西电校园情报助手 API",
    description="校园情报采集、分析与推送系统后端",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置（开发环境允许所有来源，生产环境需限制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境改为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agent 管理"])
app.include_router(config_router.router, prefix="/api/v1/config", tags=["配置管理"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["仪表盘"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["报告管理"])
app.include_router(preferences.router, prefix="/api/v1/preferences", tags=["偏好设置"])


# WebSocket 路由：实时日志流
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket, session_id: str = "default"):
    """WebSocket 端点：推送 Agent 执行日志"""
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            # 接收前端消息（如中断请求）
            data = await websocket.receive_json()
            if data.get("type") == "interrupt":
                logger.info(f"收到中断请求: {session_id}")
                ws_manager.mark_interrupt(session_id)
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        logger.info(f"WebSocket 断开: {session_id}")


@app.get("/")
async def root():
    return {
        "name": "西电校园情报助手",
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = 8138
    logger.info(f"访问地址: http://localhost:{port}")
    logger.info(f"API 文档: http://localhost:{port}/docs")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
