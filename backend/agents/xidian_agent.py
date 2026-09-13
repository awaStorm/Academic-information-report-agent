"""
backend/agents/xidian_agent.py - XidianAgent 适配层
继承 BaseAgent，适配原有 XidianAgent 逻辑，支持 WebSocket 日志推送
"""
import asyncio
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
                "3. 异常处理：若工具返回 error_type 为 SESSION_EXPIRED 或 AUTH（登录失效/凭证缺失），立即调用对应的扫码登录工具（微信情报用 harvest_weread_session，超星用 harvest_chaoxing_session），登录完成后自动重跑之前中断的抓取。\n"
                "4. 去重机制：analyze_and_push_intelligence 工具内部已完成代码级去重（基于 raw_hash 和标题精确匹配），你不需要担心重复推送问题。\n"
                "5. 时间敏感性：当前系统时间已注入每条用户消息，如果数据采集结果与昨天一致，可能确实是没有新情报，不要误判为'需要补充抓取'。\n"
                "6. 空数据保护：如果没有新情报，直接返回'无新情报'，不要无中生有或推送空消息。\n"
                "7. 采集失败必须如实区分：run_wechat_scraper 返回 success=false 时严禁说成'没有新情报'，需按 error_type 说明真实原因——SESSION_EXPIRED/AUTH 需扫码；RATE_LIMITED 为限流（稍后重试即可，无需扫码）；SOURCE_UNAVAILABLE/NOT_FOUND 为数据源异常或目标号未被收录。只有 success=true 且 count=0 才是'确实没有新文章'。返回值含 failed_targets 时，需告知用户哪些公众号失败及原因。\n"
                "8. 尊重用户的显式指令：如果用户明确要求「扫码登录」「重试」「再抓一次」，即使你判断可能无效，也必须照办——可以先说明你的判断，但不得替用户拒绝，更不得以'这样做没用'为由不执行。\n"
                "9. 回复简洁：先给结论与关键事实（失败数量、error_type、错误码等可核验信息），再给必要说明；同一个结论只讲一次，不反复论证、不长篇铺垫。\n"
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

            # 任务结果如实回传：失败不得再被包装成「任务完成 + success=True」
            ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            if ok:
                await self._send_log(session_id, "ok", f"✅ 任务完成: {task_name}")
            else:
                msg = (result.get("message") if isinstance(result, dict) else "") or ""
                await self._send_log(session_id, "err", f"⚠️ 任务未成功: {task_name} {msg}")
            return {"success": ok, "data": result}
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

    async def _report_wechat_result(self, session_id: str, result):
        """
        如实上报微信采集结果。

        旧实现直接丢弃 run_scraper_flow 的返回值，导致「抓取失败」与「确实没有新文章」
        在界面上完全无法区分（静默断流）。这里按 error_type 分类上报，失败必须可见。
        """
        if not isinstance(result, dict):
            await self._send_log(session_id, "err", "❌ 微信采集返回格式异常，无法判定结果")
            return

        if result.get("success"):
            count = result.get("count", 0)
            if count:
                await self._send_log(session_id, "status", f"✅ 微信情报取回 {count} 篇")
            else:
                await self._send_log(
                    session_id, "status",
                    "ℹ️ " + (result.get("message") or "微信通道正常，本轮无新文章"))

            failed = result.get("failed_targets") or []
            if failed:
                detail = "、".join(
                    "%s(%s)" % (i.get("target"), i.get("status")) for i in failed[:5])
                await self._send_log(
                    session_id, "err",
                    f"⚠️ 其中 {len(failed)} 个公众号抓取失败: {detail}")
            return

        err = result.get("error_type") or "ERROR"
        msg = result.get("message") or "微信采集失败"
        if err in ("SESSION_EXPIRED", "AUTH"):
            await self._send_log(
                session_id, "err",
                f"❌ 微信登录态失效，需重新扫码登录（harvest_weread_session）: {msg}")
        elif err == "RATE_LIMITED":
            await self._send_log(
                session_id, "err",
                f"⚠️ 微信数据源限流，稍后重试即可、无需重新扫码: {msg}")
        else:
            await self._send_log(session_id, "err", f"❌ 微信采集失败({err}): {msg}")

    async def _run_full_flow(self, session_id: str):
        """执行完整流程（异步）"""
        from src.collectors.scrapers.scraper import Scraper
        from src.collectors.scrapers.wechat_scraper import WechatScraper
        from src.processors.data_processor import DataProcessor
        from src.processors.extractors.wechat_parser import WechatParser
        from src.processors.extractors.content_extractor import ContentExtractor
        from src.processors.mergers.final_merger import FinalMerger
        from src.agent.analyzer import run_analysis_flow

        # 所有同步重活（含 Playwright 同步 API、requests 长抓取）都必须丢到线程池：
        #   1) Playwright Sync API 在 asyncio 事件循环线程里调用会直接抛错
        #      （"It looks like you are using Playwright Sync API inside the asyncio loop"），
        #      而「微信登录态自愈」需要拉起浏览器，一定会踩到；
        #   2) 采集/分析本身耗时数分钟，同步执行会把整个后端的 WebSocket 与 HTTP 一起卡死。
        loop = asyncio.get_running_loop()

        def _progress_callback(current, total, msg):
            # 该回调运行在工作线程中，必须用 run_coroutine_threadsafe 投递回主事件循环
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_log(session_id, "tool", f"📊 ({current}/{total}) {msg}"),
                    loop
                )
            except Exception:
                pass

        await self._send_log(session_id, "status", "📡 开始采集...")
        await asyncio.to_thread(Scraper().fetch_and_save, progress_callback=_progress_callback)
        # 微信采集结果必须上报：失败要可见，不能与「确实没有新文章」混为一谈
        wx_result = await asyncio.to_thread(
            WechatScraper().run_scraper_flow, progress_callback=_progress_callback)
        await self._report_wechat_result(session_id, wx_result)

        await self._send_log(session_id, "status", "🧹 开始处理...")
        await asyncio.to_thread(WechatParser().run_parser, progress_callback=_progress_callback)
        await asyncio.to_thread(DataProcessor().run, progress_callback=_progress_callback)
        await asyncio.to_thread(ContentExtractor().clean_and_refine, progress_callback=_progress_callback)
        await asyncio.to_thread(FinalMerger().merge_intelligence, progress_callback=_progress_callback)

        await self._send_log(session_id, "status", "🧠 开始 AI 分析...")
        result = await asyncio.to_thread(run_analysis_flow, progress_callback=_progress_callback)

        # 完整流程结束后，清理上下文（防止 Token 滚雪球）
        self._trim_history(max_rounds=3)

        # 微信采集失败不应中断整轮（超星数据仍可能有效），但必须让前端/LLM 看得到失败原因，
        # 否则「抓取失败」会再次被「分析完成」掩盖
        if isinstance(result, dict) and isinstance(wx_result, dict) and not wx_result.get("success"):
            result = dict(result)
            result["wechat_error"] = {
                "error_type": wx_result.get("error_type"),
                "message": wx_result.get("message"),
            }
        return result

    async def _run_scrape(self, session_id: str):
        """仅执行采集"""
        from src.collectors.scrapers.scraper import Scraper
        from src.collectors.scrapers.wechat_scraper import WechatScraper

        await self._send_log(session_id, "status", "📡 开始采集...")
        # 同 _run_full_flow：同步长任务必须放线程池，否则 Playwright Sync API 会直接报错
        await asyncio.to_thread(Scraper().fetch_and_save)
        wx_result = await asyncio.to_thread(WechatScraper().run_scraper_flow)
        await self._report_wechat_result(session_id, wx_result)

        # 采集阶段的结果如实回传：微信失败不算「采集完成」
        wx_ok = isinstance(wx_result, dict) and bool(wx_result.get("success"))
        wx_msg = (wx_result or {}).get("message") if isinstance(wx_result, dict) else ""
        return {
            "success": wx_ok,
            "message": wx_msg or ("采集完成" if wx_ok else "微信采集失败"),
            "wechat": wx_result,
        }
