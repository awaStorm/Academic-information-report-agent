# src/agent/analyzer.py
import json
import os
import sys
import io
import glob
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from src.agent.database import AgentMemory
from src.agent.pusher import Pusher

# 1. 加载环境变量与配置[cite: 13]
load_dotenv()
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-v4-flash")
MAX_REPORTS = 5           
REPORT_DIR = "reports"    

# 解决 Windows 环境下的编码问题[cite: 13]
        # Removed sys.stdout redirection for Windows compatibility

# --- 关键路径配置：以项目根目录为准 ---[cite: 5, 12]
INPUT_FILE = os.path.join("data", "processed", "full_intelligence_stream.json")

def generate_report():
    """
    核心分析函数：调用大模型进行筛选与提取[cite: 13]
    返回: (report_md: str, res_data: dict)
    """
    if not API_KEY:
        print("❌ 错误：未在 .env 中找到 LLM_API_KEY")
        return None, None

    if not os.path.exists(INPUT_FILE):
        print(f"❌ 找不到合流文件: {INPUT_FILE}")
        return None, None
        
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 构造上下文数据流[cite: 13]
    context_stream = ""
    for idx, item in enumerate(raw_data):
        context_stream += f"ID: {idx} | 来源: {item['platform']} | 标题: {item['title']} | 内容: {item['body'][:1000]}\n"

    system_instruction = f"""
你是西安电子科技大学的【校园情报筛选与提取 Agent】。
当前日期：{today_str}

## 任务目标
1. 过滤：worth_push=false（排版通知、小编感悟、无营养转载等）。
2. 提取：教学安排、放假、考试、讲座、竞赛等硬核干货。
3. 合并：相似事件合并。
## 格式要求
1. source 必须包含编写单位（platform:author）。
2. deadline 字段由你自由描述：可以是"报名截止 5月20日"、"讲座时间 6月1日 14:00"、"5月15日起选课"等，根据情报性质灵活表述，不要统一写成"截止"。
3. link 字段：如果原数据中有完整的 http/https 链接则填入，否则留空字符串。绝对不要填入 ID、数字或其他非 URL 内容。

## 输出 JSON 格式
{{
  "pushed_items": [
    {{ "title": "", "category": "", "deadline": "", "brief": "摘要", "link": "", "source": "" }}
  ],
  "filtered_items": [
    {{ "title": "", "source": "", "reason": "理由", "summary": "15字内内容简述" }}
  ]
}}
"""

    try:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        print(f"🚀 Agent 正在通过 {MODEL_NAME} 分析情报...")
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"数据流：\n{context_stream}"}
            ],
            response_format={ 'type': 'json_object' },
            temperature=0.2 
        )
        
        res_data = json.loads(response.choices[0].message.content)
        report_md = render_markdown(res_data, today_str)
        return report_md, res_data

    except Exception as e:
        print(f"💥 AI 分析调用失败: {str(e)}")
        return None, None

def render_markdown(res_data, date_str):
    """将 JSON 结果渲染为 Markdown 格式[cite: 13]"""
    pushed = res_data.get("pushed_items", [])
    filtered = res_data.get("filtered_items", [])
    
    md = f"# 📅 西电校园情报简报 | {date_str}\n\n"
    md += "## ⚠️ 今日核心提醒\n"
    
    if not pushed:
        md += "> 📭 今日暂无高优先级干货情报。\n\n"
    else:
        pushed.sort(key=lambda x: x.get('deadline') if x.get('deadline') else "9999")
        for item in pushed:
            deadline_str = f"⏰ {item.get('deadline')}" if item.get('deadline') else ""
            link_str = f" [🔗详情]({item.get('link')})" if (item.get('link') and item.get('link').startswith('http')) else ""
            if deadline_str:
                md += f"- **[{item.get('source', '未知')}]** {deadline_str} | **{item.get('title', '无标题')}**\n"
            else:
                md += f"- **[{item.get('source', '未知')}]** **{item.get('title', '无标题')}**\n"
            md += f"  > 【{item.get('category', '校园动态')}】{item.get('brief')}{link_str}\n\n"

    md += "---\n### 🔍 垃圾回收站 (AI 已自动过滤)\n"
    if not filtered:
        md += "- (暂无过滤记录)\n"
    else:
        for f_item in filtered:
            md += f"- ~[{f_item.get('source', '未知')}] {f_item.get('title', '无标题')}~\n"
            md += f"  - **过滤理由**: {f_item.get('reason', '不符合标准')}\n"
            md += f"  - **内容简述**: {f_item.get('summary', '无摘要')}\n"
            
    md += f"\n\n> ✅ 本次分析 {len(pushed) + len(filtered)} 条原始情报\n"
    md += f"> 💡 **西电情报 Agent** 驱动中\n"
    return md

