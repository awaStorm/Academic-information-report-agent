# src/agent/analyzer.py
import json
import os
import sys
import io
import glob
import re
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from src.agent.database import AgentMemory
from src.agent.pusher import Pusher
from src.utils.config_loader import CONFIG

# 1. 加载环境变量与配置
load_dotenv()
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")
MODEL_NAME = os.getenv("LLM_MODEL", CONFIG.get("analysis", {}).get("model_name", "deepseek-v4-flash"))
MAX_REPORTS = 5
REPORT_DIR = "reports"

# 解决 Windows 环境下的编码问题

# --- 关键路径配置：以项目根目录为准 ---
INPUT_FILE = os.path.join("data", "processed", "full_intelligence_stream.json")
AUDIT_LOG_PATH = os.path.join("data", "audit.log")

def clean_title(title: str) -> str:
    """清洗标题：去除首尾空格、换行符、统一中文标点"""
    if not title:
        return ""
    title = title.strip().replace('\n', '').replace('\r', '')
    title = title.replace('【', '[').replace('】', ']')
    return title

def _filter_expired_items_conservative(raw_data: list, today_str: str) -> list:
    """
    保守策略过滤过期消息：
    - 只过滤"所有日期都过期"的硬过期条目
    - 如果任何一个日期晚于今天，保留该条目（避免误杀）
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    filtered = []

    for item in raw_data:
        text = item.get('title', '') + ' ' + item.get('body', '')

        # 提取所有日期
        all_dates = []
        date_patterns = [
            r'(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})',
            r'(\d{1,2})月(\d{1,2})日',
        ]

        for pattern in date_patterns:
            for match in re.finditer(pattern, text):
                try:
                    if len(match.groups()) == 3:
                        year, month, day = match.groups()
                        all_dates.append(datetime(int(year), int(month), int(day)))
                    elif len(match.groups()) == 2:
                        month, day = match.groups()
                        year = today.year
                        item_date = datetime(year, int(month), int(day))
                        if item_date < today:
                            item_date = datetime(year + 1, int(month), int(day))
                        all_dates.append(item_date)
                except ValueError:
                    continue

        # 保守策略：只有当所有日期都过期时才过滤
        if all_dates and all(d < today for d in all_dates):
            print(f"⏭️  跳过硬过期情报: {item.get('title', '')}")
            continue

        filtered.append(item)

    print(f"📅 保守过期过滤：{len(raw_data)} → {len(filtered)} 条（移除 {len(raw_data) - len(filtered)} 条硬过期）")
    return filtered

def _normalize_platform(source: str) -> str:
    """将 AI 输出的 source 字段归一化为 'wechat' / 'chaoxing'"""
    if not source or source == "unknown":
        return "unknown"
    s = source.lower()
    for kw in ("wechat", "chaoxing"):
        if kw in s:
            return kw
    first = source.split(":")[0].strip().lower()
    for kw in ("wechat", "chaoxing"):
        if kw in first:
            return kw
    return "wechat"

def generate_report(already_pushed_titles: list = None):
    """
    核心分析函数：调用大模型进行筛选与提取
    参数:
        already_pushed_titles: 已推送过的情报标题列表，LLM 将据此避免重复推荐
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

    # 构造上下文数据流
    context_stream = ""
    for idx, item in enumerate(raw_data):
        context_stream += f"ID: {idx} | 平台: {item.get('platform', 'unknown')} | 账号: {item.get('author', '未知')} | 标题: {item['title']} | 内容: {item['body'][:1000]}\n"

    # 构造已推送历史提示（如存在）
    pushed_hint = ""
    if already_pushed_titles:
        pushed_list = "\n".join(f"  - 【已推送】{t}" for t in already_pushed_titles)
        pushed_hint = f"""
## ⚠️ 以下情报已经在此前推送过，请勿重复推荐：
{pushed_list}

如果你在数据流中发现标题与上述列表高度相似的条目，应当将其归入 filtered_items 而非 pushed_items。
"""

    system_instruction = f"""
你是西安电子科技大学的【校园情报筛选与提取 Agent】。
当前日期：{today_str}
{pushed_hint}
## 任务目标
1. 过滤：worth_push=false（排版通知、小编感悟、无营养转载等）。
2. 提取：教学安排、放假、考试、讲座、竞赛等硬核干货。
3. 合并：相似事件合并。
4. 去重：如已推送列表中已有相同事件，必须过滤，不要重复推送。

## ⚠️ 硬性时间规则（必须遵守）
1. 当前系统时间是 {today_str}
2. 你必须在输出中为每条情报提取 "deadline" 字段（YYYY-MM-DD 格式，若无则为 null）
3. 如果 deadline < {today_str}，必须标记为 [EXPIRED] 并放入 filtered_items
4. 不要因为"内容重要"就推送过期消息
5. 如果你的输出中包含过期消息，将被视为严重错误

## 格式要求
1. source 字段必须严格填入「平台:账号名」格式，其中：
   - 平台：直接取原始数据的"平台"字段值（wechat 或 chaoxing）
   - 账号名：直接取原始数据的"账号"字段值（即发布该消息的公众号/通知源名称），不要替换或改写
   - 如果你想补充更细粒度的来源信息（如具体工作室、部门等），在账号名后用中文括号标注
   - 示例：wechat:校团委、chaoxing:教务处、wechat:西电社团（POD影音工作室）
2. deadline 字段：必须是 YYYY-MM-DD 格式（如 2026-06-28），如果无法提取具体日期则为 null
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
            response_format={'type': 'json_object'},
            temperature=CONFIG.get("analysis", {}).get("temperature", 0.2)
        )

        res_data = json.loads(response.choices[0].message.content)
        report_md = render_markdown(res_data, today_str)
        return report_md, res_data

    except Exception as e:
        print(f"💥 AI 分析调用失败: {str(e)}")
        return None, None

def render_markdown(res_data, date_str):
    """将 JSON 结果渲染为 Markdown 格式"""
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
    """保存报告并清理旧文件"""
    if not os.path.exists(REPORT_DIR):
        os.makedirs(REPORT_DIR)

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

    existing = sorted(glob.glob(os.path.join(REPORT_DIR, "Report_*.md")))
    if len(existing) > MAX_REPORTS:
        for old_file in existing[:-MAX_REPORTS]:
            os.remove(old_file)
            print(f"扫除旧报告: {os.path.basename(old_file)}")

def _write_audit_log(final_pushed_list, db):
    """推送前审计日志"""
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        for item in final_pushed_list:
            item_hash = item.get('raw_hash') or db.get_hash(item['title'], item.get('brief', ''))
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PUSH | {item.get('title', '')} | hash={item_hash}\n")

def run_analysis_flow(progress_callback=None):
    """
    Agent 核心工作流：集成去重、分析、保存与推送
    返回: dict {"success": bool, "pushed": int, "message": str}
    """
    TOTAL_STAGES = 4

    def _progress(stage, msg):
        if progress_callback:
            try:
                progress_callback(stage, TOTAL_STAGES, msg)
            except Exception:
                pass

    print("🧠 Agent 正在启动深度情报分析流...")

    db = AgentMemory()
    pusher = Pusher()

    try:
        # === 第0步：保守过期过滤（代码层硬过滤）===
        if os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                raw_all = json.load(f)

            today_str = datetime.now().strftime("%Y-%m-%d")
            filtered_items = _filter_expired_items_conservative(raw_all, today_str)

            # 空数据检查1：保守过滤后无数据
            if not filtered_items:
                print("📢 今日无新增有效校园情报（全部硬过期），流程自动终止。")
                return {"success": True, "pushed": 0, "message": "No new intelligence to push."}

            # 写回过滤后的数据
            with open(INPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(filtered_items, f, ensure_ascii=False, indent=4)
        else:
            filtered_items = []

        # === 第1步：LLM 分析前预过滤已推送情报 ===
        already_pushed_titles = []
        if os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                raw_all = json.load(f)

            new_items = []
            for item in raw_all:
                # 优先使用 raw_hash（原始数据阶段生成，稳定不变）
                item_hash = item.get('raw_hash')
                if not item_hash:
                    body_key = str(item.get("body", ""))[:200]
                    item_hash = db.get_hash(item.get("title", ""), body_key)

                if db.is_seen(item_hash):
                    already_pushed_titles.append(item.get("title", ""))
                else:
                    new_items.append(item)

            if already_pushed_titles:
                print(f"🔍 预过滤：{len(already_pushed_titles)} 条已知情报已排除，剩余 {len(new_items)} 条新情报")
                with open(INPUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(new_items, f, ensure_ascii=False, indent=4)

        # === 第2步：执行 AI 核心分析 ===
        _progress(1, "正在调用 AI 分析情报...")
        report_md, res_data = generate_report(already_pushed_titles if already_pushed_titles else None)

        if not (report_md and res_data):
            print("❌ AI 分析未能生成有效数据，流程终止。")
            return {"success": False, "pushed": 0, "message": "AI 分析未能生成有效数据"}

        # 空数据检查2：AI 分析后无新内容
        pushed_list = res_data.get("pushed_items", [])
        if not pushed_list:
            print("📢 今日无新增有效校园情报（AI 分析后无新内容），流程自动终止。")
            return {"success": True, "pushed": 0, "message": "No new intelligence to push."}

        # === 第3步：智能去重与记忆过滤（核心升级点）===
        _progress(2, "正在数据库去重过滤...")
        final_pushed_list = []

        # 批内跨来源去重：同一篇文章若被多个来源通道同时返回，其 link / raw_hash 可能不同
        # （不同通道给出的 URL 规范形式不一致），但 raw_key 相同。这里按「raw_key → 清洗标题」
        # 做一次批内归并。注意：**不改动 db 记忆的 hash 语义**（仍然只用 raw_hash / 标题哈希），
        # 否则存量记录与新记录对不上，反而会造成重复推送。
        seen_in_batch = set()

        for item in pushed_list:
            batch_key = item.get('raw_key') or clean_title(item.get('title', ''))
            if batch_key in seen_in_batch:
                print(f"⏭️  跳过本轮重复的情报（跨来源）: {item['title']}")
                continue
            seen_in_batch.add(batch_key)

            # 优先使用 raw_hash（原始数据阶段生成，稳定不变）
            item_hash = item.get('raw_hash')
            if not item_hash:
                item_hash = db.get_hash(item['title'], item.get('brief', ''))

            # 检查数据库（MD5 / raw_hash）
            if db.is_seen(item_hash):
                print(f"⏭️  跳过已处理的情报 (hash): {item['title']}")
                continue

            # 检查标题精确匹配（使用清洗后的标题）
            cleaned_title = clean_title(item['title'])
            db.cursor.execute("SELECT 1 FROM intelligence_memory WHERE TRIM(title) = ? AND status = 'pushed'", (cleaned_title,))
            if db.cursor.fetchone():
                print(f"⏭️  跳过已处理的情报 (标题): {item['title']}")
                continue

            # 模糊匹配兜底（防止标点抖动）
            db.cursor.execute("SELECT title FROM intelligence_memory WHERE status = 'pushed' AND TRIM(title) LIKE ?", (f"%{cleaned_title[:10]}%",))
            fuzzy_match = db.cursor.fetchone()
            if fuzzy_match:
                print(f"⏭️  跳过已处理的情报 (模糊匹配): {item['title']} (匹配到: {fuzzy_match[0]})")
                continue

            # 检查 deadline（AI 输出了结构化字段）
            deadline_str = item.get('deadline')
            if deadline_str and deadline_str != 'null':
                try:
                    deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
                    if deadline < datetime.now():
                        print(f"⏭️  跳过过期情报 (deadline): {item['title']} (deadline: {deadline_str})")
                        continue
                except ValueError:
                    pass

            final_pushed_list.append(item)
            db.save_memory(item_hash, item['title'], item.get('source', ''), "pushed")

        # 空数据检查3：代码级去重后无数据
        if not final_pushed_list:
            print("📢 今日无新增有效校园情报（全部已推送），流程自动终止。")
            return {"success": True, "pushed": 0, "message": "No new intelligence to push."}

        # === 第4步：保存本地报告 ===
        _progress(3, "正在保存分析报告...")
        file_tag = datetime.now().strftime("%Y%m%d")
        save_and_cleanup(report_md, file_tag)

        # === 第5步：执行最终推送 ===
        _progress(4, f"正在推送 {len(final_pushed_list)} 条情报...")
        display_date = datetime.now().strftime("%Y-%m-%d")
        print(f"📢 发现 {len(final_pushed_list)} 条新情报，正在通过企业微信发送...")

        # 推送前审计日志
        _write_audit_log(final_pushed_list, db)

        if pusher.send_wecom(final_pushed_list, display_date):
            print("🚀 推送成功！")
        else:
            print("⚠️ 企业微信推送异常，尝试备份渠道...")
            pusher.send_serverchan(final_pushed_list, display_date)

        # 写入推送记录表（供前端仪表盘统计）
        for item in final_pushed_list:
            db.save_pushed_record(
                title=item.get('title', ''),
                platform=_normalize_platform(item.get('source', 'unknown')),
                category=item.get('category', '其他动态'),
                brief=item.get('brief', ''),
                link=item.get('link', ''),
                status='pushed'
            )

        return {"success": True, "pushed": len(final_pushed_list), "message": "分析完成"}

    except Exception as e:
        print(f"💥 分析流程异常: {str(e)}")
        return {"success": False, "pushed": 0, "message": str(e)}

    finally:
        db.close()

if __name__ == "__main__":
    run_analysis_flow()
