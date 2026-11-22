import json
import os
from dotenv import load_dotenv
from datetime import datetime

# 导入修正后的工具配置
from tools_config import TOOLS_METADATA, execute_tool
from src.utils.config_loader import CONFIG, get_identity_prompt, get_display_name
from src.utils.llm_client import build_llm_client, call_with_retry

load_dotenv()

class XidianAgent:
    def __init__(self):
        """初始化 Agent，配置模型与记忆"""
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        
        if not api_key:
            raise ValueError("LLM_API_KEY 未设置，请在 .env 中配置或通过前端保存")
        
        # 统一客户端口径：默认绕开系统代理 + 连接类错误自动重试
        # （详见 src/utils/llm_client.py）
        self.client = build_llm_client(api_key, base_url)
        
        # ✅ 修改：从 CONFIG 读取模型名称，不再硬编码[cite: 4]
        self.model = CONFIG.get("analysis", {}).get("model_name", "")
        if not self.model:
            raise ValueError("模型名称未配置 (CONFIG['analysis']['model_name'] 为空)")
        # ✅ 修改：同步读取分析参数
        self.temperature = CONFIG.get("analysis", {}).get("temperature", 0.1)
        self.max_tokens = CONFIG.get("analysis", {}).get("max_tokens", 20000)

        self.history = []

        # 工具调用轮次上限：防止 LLM 陷入「扫码→重抓→仍失败→再扫码」无限循环烧 token
        self.MAX_TOOL_ROUNDS = 15
        
        # 核心系统提示词
        self.system_prompt = {
            "role": "system",
            "content": (
                get_identity_prompt() + "\n"
                "你有权访问超星通知、微信公众号数据、本地数据库以及推送工具。\n\n"
                "## 执行准则\n"
                "1. 链路逻辑：采集 -> 处理 -> 解析 -> 合流 -> 分析 -> 推送。\n"
                "2. 交互性：在执行耗时工具前，先口头告知用户你的计划。\n"
                "3. 异常处理：若工具返回 error_type 为 SESSION_EXPIRED 或 AUTH（登录失效/凭证缺失），立即调用对应的扫码登录工具（微信情报用 harvest_weread_session，超星用 harvest_chaoxing_session）。登录完成后，**必须自动重新执行之前因凭证失效而中断的工具**，不要等待用户再次输入指令。\n"
                "4.优先理解用户意图。如果用户说“只分析不推送”，就跳过微信相关工具和推送步骤。\n"
                "5. 结束意图：当用户表达再见或任务完成时，请礼貌告别并在回复中包含'再见'或'退出'。\n"
                "6. 尊重用户的显式指令：如果用户明确要求「扫码登录」「重试」「再抓一次」，即使你判断可能无效，也必须照办——可以先说明你的判断，但不得替用户拒绝，更不得以'这样做没用'为由不执行。\n"
                "7. 回复简洁：先给结论与关键事实（失败数量、error_type、错误码等可核验信息），再给必要说明；同一个结论只讲一次，不反复论证、不长篇铺垫。\n"
                "8. 信源扩展：当用户要求适配不同学校、寻找特定竞赛/通知渠道、或自定义信源时，用 discover_source_cards 生成候选卡片（网站大卡片+公众号小卡片），用 list_source_cards 查看，用 add_card_to_checklist 加入检查清单，用 remove_card 删除。信源不局限于超星/微信预设；网站卡片会在生成时做可达性验证，未验证的如实告知用户由其决定。生成后不要擅自把所有卡片都加入清单，先让用户确认。\n"
                "## 故障排除指引\n"
                "1. run_wechat_scraper 的返回值必须按 error_type 区分，严禁把抓取失败当成'没有新情报'：\n"
                "   - success=true 且 count>0：正常取到文章。\n"
                "   - success=true 且 count=0：通道正常、目标公众号本轮确实没有文章。只有这一种才是'没有新情报'，请如实告知用户，不要引导用户扫码。\n"
                "   - success=false 且 error_type=SESSION_EXPIRED/AUTH：登录失效或凭证缺失，才调用 harvest_weread_session 扫码，随后自动重跑抓取。\n"
                "   - success=false 且 error_type=RATE_LIMITED：触发限流，凭证仍然有效。请明确告诉用户'稍后重试即可，无需重新扫码'，绝不要引导用户扫码。\n"
                "   - success=false 且 error_type=SOURCE_UNAVAILABLE/NOT_FOUND：数据源不可用或目标号未被收录。请如实说明数据源异常，绝不能谎报为'没有新情报'。\n"
                "   - 返回值中出现 failed_targets：说明部分公众号本轮抓取失败，请一并如实告知用户是哪些号、什么原因。\n"
                "2. 不要只是说'遇到问题'，要说出具体是'登录过期'、'触发限流'、'数据源异常'还是'确实没有新内容'。"
            )
        }
        # 初始化时注入系统提示词
        self.history.append(self.system_prompt)

    def chat(self, user_input):
        """核心交互循环"""
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timed_input = f"【当前系统时间：{current_time_str}】\n用户指令：{user_input}"
        self.history.append({"role": "user", "content": timed_input})

        tool_rounds = 0
        while True:
            # 1. 发送请求给 LLM（连接类错误自动指数退避重试，避免瞬时抖动中断对话）
            response = call_with_retry(
                self.client.chat.completions.create,
                model=self.model,
                messages=self.history,
                tools=TOOLS_METADATA,
                tool_choice="auto",
                # ✅ 修改：应用配置中的温度和 Token 限制
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # 防御：API 可能返回非标准格式
            if not hasattr(response, "choices"):
                print(f"  [系统日志] ❌ LLM API 返回异常格式: {str(response)[:300]}")
                break

            response_msg = response.choices[0].message
            self.history.append(response_msg)

            # ✅ 修改：根据 enable_console_report 开关决定是否打印回复
            if response_msg.content and CONFIG.get("pusher", {}).get("enable_console_report", True):
                print(f"\n🤖 Agent: {response_msg.content}")

            # 3. 检查是否需要调用工具
            if not response_msg.tool_calls:
                # 由 Agent 决策是否退出（仅短回复中的退出词才判定，避免报告正文含该词导致误退出）
                if (response_msg.content and len(response_msg.content) < 50
                        and any(word in response_msg.content for word in ["再见", "退出"])):
                    return "EXIT_SIGNAL"
                break

            # 工具调用轮次保护：超限后强制收敛为文字总结，防止无限循环烧 token
            tool_rounds += 1
            if tool_rounds > self.MAX_TOOL_ROUNDS:
                print(f"  [系统日志] ⚠️ 工具调用已达上限（{self.MAX_TOOL_ROUNDS} 轮），强制停止工具执行")
                self.history.append({
                    "role": "user",
                    "content": (
                        f"[系统] 工具调用轮次已达上限（{self.MAX_TOOL_ROUNDS} 轮）。"
                        "请立即基于以上已获取的信息直接输出文字总结；未完成的部分请明确说明原因与建议的后续操作。"
                        "不要再尝试调用任何工具。"
                    ),
                })
                response = call_with_retry(
                    self.client.chat.completions.create,
                    model=self.model,
                    messages=self.history,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                summary = ""
                if hasattr(response, "choices") and response.choices:
                    summary = response.choices[0].message.content or ""
                if summary:
                    self.history.append({"role": "assistant", "content": summary})
                    if CONFIG.get("pusher", {}).get("enable_console_report", True):
                        print(f"\n🤖 Agent: {summary}")
                break

            # 4. 执行工具逻辑
            for tool_call in response_msg.tool_calls:
                function_name = tool_call.function.name

                # ✅ 修正变量名错误：使用 tool_call.function.arguments
                args_str = tool_call.function.arguments
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    # LLM 偶发输出非法 JSON：不崩整轮对话，把错误作为工具结果喂回模型自行纠正
                    args = None

                if args is None:
                    print(f"  [系统日志] ❌ 工具参数 JSON 解析失败 [{function_name}]，已将错误反馈给模型")
                    result = {"success": False, "error": f"工具参数不是合法 JSON: {str(args_str)[:200]}"}
                else:
                    print(f"  [系统日志] 🛠️  启动工具: {function_name} | 参数: {args}")

                    # 调用 tools_config 中的执行器，支持参数解包[cite: 2]
                    result = execute_tool(function_name, **args)

                # 将工具执行结果反馈给 LLM
                self.history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })

# --- 主交互入口 ---

if __name__ == "__main__":
    agent = XidianAgent()
    print("========================================")
    print(f"🎓 {get_display_name()} 启动成功！")
    print("提示：输入'退出'结束对话。")
    print("========================================")
    
    while True:
        try:
            user_prompt = input("\n👤 用户: ").strip()
            if not user_prompt:
                continue
                
            # 执行 chat 并捕获退出信号
            status = agent.chat(user_prompt)
            
            if status == "EXIT_SIGNAL":
                break
        except KeyboardInterrupt:
            print("\n👋 程序已被手动终止。")
            break
        except Exception as e:
            print(f"\n💥 运行异常: {str(e)}")