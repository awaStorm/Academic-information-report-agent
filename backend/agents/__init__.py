"""
backend/agents/__init__.py - Agent 自动注册
导入所有 Agent 类并注册到 registry
"""
from backend.core.agent_registry import registry
from backend.agents.xidian_agent import XidianAgent

# 注册 XidianAgent
registry.register(XidianAgent)

# 未来新增 Agent 只需在此处添加：
# from backend.agents.another_agent import AnotherAgent
# registry.register(AnotherAgent)
