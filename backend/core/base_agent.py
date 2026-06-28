"""
backend/core/base_agent.py - Agent 抽象基类
所有 Agent 必须继承此类，实现统一接口
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class BaseAgent(ABC):
    """Agent 抽象基类，定义所有 Agent 的统一接口"""

    @abstractmethod
    def get_name(self) -> str:
        """返回 Agent 唯一标识名称"""
        pass

    @abstractmethod
    def get_display_name(self) -> str:
        """返回 Agent 显示名称（用于前端展示）"""
        pass

    @abstractmethod
    def get_description(self) -> str:
        """返回 Agent 功能描述"""
        pass

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """返回该 Agent 可用的工具元数据列表（OpenAI Tool Calling 格式）"""
        pass

    @abstractmethod
    async def chat(
        self,
        user_input: str,
        session_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理用户对话请求
        返回格式: {"success": bool, "response": str, "history": list}
        """
        pass

    @abstractmethod
    async def run_task(
        self,
        task_name: str,
        session_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行指定任务（如采集、分析、推送等）
        日志通过 ws_manager 推送到前端
        """
        pass

    def get_capabilities(self) -> Dict[str, Any]:
        """返回 Agent 能力描述（可选重写）"""
        return {
            "name": self.get_name(),
            "display_name": self.get_display_name(),
            "description": self.get_description(),
            "tools": [t.get("function", {}).get("name") for t in self.get_tools()],
        }
