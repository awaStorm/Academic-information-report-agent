"""
backend/core/agent_registry.py - Agent 注册器
单例模式管理所有 Agent 的注册与获取
"""
from typing import Dict, Type, List, Any
import logging

logger = logging.getLogger("backend")


class AgentRegistry:
    """Agent 注册器（单例）"""

    _instance = None
    _lock = False  # 简单锁，避免重复初始化

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._agent_classes: Dict[str, Type["BaseAgent"]] = {}
        self._agent_instances: Dict[str, "BaseAgent"] = {}

    def register(self, agent_class: Type["BaseAgent"], name: str = None):
        """
        注册 Agent 类
        :param agent_class: Agent 类（继承 BaseAgent）
        :param name: 可选，Agent 名称（默认使用 get_name()）
        """
        # 实例化一次获取名称（如果未提供）
        if name is None:
            temp_instance = agent_class()
            name = temp_instance.get_name()
        self._agent_classes[name] = agent_class
        logger.info(f"✅ Agent 已注册: {name} ({agent_class.__name__})")

    def get_agent(self, name: str) -> "BaseAgent":
        """
        获取 Agent 实例（懒加载，单例）
        """
        if name not in self._agent_instances:
            if name not in self._agent_classes:
                raise ValueError(f"Agent '{name}' 未注册")
            self._agent_instances[name] = self._agent_classes[name]()
            logger.info(f"🤖 Agent 实例已创建: {name}")
        return self._agent_instances[name]

    def list_agents(self) -> List[Dict[str, str]]:
        """列出所有已注册的 Agent 基本信息"""
        result = []
        for name, agent_class in self._agent_classes.items():
            try:
                temp = agent_class()
                result.append({
                    "name": temp.get_name(),
                    "display_name": temp.get_display_name(),
                    "description": temp.get_description(),
                })
            except Exception as e:
                logger.warning(f"获取 Agent 信息失败 {name}: {e}")
        return result

    def get_all_capabilities(self) -> List[Dict[str, Any]]:
        """获取所有 Agent 的能力描述"""
        result = []
        for name in self._agent_classes:
            agent = self.get_agent(name)
            result.append(agent.get_capabilities())
        return result

    def remove_agent(self, name: str):
        """移除 Agent（主要用于测试）"""
        self._agent_classes.pop(name, None)
        self._agent_instances.pop(name, None)


# 全局注册器实例
registry = AgentRegistry()
