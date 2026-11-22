# src/agent/analyzer.py
import json
import os
import sys
import io
import glob
import re
import base64
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from src.agent.database import AgentMemory
from src.agent.pusher import Pusher
from src.processors.extractors.content_extractor import merge_links
from src.utils.config_loader import CONFIG, get_identity_prompt, get_report_title, get_display_name
from src.utils.llm_client import build_llm_client, call_with_retry

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
ANALYSIS_CACHE_DIR = "data"

# ============ 当日分析缓存（省 token）============

def _day_cache_path() -> str:
    return os.path.join(ANALYSIS_CACHE_DIR, f"analysis_cache_{datetime.now().strftime('%Y-%m-%d')}.json")

def _load_day_cache() -> dict:
    path = _day_cache_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def _save_day_cache(cache: dict):
    os.makedirs(ANALYSIS_CACHE_DIR, exist_ok=True)
    with open(_day_cache_path(), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def _cleanup_day_cache(keep_days: int = 2):
    """删除 keep_days 天之前的当日分析缓存文件"""
    now = datetime.now()
    for p in glob.glob(os.path.join(ANALYSIS_CACHE_DIR, "analysis_cache_*.json")):
        m = re.search(r'analysis_cache_(\d{4}-\d{2}-\d{2})\.json$', p)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        if (now - d).days > keep_days:
            os.remove(p)
            print(f"扫除过期分析缓存: {os.path.basename(p)}")

def _build_raw_index(raw_items: list, db) -> dict:
    """构建 清洗标题(小写) -> (raw_hash, 原始条目) 索引，用于把 LLM 输出映射回原始条目"""
    index = {}
    for it in raw_items:
        h = it.get('raw_hash') or db.get_hash(it.get('title', ''), str(it.get('body', ''))[:200])
        key = clean_title(it.get('title', '')).lower()
        if key:
            index[key] = (h, it)
    return index

def _lookup_raw_index(index: dict, title: str):
    """按清洗标题精确匹配查原始条目，前 10 字符前缀兜底（应对 LLM 轻微改写标题）"""
    key = clean_title(title or '').lower()
    if key and key in index:
        return index[key]
    prefix = key[:10]
    if prefix:
        for k, v in index.items():
            if k.startswith(prefix):
                return v
    return None, None

# ============ 多模态识图（可选，失败静默降级）============

_MM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def _get_multimodal_config() -> dict:
    """读取多模态配置（settings.yaml 的 analysis.multimodal），未配置则返回 enabled=False"""
    mm = CONFIG.get("analysis", {}).get("multimodal", {}) or {}
    return {
        "enabled": bool(mm.get("enabled", False)),
        "api_key": mm.get("api_key") or os.getenv("LLM_API_KEY", ""),
        "base_url": mm.get("base_url") or os.getenv("LLM_BASE_URL", ""),
        "model": mm.get("model", "") or os.getenv("LLM_MODEL", "deepseek-v4-flash"),
        "max_images": int(mm.get("max_images", 3)),
    }

def _download_image_to_base64(url: str, timeout: int = 8) -> Optional[str]:
    """下载图片转 base64 data URI；失败返回 None。微信图片有防盗链，必须带 UA 且可能需 Referer。"""
    try:
        import requests as _requests
        headers = {"User-Agent": _MM_UA, "Referer": "https://mp.weixin.qq.com/"}
        resp = _requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if not content_type.startswith("image/"):
            return None
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        return None

def extract_text_from_images(item: dict) -> str:
    """
    多模态识图：提取条目中图片的文字/日期/地点，返回补充文本。
    多模态未开启、无图片或调用失败时返回空字符串（静默降级，不阻塞主流程）。
    """
    mm = _get_multimodal_config()
    images = item.get("images") or []
    if not mm["enabled"] or not images or not mm["model"]:
        return ""

    picked = images[: mm["max_images"]]
    image_contents = []
    for url in picked:
        data_uri = _download_image_to_base64(url)
        if data_uri:
            image_contents.append({"type": "image_url", "image_url": {"url": data_uri}})
    if not image_contents:
        return ""

    try:
        client = build_llm_client(mm["api_key"], mm["base_url"])
        prompt = (
            "请仔细阅读这张图片，提取其中的所有文字信息，"
            "特别注意日期（年月日）、时间、地点、报名截止时间、活动名称等关键信息。"
            "只输出提取到的文字内容，不要添加解释。"
        )
        response = call_with_retry(
            client.chat.completions.create,
            model=mm["model"],
            messages=[
                {"role": "system", "content": "你是一个图片文字识别助手。"},
                {"role": "user", "content": [{"type": "text", "text": prompt}] + image_contents},
            ],
            temperature=0.1,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            print(f"🖼️  多模态识图提取 {item.get('title', '')[:20]}... 图片文字: {text[:80]}")
            return f"\n[图片文字提取] {text}"
        return ""
    except Exception as e:
        print(f"⚠️  多模态识图失败（降级为纯文本）: {str(e)[:100]}")
        return ""

def clean_title(title: str) -> str:
    """清洗标题：去除首尾空格、换行符、统一中文标点"""
    if not title:
        return ""
    title = title.strip().replace('\n', '').replace('\r', '')
    title = title.replace('【', '[').replace('】', ']')
    return title

def _sanitize_timeline(raw):
    """清洗 LLM 输出的 timeline：只保留 dict 节点，字段强制为字符串，日期斜杠归一。
    模型偶发输出 ["报名", null] 等异常结构时，若不清洗会导致 render_markdown 的
    node.get() 抛 AttributeError（整轮分析失败）以及前端渲染崩溃。"""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for node in raw:
        if not isinstance(node, dict):
            continue
        label = node.get("label")
        date = node.get("date")
        tm = node.get("time")
        label_str = str(label).strip() if isinstance(label, str) else ""
        date_str = str(date).strip().replace("/", "-") if isinstance(date, str) else ""
        if not label_str and not date_str:
            continue  # 既无标签又无日期的空节点没有展示价值
        cleaned.append({
            "label": label_str,
            "date": date_str,
            "time": str(tm).strip() if isinstance(tm, str) else "",
        })
    return cleaned

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
        body = item.get('body', '')
        # 多模态识图：从图片提取文字补充正文（未开启/失败则返回空串）
        img_text = extract_text_from_images(item)
        if img_text:
            body = body + img_text
        context_stream += f"ID: {idx} | 平台: {item.get('platform', 'unknown')} | 账号: {item.get('author', '未知')} | 标题: {item['title']} | 内容: {body[:1000]}\n"

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
{get_identity_prompt()}现在执行【校园情报筛选与提取 Agent】的具体任务。
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

## 📅 事件日期与事件时间轴（核心增强）
**重要：消息的获取时间（发布/推送时间）与事件实际发生日期是两回事，必须分离。**
1. `event_date`：事件**主要发生日期**（YYYY-MM-DD），例如竞赛开赛日、讲座当天、放假首日。
   - 仅当你能从正文中识别出明确的事件发生日期时才填写；**无法识别则填 null**（该条不会进入事件日历）。
   - 不要用消息的获取/发布时间充当 event_date。
2. `timeline`：事件时间轴数组，按时间顺序列出所有关键时间点，每个节点格式：
   `{{ "label": "报名截止", "date": "2026-09-20", "time": "23:59" }}`
   - label：节点语义（如「报名截止」「初赛」「决赛」「作业开始」「作业截止」「放假」「收假」）
   - date：YYYY-MM-DD；time：HH:MM（24 小时制，未知则留空字符串）
   - 单日期事件至少填一个节点；多阶段事件（报名→初赛→决赛）逐个列出。
3. 相对日期（「下周三」「后天」「本周六」）必须换算为绝对日期（已知当前日期 {today_str}）。
4. 若整条情报无任何可识别的事件日期，event_date 与 timeline 均留空。

## 格式要求
1. source 字段必须严格填入「平台:账号名」格式，其中：
   - 平台：直接取原始数据的"平台"字段值（wechat 或 chaoxing）
   - 账号名：直接取原始数据的"账号"字段值（即发布该消息的公众号/通知源名称），不要替换或改写
   - 如果你想补充更细粒度的来源信息（如具体工作室、部门等），在账号名后用中文括号标注
   - 示例：wechat:校团委、chaoxing:教务处
2. deadline 字段：必须是 YYYY-MM-DD 格式（如 2026-06-28），如果无法提取具体日期则为 null
3. link 字段：如果原数据中有完整的 http/https 链接则填入，否则留空字符串。绝对不要填入 ID、数字或其他非 URL 内容。
4. event_date 字段：YYYY-MM-DD 或 null
5. timeline 字段：对象数组，或空数组 []

## 输出 JSON 格式
{{
  "pushed_items": [
    {{ "title": "", "category": "", "deadline": "", "brief": "摘要", "link": "", "source": "",
       "event_date": "2026-09-20",
       "timeline": [
         {{ "label": "报名截止", "date": "2026-09-20", "time": "23:59" }},
         {{ "label": "初赛", "date": "2026-10-01", "time": "14:00" }}
       ] }}
  ],
  "filtered_items": [
    {{ "title": "", "source": "", "reason": "理由", "summary": "15字内内容简述" }}
  ]
}}
"""

    try:
        client = build_llm_client(API_KEY, BASE_URL)
        print(f"🚀 Agent 正在通过 {MODEL_NAME} 分析情报...")

        response = call_with_retry(
            client.chat.completions.create,
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"数据流：\n{context_stream}"}
            ],
            response_format={'type': 'json_object'},
            temperature=CONFIG.get("analysis", {}).get("temperature", 0.2)
        )

        res_data = json.loads(response.choices[0].message.content)
        # 防御：LLM 偶发输出非标准 timeline（非 list、字符串/null 元素、斜杠日期），
        # 在渲染与入库前统一清洗，避免单条脏数据导致整轮分析失败或前端崩溃
        pushed_items = res_data.get("pushed_items")
        if isinstance(pushed_items, list):
            for item in pushed_items:
                if isinstance(item, dict):
                    item["timeline"] = _sanitize_timeline(item.get("timeline"))
        report_md = render_markdown(res_data, today_str)
        return report_md, res_data

    except Exception as e:
        print(f"💥 AI 分析调用失败: {str(e)}")
        return None, None

def render_markdown(res_data, date_str):
    """将 JSON 结果渲染为 Markdown 格式"""
    pushed = res_data.get("pushed_items", [])
    filtered = res_data.get("filtered_items", [])

    md = f"# 📅 {get_report_title()} | {date_str}\n\n"
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
            md += f"  > 【{item.get('category', '校园动态')}】{item.get('brief')}{link_str}\n"
            # 事件时间轴（此处再洗一次：缓存命中恢复的旧条目不经 generate_report）
            timeline = _sanitize_timeline(item.get("timeline"))
            item["timeline"] = timeline
            if timeline:
                tl_parts = []
                for node in timeline:
                    t = node.get("date", "")
                    if node.get("time"):
                        t += f" {node['time']}"
                    tl_parts.append(f"{node.get('label', '')} {t}".strip())
                if tl_parts:
                    md += f"  > 📅 事件时间轴：{' → '.join(tl_parts)}\n"
            md += "\n"

    md += "---\n### 🔍 垃圾回收站 (AI 已自动过滤)\n"
    if not filtered:
        md += "- (暂无过滤记录)\n"
    else:
        for f_item in filtered:
            md += f"- ~[{f_item.get('source', '未知')}] {f_item.get('title', '无标题')}~\n"
            md += f"  - **过滤理由**: {f_item.get('reason', '不符合标准')}\n"
            md += f"  - **内容简述**: {f_item.get('summary', '无摘要')}\n"

    md += f"\n\n> ✅ 本次分析 {len(pushed) + len(filtered)} 条原始情报\n"
    md += f"> 💡 **{get_display_name()}** 驱动中\n"
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
        new_items = []
        if os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                raw_all = json.load(f)

            for item in raw_all:
                # 优先使用 raw_hash（原始数据阶段生成，稳定不变），统一回填供缓存与去重共用
                item_hash = item.get('raw_hash')
                if not item_hash:
                    body_key = str(item.get("body", ""))[:200]
                    item_hash = db.get_hash(item.get("title", ""), body_key)
                item['raw_hash'] = item_hash

                if db.is_seen(item_hash):
                    already_pushed_titles.append(item.get("title", ""))
                else:
                    new_items.append(item)

            if already_pushed_titles:
                print(f"🔍 预过滤：{len(already_pushed_titles)} 条已知情报已排除，剩余 {len(new_items)} 条新情报")

        # === 第1.5步：当日分析缓存 —— 同一 raw_hash 当天不重复送 LLM（省 token）===
        day_cache = _load_day_cache()
        to_analyze = []
        cached_hits = []
        for it in new_items:
            h = it.get('raw_hash') or db.get_hash(it.get('title', ''), str(it.get('body', ''))[:200])
            if h in day_cache:
                cached_hits.append((h, it))
            else:
                to_analyze.append(it)

        if cached_hits:
            print(f"💾 当日缓存命中 {len(cached_hits)} 条，复用上次分析结果；待分析 {len(to_analyze)} 条")

        # 只把未命中缓存的条目写入合流文件供 LLM 分析
        with open(INPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(to_analyze, f, ensure_ascii=False, indent=4)

        _cleanup_day_cache()

        # === 第2步：执行 AI 核心分析（全部命中缓存时跳过 LLM 调用）===
        _progress(1, "正在调用 AI 分析情报..." if to_analyze else "全部命中当日缓存，跳过 AI 调用...")
        raw_index = _build_raw_index(to_analyze, db)

        if to_analyze:
            report_md, res_data = generate_report(already_pushed_titles if already_pushed_titles else None)
        else:
            res_data = {"pushed_items": [], "filtered_items": []}

        # 合并当日缓存命中的决策到本轮结果
        merged_pushed = 0
        if res_data:
            for h, it in cached_hits:
                entry = day_cache.get(h) or {}
                if entry.get("decision") == "pushed":
                    cached_item = dict(entry.get("item") or {})
                    cached_item["raw_hash"] = h
                    res_data.setdefault("pushed_items", []).append(cached_item)
                    merged_pushed += 1
                elif entry.get("decision") == "filtered":
                    res_data.setdefault("filtered_items", []).append({
                        "title": it.get("title", ""),
                        "source": it.get("platform", entry.get("source", "unknown")),
                        "reason": entry.get("reason", "当日早前判定为垃圾"),
                        "summary": entry.get("summary", ""),
                    })
        if merged_pushed:
            print(f"💾 从当日缓存恢复 {merged_pushed} 条推送决策")

        # 全部命中缓存且无新推送：无需 LLM/报告，直接结束
        if not to_analyze and not (res_data and res_data.get("pushed_items")):
            print("📢 今日无新增有效校园情报（全部命中当日缓存且无新推送），流程自动终止。")
            return {"success": True, "pushed": 0, "message": "No new intelligence to push."}

        if not (report_md and res_data):
            print("❌ AI 分析未能生成有效数据，流程终止。")
            return {"success": False, "pushed": 0, "message": "AI 分析未能生成有效数据"}

        # 将本轮 LLM 新决策写入当日缓存（供下次运行复用）
        if res_data:
            new_cache_entries = 0
            for p_item in (res_data.get("pushed_items") or []):
                h, raw_it = _lookup_raw_index(raw_index, p_item.get("title", ""))
                if h:
                    p_item["raw_hash"] = p_item.get("raw_hash") or h
                    # P5：链接直取原始条目，不依赖 LLM 复述
                    if raw_it:
                        if not str(p_item.get("link") or "").startswith("http"):
                            p_item["link"] = raw_it.get("link", "") or ""
                        raw_links = raw_it.get("links") or []
                        if raw_links:
                            p_item["links"] = merge_links(
                                [p_item["link"]] if str(p_item.get("link") or "").startswith("http") else [],
                                raw_links,
                            )
                    day_cache[h] = {"decision": "pushed", "item": p_item}
                    new_cache_entries += 1
            for f_item in (res_data.get("filtered_items") or []):
                h, _raw = _lookup_raw_index(raw_index, f_item.get("title", ""))
                if h:
                    day_cache[h] = {
                        "decision": "filtered",
                        "source": f_item.get("source", ""),
                        "reason": f_item.get("reason", ""),
                        "summary": f_item.get("summary", ""),
                    }
                    new_cache_entries += 1
            if new_cache_entries:
                _save_day_cache(day_cache)
                print(f"💾 当日缓存已更新：+{new_cache_entries} 条决策")

        # 合并缓存决策后重渲染报告，保证缓存命中的条目也出现在报告里
        if res_data.get("pushed_items"):
            report_md = render_markdown(res_data, today_str)

        # === 第2.5步：垃圾条目入记忆库（junk）—— 下次预过滤直接排除，不再送 LLM ===
        junk_saved = 0
        for f_item in (res_data.get("filtered_items") or []):
            h, _raw = _lookup_raw_index(raw_index, f_item.get("title", ""))
            if h and not db.is_seen(h):
                db.save_memory(h, f_item.get("title", ""), f_item.get("source", ""), "junk",
                               reason=f_item.get("reason", ""))
                junk_saved += 1
        if junk_saved:
            print(f"🗑️  {junk_saved} 条垃圾情报已入记忆库（junk），后续运行自动排除")

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

        # 写入推送记录表（供前端仪表盘统计，links 为扩展链接数组，event_date/timeline 为事件日期分离）
        for item in final_pushed_list:
            event_date = item.get('event_date')
            # event_date 兜底：LLM 可能返回 "null" 字符串、非 YYYY-MM-DD 或斜杠日期，统一清洗
            if event_date in (None, "", "null"):
                event_date = None
            elif isinstance(event_date, str) and len(event_date) >= 10:
                event_date = event_date.strip().replace("/", "-")[:10]  # 归一为 YYYY-MM-DD
            else:
                event_date = None
            db.save_pushed_record(
                title=item.get('title', ''),
                platform=_normalize_platform(item.get('source', 'unknown')),
                category=item.get('category', '其他动态'),
                brief=item.get('brief', ''),
                link=item.get('link', ''),
                status='pushed',
                links=item.get('links') or None,
                event_date=event_date,
                timeline=item.get('timeline') or None,
            )

        return {"success": True, "pushed": len(final_pushed_list), "message": "分析完成"}

    except Exception as e:
        print(f"💥 分析流程异常: {str(e)}")
        return {"success": False, "pushed": 0, "message": str(e)}

    finally:
        db.close()

if __name__ == "__main__":
    run_analysis_flow()
