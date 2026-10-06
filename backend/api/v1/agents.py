"""
backend/api/v1/agents.py - Agent 管理 API
"""
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Any
import logging

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.agent_registry import registry
from backend.ws.connection_manager import manager
from src.utils.llm_client import describe_llm_error, is_connection_error

logger = logging.getLogger("backend.api.agents")
router = APIRouter()


@router.get("/")
async def list_agents():
    """列出所有已注册的 Agent"""
    return {"success": True, "data": registry.list_agents()}


@router.get("/{agent_name}/capabilities")
async def get_agent_capabilities(agent_name: str):
    """获取指定 Agent 的能力描述"""
    try:
        agent = registry.get_agent(agent_name)
        return {"success": True, "data": agent.get_capabilities()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_name}/chat")
async def agent_chat(
    agent_name: str,
    user_input: str,
    session_id: str = Query(default="default"),
):
    """与指定 Agent 对话（异步，通过 WebSocket 推送日志）"""
    try:
        agent = registry.get_agent(agent_name)
        result = await agent.chat(user_input, session_id)
        # result 自身已包含 success 字段，直接返回避免双层嵌套
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # 网络层连不上（网络中断 / 代理节点抖动 / LLM 服务端临时不可用）属于
        # 「重试即可恢复」的可恢复状态，不该以 500 把前端吓成硬故障。
        # 返回结构化结果，前端 AgentChatPage 会按 success=false 展示 message。
        if is_connection_error(e):
            logger.error(f"Agent 对话失败（LLM 连接异常）: {e}")
            return {"success": False, "error_type": "LLM_UNREACHABLE",
                    "message": describe_llm_error(e)}
        logger.error(f"Agent 对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agent_name}/task/{task_name}")
async def run_agent_task(
    agent_name: str,
    task_name: str,
    session_id: str = Query(default="default"),
):
    """执行 Agent 指定任务"""
    try:
        agent = registry.get_agent(agent_name)
        result = await agent.run_task(task_name, session_id)
        # 直接透传：agent.run_task 已如实包含 success 字段，
        # 不得再包一层 {"success": True, ...} 把失败伪装成成功
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # 与 agent_chat 同口径：网络层断连属可恢复状态，返回结构化结果而非 500。
        # （正常情况下 XidianAgent.run_task 已在内部兜底，这里是接口层的双保险，
        #  避免将来新增 Agent 时又把这个缺口漏出来。）
        if is_connection_error(e):
            logger.error(f"任务执行失败（LLM 连接异常）: {e}")
            return {"success": False, "error_type": "LLM_UNREACHABLE",
                    "message": describe_llm_error(e)}
        logger.error(f"任务执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
