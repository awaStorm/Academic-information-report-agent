"""
backend/agents/xidian_agent.py - XidianAgent 适配层
继承 BaseAgent，适配原有 XidianAgent 逻辑，支持 WebSocket 日志推送
"""
import sys
import json
import os
from pathlib import Path
from typing import Dict, List, Any
import logging
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from backend.core.base_agent import BaseAgent
from backend.ws.connection_manager import manager
from tools_config import TOOLS_METADATA, execute_tool
from src.utils.config_loader import CONFIG

logger = logging.getLogger("backend.xidian_agent")


class XidianAgent(BaseAgent):
    """西电校园情报 Agent（适配 BaseAgent 接口）"""

    def __init__(self):
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if not api_key:
            raise ValueError("LLM_API_KEY 未设置")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = CONFIG.get("analysis", {}).get("model_name", "")
        self.temperature = CONFIG.get("analysis", {}).get("temperature", 0.1)
        self.max_tokens = CONFIG.get("analysis", {}).get("max_tokens", 20000)
        self.history: List[Dict] = []
        self._init_system_prompt()
        logger.info(f"✅ XidianAgent 初始化完成，模型: {self.model}")

    def _init_system_prompt(self):
        self.system_prompt = {
            "role": "system",
            "content": (
                "你是西安电子科技大学的【校园情报 Agent】。\n"
                "你有权访问超星通知、微信公众号数据、本地数据库以及推送工具。\n\n"
                "## 执行准则\n"
                "1. 链路逻辑：采集 -> 处理 -> 解析 -> 合流 -> 分析 -> 推送。\n"
                "2. 交互性：在执行耗时工具前，先口头告知用户你的计划。\n"
                "3. 异常处理：若凭证失效（AUTH_EXPIRED），立即调用对应的扫码登录工具。\n"
                "4. 去重机制：analyze_and_push_intelligence 工具内部已完成代码级去重（基于 raw_hash 和标题精确匹配），你不需要担心重复推送问题。\n"
                "5. 时间敏感性：当前系统时间已注入每条用户消息，如果数据采集结果与昨天一致，可能是没有新情报，不要误判为'需要补充抓取'。\n"
                "6. 空数据保护：如果没有新情报，直接返回'无新情报'，不要无中生有或推送空消息。\n"
            )
        }
        self.history.append(self.system_prompt)

    def _trim_history(self, max_rounds: int = 3):
        """
        裁剪历史记录，只保留 system_prompt + 最近 max_rounds 轮对话
        防止上下文滚雪球导致 Token 稀释和 Agent 失焦
        """
        if len(self.history) <= 1:
            return

        # 第一条是 system_prompt，必须保留
        system_prompt = self.history[0:1]

        # 保留最近 max_rounds 轮（每轮包括 user + assistant）
        recent_rounds = self.history[-(max_rounds * 2):]

        self.history = system_prompt + recent_rounds
        logger.info(f"🧹 上下文清理：{len(self.history)} 条消息（保留 system_prompt + 最近 {max_rounds} 轮）")

    def get_name(self) -> str:
        return "xidian"

    def get_display_name(self) -> str:
        return "西电校园情报助手"

    def get_description(self) -> str:
        return "负责校园情报采集、分析与推送，支持超星通知和微信公众号"

    def get_tools(self) -> List[Dict[str, Any]]:
        return TOOLS_METADATA

    async def chat(self, user_input: str, session_id: str = "default") -> Dict[str, Any]:
        """处理对话（支持多轮工具调用 Agentic Loop）"""
        await self._send_log(session_id, "user", f"👤 {user_input}")

        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timed_input = f"【当前系统时间：{current_time_str}】\n用户指令：{user_input}"
        self.history.append({"role": "user", "content": timed_input})

        # Token 累计统计
        total_tokens = {"prompt": 0, "completion": 0, "total": 0}

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                tools=TOOLS_METADATA,
                tool_choice="auto",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # 累计 Token 用量
            if hasattr(response, "usage") and response.usage:
                total_tokens["prompt"] += response.usage.prompt_tokens
                total_tokens["completion"] += response.usage.completion_tokens
                total_tokens["total"] += response.usage.total_tokens
                await self._send_log(session_id, "token",
                    f"📊 Token: +{response.usage.total_tokens} (累计: {total_tokens['total']})")

            # 防御：API 可能返回非标准格式
            if not hasattr(response, "choices"):
                logger.error(f"LLM API 返回异常格式: {str(response)[:300]}")
                await self._send_log(session_id, "err", "❌ LLM API 返回异常")
                break

            response_msg = response.choices[0].message
            self.history.append(response_msg)

            # 推送文本回复
            if response_msg.content:
                await self._send_log(session_id, "agent", f"🤖 {response_msg.content}")

            # 检查是否需要调用工具
            if not response_msg.tool_calls:
                # 由 Agent 决策是否退出
                if response_msg.content and any(word in response_msg.content for word in ["再见", "退出"]):
                    return {"success": True, "response": response_msg.content, "exit": True, "tokens": total_tokens}
                break

            # 执行工具调用
            for tool_call in response_msg.tool_calls:
                function_name = tool_call.function.name
                args_str = tool_call.function.arguments
                args = json.loads(args_str) if args_str else {}

                await self._send_log(session_id, "tool",
                    f"🛠️ 调用工具: {function_name} | 参数: {json.dumps(args, ensure_ascii=False)}")

                try:
                    # 所有工具（含 Playwright 同步 API）必须在线程池中执行，
                    # 避免 "Sync API inside the asyncio loop" 报错
                    import asyncio as _asyncio
                    result = await _asyncio.to_thread(
                        execute_tool, function_name, **args
                    )
                except Exception as tool_err:
                    logger.error(f"工具执行失败 [{function_name}]: {tool_err}", exc_info=True)
                    result = {"success": False, "error": str(tool_err)}
                    await self._send_log(session_id, "err", f"❌ 工具失败 [{function_name}]: {tool_err}")

                await self._send_log(session_id, "tool", f"✅ 工具完成: {function_name}")

                # 将工具执行结果反馈给 LLM
                self.history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # 提取最终回复文本（history 中混合了 dict 和 ChatCompletionMessage 对象）
        final_content = ""
        for msg in reversed(self.history):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            if role == "assistant" and content:
                final_content = content
                break

        return {
            "success": True,
            "response": final_content,
            "tokens": total_tokens,
        }

    async def run_task(self, task_name: str, session_id: str = "default", **kwargs) -> Dict[str, Any]:
        """执行指定任务"""
        await self._send_log(session_id, "status", f"🔄 开始执行任务: {task_name}")

        try:
            if task_name == "full_flow":
                result = await self._run_full_flow(session_id)
            elif task_name == "scrape":
                result = await self._run_scrape(session_id)
            else:
                result = {"success": False, "message": f"未知任务: {task_name}"}

            await self._send_log(session_id, "ok", f"✅ 任务完成: {task_name}")
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"任务执行失败: {e}", exc_info=True)
            await self._send_log(session_id, "err", f"❌ 任务失败: {str(e)}")
            return {"success": False, "message": str(e)}

    async def _send_log(self, session_id: str, cls: str, html: str):
        """推送日志到 WebSocket（在线程池中安全调用）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在运行中的事件循环，直接 await
                await manager.send_log(session_id, {"cls": cls, "html": html})
            else:
                # 没有运行中的循环，使用 run_coroutine_threadsafe
                asyncio.run_coroutine_threadsafe(
                    manager.send_log(session_id, {"cls": cls, "html": html}),
                    asyncio.get_event_loop()
                )
        except Exception as e:
            logger.warning(f"推送日志失败: {e}")

    async def _run_full_flow(self, session_id: str):
        """执行完整流程（异步）"""
        from src.collectors.scrapers.scraper import Scraper
        from src.collectors.scrapers.wechat_scraper import WechatScraper
        from src.processors.data_processor import DataProcessor
        from src.processors.extractors.wechat_parser import WechatParser
        from src.processors.extractors.content_extractor import ContentExtractor
        from src.processors.mergers.final_merger import FinalMerger
        from src.agent.analyzer import run_analysis_flow

        def _progress_callback(current, total, msg):
            # 在非异步上下文中调用，需要通过事件循环
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._send_log(session_id, "tool", f"📊 ({current}/{total}) {msg}"),
                        loop
                    )
            except Exception:
                pass

        await self._send_log(session_id, "status", "📡 开始采集...")
        Scraper().fetch_and_save(progress_callback=_progress_callback)
        WechatScraper().run_scraper_flow(progress_callback=_progress_callback)

        await self._send_log(session_id, "status", "🧹 开始处理...")
        WechatParser().run_parser(progress_callback=_progress_callback)
        DataProcessor().run(progress_callback=_progress_callback)
        ContentExtractor().clean_and_refine(progress_callback=_progress_callback)
        FinalMerger().merge_intelligence(progress_callback=_progress_callback)

        await self._send_log(session_id, "status", "🧠 开始 AI 分析...")
        result = run_analysis_flow(progress_callback=_progress_callback)

        # 完整流程结束后，清理上下文（防止 Token 滚雪球）
        self._trim_history(max_rounds=3)

        return result

    async def _run_scrape(self, session_id: str):
        """仅执行采集"""
        from src.collectors.scrapers.scraper import Scraper
        from src.collectors.scrapers.wechat_scraper import WechatScraper

        await self._send_log(session_id, "status", "📡 开始采集...")
        Scraper().fetch_and_save()
        WechatScraper().run_scraper_flow()
        return {"message": "采集完成"}
