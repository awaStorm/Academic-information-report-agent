# tools_config.py

from src.collectors.sessions.session_harvester import SessionHarvester
from src.collectors.sessions.wechat_harvester import WechatHarvester
from src.collectors.scrapers.scraper import run_scraper_flow, Scraper
from src.collectors.scrapers.wechat_scraper import run_wechat_scraper_flow, WechatScraper
from src.processors.data_processor import DataProcessor
from src.processors.extractors.content_extractor import ContentExtractor
from src.processors.extractors.wechat_parser import WechatParser
from src.processors.mergers.final_merger import FinalMerger
from src.agent.database import AgentMemory
from src.agent.pusher import Pusher
from src.agent.analyzer import run_analysis_flow

# --- 第一部分：给 LLM 看的工具描述 (Metadata) ---
# 严格遵循 OpenAI/DeepSeek 的 Tool Calling 格式
TOOLS_METADATA = [
    {
        "type": "function",
        "function": {
            "name": "harvest_chaoxing_session",
            "description": "调起有头浏览器进行超星扫码登录。当本地凭证失效、不存在或爬虫返回 401 错误时调用。此操作需要人工扫码。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "harvest_wechat_session",
            "description": "获取微信公众平台登录凭证（Token 和 Cookies）。当微信爬虫报凭证过期或需要初始化登录环境时调用。此操作需要人工扫码。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_chaoxing_scraper",
            "description": "抓取超星校园通知列表。当需要更新校园情报数据时调用。如果返回 AUTH_EXPIRED，说明需要先调用扫码工具。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_wechat_scraper",
            "description": "抓取微信公众号情报。若用户提到特定公众号（如'西电物理'），请务必将全名传入 extra_query 参数以执行定向扩充抓取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "extra_query": {
                        "type": "string",
                        "description": "可选参数。如果你想抓取预设列表（如教务处）之外的特定公众号（例如'西电计科'、'西电物理'），请在此处传入公众号全名。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_raw_data",
            "description": "对超星抓取的原始 JSON 数据进行清洗和标准化。将杂乱的字段转化为包含标题、日期、正文和附件链接的统一格式。在抓取完成后必须调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "refine_data_for_ai",
            "description": "将清洗后的情报进行字段对齐（例如 content 转为 body）。这是在进行 AI 总结、分析或生成日报前的最后一个步骤，确保数据格式符合 AI 模型的要求。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "parse_wechat_content",
            "description": "对微信抓取的原始链接进行深度解析。该工具会访问微信网页并提取完整的正文文本。当需要对微信文章进行总结或日报生成时，必须先运行此工具以获得正文。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "merge_all_intelligence",
            "description": "合流工具：将来自超星（学习通）通知和微信公众号文章的所有已处理情报合并为一个统一的时间轴列表。在执行 AI 总结或生成最终日报之前，必须调用此工具以汇总全量数据,这是生成 full_intelligence_stream.json 的唯一途径。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_intelligence_memory",
            "description": "记忆检查工具：在处理具体情报前，先检查该情报是否已在数据库中处理过（去重）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "platform": {"type": "string"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_final_report",
            "description": "推送工具：将筛选出的核心情报列表发送到企业微信和 Server 酱。该工具接收格式化后的情报对象列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pushed_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "brief": {"type": "string"},
                                "source": {"type": "string"},
                                "link": {"type": "string"},
                                "deadline": {"type": "string"}
                            }
                        }
                    },
                    "date_str": {"type": "string", "description": "日期，如 2026-05-01"}
                },
                "required": ["pushed_items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_and_push_intelligence",
            "description": "执行深度情报分析。该工具会比对数据库去重、调用 AI 提取干货（含灵活的时间/地点说明）、生成带【垃圾回收站】的 Markdown 报告并保存至 reports 目录（循环保留5份），最后推送至企业微信。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# --- 第二部分：给代码看的函数映射 (Dispatch Table) ---
# 这里的 key 必须与上面的 "name" 字段完全一致
TOOL_MAP = {
    "harvest_chaoxing_session": lambda: SessionHarvester().run_harvest(),
    "harvest_wechat_session": lambda: WechatHarvester().run_harvest(),
    "run_chaoxing_scraper": lambda: Scraper().fetch_and_save(),
    "run_wechat_scraper": lambda extra_query=None, progress_callback=None: run_wechat_scraper_flow(extra_query=extra_query, progress_callback=progress_callback),
    "process_raw_data": lambda: DataProcessor().run(),
    "refine_data_for_ai": lambda: ContentExtractor().clean_and_refine(),
    "parse_wechat_content": lambda progress_callback=None: WechatParser().run_parser(),
    "merge_all_intelligence": lambda: FinalMerger().merge_intelligence(),
    "check_intelligence_memory": lambda title, content, platform: _check_and_save(title, content, platform),
    "send_final_report": lambda pushed_items, date_str=None: _push_notification(pushed_items, date_str),
    "analyze_and_push_intelligence": lambda: run_analysis_flow(),
}

def _check_and_save(title, content, platform):
    """去重检查并保存"""
    db = AgentMemory()
    item_hash = db.get_hash(title, content)
    seen = db.is_seen(item_hash)
    if not seen:
        db.save_memory(item_hash, title, platform, "pushed")
    db.close()
    return {"seen": seen, "hash_id": item_hash}

def _push_notification(pushed_items, date_str=None):
    """推送通知"""
    if date_str is None:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
    pusher = Pusher()
    wechat_ok = pusher.send_wecom(pushed_items, date_str)
    serverchan_ok = pusher.send_serverchan(pushed_items, date_str)
    return {"success": wechat_ok or serverchan_ok, "wecom": wechat_ok, "serverchan": serverchan_ok}

# 辅助函数：方便 Agent 执行器直接调用
def execute_tool(tool_name: str, **kwargs):
    """支持解包参数的执行器"""
    if tool_name in TOOL_MAP:
        # 使用 **kwargs 自动匹配工具需要的参数
        return TOOL_MAP[tool_name](**kwargs)
    return {"success": False, "error": f"未找到名为 {tool_name} 的工具"}