def save_and_cleanup(content, date_str):
    """保存报告并清理旧文件[cite: 12, 13]"""
    if not os.path.exists(REPORT_DIR):
        os.makedirs(REPORT_DIR)

    # 生成版本化文件名
    version = 1
    while True:
        file_name = f"Report_{date_str}_v{version}.md"
        file_path = os.path.join(REPORT_DIR, file_name)
        if not os.path.exists(file_path):
            break
        version += 1

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✨ 报告已保存: {file_path}")

    # 清理陈旧报告[cite: 13]
    existing = sorted(glob.glob(os.path.join(REPORT_DIR, "Report_*.md")))
    if len(existing) > MAX_REPORTS:
        for old_file in existing[:-MAX_REPORTS]:
            os.remove(old_file)
            print(f"扫除旧报告: {os.path.basename(old_file)}")

def run_analysis_flow():
    """
    Agent 核心工作流：集成去重、分析、保存与推送
    """
    print("🧠 Agent 正在启动深度情报分析流...")
    
    # 1. 初始化记忆和推送器
    db = AgentMemory()
    pusher = Pusher()
    
    # 2. 执行 AI 核心分析，获取初步结果
    report_md, res_data = generate_report()
    
    if not (report_md and res_data):
        print("❌ AI 分析未能生成有效数据，流程终止。")
        return {"success": False, "error_type": "ANALYSIS", "message": "AI 分析未能生成有效数据"}

    # 3. 智能去重与记忆过滤 (核心升级点)
    pushed_list = res_data.get("pushed_items", [])
    final_pushed_list = []

    for item in pushed_list:
        # 根据标题和内容生成唯一指纹
        item_hash = db.get_hash(item['title'], item['brief'])
        
        # 检查数据库，如果以前推过，就跳过
        if db.is_seen(item_hash):
            print(f"⏭️  跳过已处理的情报: {item['title']}")
            continue
        
        # 如果没推过，加入本次推送清单并记入数据库
        final_pushed_list.append(item)
        db.save_memory(item_hash, item['title'], item['source'], "pushed")

    # 4. 保存本地报告（包含所有分析记录，用于复核）
    file_tag = datetime.now().strftime("%Y%m%d")
    save_and_cleanup(report_md, file_tag)
    
    # 5. 执行最终推送（仅针对新情报）
    if final_pushed_list:
        display_date = datetime.now().strftime("%Y-%m-%d")
        print(f"📢 发现 {len(final_pushed_list)} 条新情报，正在通过企业微信发送...")
        
        # 优先推企业微信，若失败可选择 Server 酱备份
        if pusher.send_wecom(final_pushed_list, display_date):
            print("🚀 推送成功！")
        else:
            print("⚠️ 企业微信推送异常，尝试备份渠道...")
            pusher.send_serverchan(final_pushed_list, display_date)
    else:
        print("📭 经数据库比对，今日无新增核心情报，无需推送。")
    
    # 6. 任务完成，关闭数据库连接
    db.close()
    return {"success": True, "pushed": len(final_pushed_list)}

if __name__ == "__main__":
    run_analysis_flow()