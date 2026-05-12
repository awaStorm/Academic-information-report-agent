import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# 导入修正后的工具配置
from tools_config import TOOLS_METADATA, execute_tool
from src.utils.config_loader import CONFIG

load_dotenv()

class XidianAgent:
    def __init__(self):
        """初始化 Agent，配置模型与记忆"""
        self.client = OpenAI(
            api_key=os.getenv("LLM_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL")
        )
        
        # ✅ 修改：从 CONFIG 读取模型名称，不再硬编码[cite: 4]
        self.model = CONFIG['analysis']['model_name']
        # ✅ 修改：同步读取分析参数
        self.temperature = CONFIG['analysis']['temperature']
        self.max_tokens = CONFIG['analysis']['max_tokens']
        
        self.history = []
        
        # 核心系统提示词
        self.system_prompt = {
            "role": "system",
            "content": (
                "你是西安电子科技大学的【校园情报 Agent】。\n"
                "你有权访问超星通知、微信公众号数据、本地数据库以及推送工具。\n\n"
                "## 执行准则\n"
                "1. 链路逻辑：采集 -> 处理 -> 解析 -> 合流 -> 分析 -> 推送。\n"
                "2. 交互性：在执行耗时工具前，先口头告知用户你的计划。\n"
                "3. 异常处理：若凭证失效（AUTH_EXPIRED），引导用户调用扫码工具。\n"
                "4.优先理解用户意图。如果用户说“只分析不推送”，就跳过微信相关工具和推送步骤。\n"
                "5. 结束意图：当用户表达再见或任务完成时，请礼貌告别并在回复中包含'再见'或'退出'。"
                "## 故障排除指引\n"
                "1. 如果 run_wechat_scraper 返回 count 为 0，说明‘当前没有新通知’。这不代表登录失败！不要反复让用户扫码。请告知用户：'目前没有发现新推文，库中现有的最近情报如下...'，并尝试读取 data/raw/ 下的缓存文件。\n"
                "2. 只有当工具明确返回 AUTH_FILE_MISSING 或 HTTP_ERROR (401/403) 时，才调用登录工具。"
                "3. 不要只是说‘遇到问题’，要说出具体是‘登录过期’还是‘没搜到新内容’。"
            )
        }
        # 初始化时注入系统提示词
        self.history.append(self.system_prompt)

    def chat(self, user_input):
        """核心交互循环"""
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timed_input = f"【当前系统时间：{current_time_str}】\n用户指令：{user_input}"
        self.history.append({"role": "user", "content": timed_input})

        while True:
            # 1. 发送请求给 LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                tools=TOOLS_METADATA,
                tool_choice="auto",
                # ✅ 修改：应用配置中的温度和 Token 限制
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            response_msg = response.choices[0].message
            self.history.append(response_msg)

            # ✅ 修改：根据 enable_console_report 开关决定是否打印回复
            if response_msg.content and CONFIG['pusher']['enable_console_report']:
                print(f"\n🤖 Agent: {response_msg.content}")

            # 3. 检查是否需要调用工具
            if not response_msg.tool_calls:
                # 由 Agent 决策是否退出
                if any(word in response_msg.content for word in ["再见", "退出"]):
                    return "EXIT_SIGNAL"
                break

            # 4. 执行工具逻辑
            for tool_call in response_msg.tool_calls:
                function_name = tool_call.function.name
                
                # ✅ 修正变量名错误：使用 tool_call.function.arguments
                args_str = tool_call.function.arguments
                args = json.loads(args_str) if args_str else {}
                
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
    print("🎓 西电校园情报 Agent 启动成功！")
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