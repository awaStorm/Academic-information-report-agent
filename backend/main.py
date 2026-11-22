"""
backend/main.py - FastAPI 后端入口
替代原 app.py 中的 Gradio 服务，提供 RESTful API + WebSocket
"""
import sys
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# 后台 uvicorn 未走 start.bat 的 chcp 65001，控制台默认 GBK：
# 采集器/分析器里大量 emoji + 中文 print 会在 Agent 线程池调用时抛
# "'gbk' codec can't encode character"，导致采集工具整体失败。
# 在入口处一次性把 stdout/stderr 重配为 UTF-8，覆盖所有模块的 print。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 将项目根目录加入 sys.path，使 backend 能导入 src/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.api.v1 import agents, config_api as config_router, dashboard_api as dashboard, reports_api as reports, preferences_api as preferences, ctf as ctf_router, calendar_api as calendar, source_cards_api as source_cards
from backend.ws.connection_manager import manager as ws_manager
from backend.core.agent_registry import registry
from backend.services.scheduler_service import SchedulerService
from src.utils.config_loader import get_display_name

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
    logger.info(f"🚀 {get_display_name()}后端启动中...")
    # 启动自检：微信读书扫码环境（持久化档案 vs Playwright 自带 Chromium）版本一致性。
    # 只读、不启动浏览器、不修改任何文件；错配时提前告警，避免等到用户要扫码时才失败，
    # 又因 Playwright 只报 "Target page, context or browser has been closed" 而误判成
    # 「档案被锁」或显卡问题（2026-10-05 就是这么误判的）。
    try:
        from src.collectors.sessions.weread_harvester import WereadHarvester
        env = WereadHarvester.diagnose_browser_env()
        if env.get("status") in ("auto_align", "needs_rebuild"):
            logger.warning("⚠️ 微信读书扫码环境自检: %s", env.get("message"))
        else:
            logger.info("✅ 微信读书扫码环境自检: %s", env.get("message"))
    except Exception as e:  # 自检绝不能影响后端启动
        logger.warning("微信读书扫码环境自检跳过（%s）", e)
    # 启动时：确保超星/微信两张系统内置信源卡片存在并排在检查清单最前
    try:
        from src.utils.source_store import ensure_system_cards, migrate_targets_to_cards
        n = ensure_system_cards()
        if n:
            logger.info(f"✅ 已初始化 {n} 张系统内置信源卡片（超星/微信）")
        m = migrate_targets_to_cards()
        if m:
            logger.info(f"✅ 已将 {m} 个历史微信公众号目标迁移为信源卡片")
    except Exception as e:
        logger.warning(f"信源卡片初始化/迁移失败（不影响原有采集）: {e}")
    # 启动时：初始化调度器
    scheduler_service.start()
    yield
    # 关闭时：停止调度器
    logger.info("🛑 正在关闭后端服务...")
    scheduler_service.stop()


app = FastAPI(
    title=f"{get_display_name()} API",
    description="校园情报采集、分析与推送系统后端",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置：默认仅允许本机前端来源；部署时通过 .env 的 ALLOWED_ORIGINS 覆盖（逗号分隔）
_allowed_origins = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:7860,http://127.0.0.1:7860",
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
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
app.include_router(ctf_router.router, prefix="/api/v1/ctf", tags=["CTF时间表"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["事件日历"])
app.include_router(source_cards.router, prefix="/api/v1/source-cards", tags=["信源卡片"])


# WebSocket 路由：实时日志流
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket, session_id: str = "default"):
    """WebSocket 端点：推送 Agent 执行日志"""
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            # 接收前端消息（中断 / 心跳 / 清历史）
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "interrupt":
                logger.info(f"收到中断请求: {session_id}")
                ws_manager.mark_interrupt(session_id)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": data.get("ts")})
            elif msg_type == "clear_history":
                ws_manager.clear_history(session_id)
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {session_id}")
    finally:
        # finally 保证任何异常路径（含 receive_json 解析失败）都清理连接记录，避免泄漏
        ws_manager.disconnect(session_id, websocket)


@app.get("/")
async def root():
    return {
        "name": get_display_name(),
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
