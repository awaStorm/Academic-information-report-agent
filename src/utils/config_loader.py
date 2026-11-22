import yaml
import os

DEFAULT_CONFIG = {
    # 身份与展示配置：项目创建之初即面向任意学校，不绑定某一所学校。
    # school_name 留空 = 通用模式；填写后由 get_identity_prompt() 自动注入提示词。
    "profile": {
        "school_name": "",
        "assistant_display_name": "校园情报助手",
        "probe_query": "",
        "report_title": "校园情报提醒",
        "identity_prompt": (
            "你是【校园情报 Agent】，负责校园资讯的采集、筛选与推送。"
            "{school_context}"
        ),
    },
    "analysis": {
        "max_tokens": 20000,
        "model_name": "deepseek-v4-flash",
        "temperature": 0.1,
        # 多模态识图：可选增强，从通知图片中提取文字/日期/二维码内容
        # 未开启或调用失败时自动降级为纯文本分析，不阻塞主流程
        "multimodal": {
            "enabled": False,
            "api_key": "",
            "base_url": "",
            "model": "",
            "max_images": 3,
        },
    },
    "collectors": {
        # 微信来源编排（2026-07 原公众号后台接口被官方关闭后，主通道切换为微信读书）
        "wechat": {
            # 公众号切换间隔（秒）：来源切换比纯接口调用更敏感，下限比旧值 5 秒保守
            "delay_range": [8, 12],
            "fetch_count": 5,
            # 来源优先级：每轮按此顺序尝试，前一个通道拿不到数据才降级到下一个
            "source_priority": ["weread"],
            # 原公众号后台通道：接口已被官方精准软拒绝，保留代码以便恢复时切回，默认不发起无效请求
            "legacy_backend_enabled": False,
            # 备用公开索引兜底（反爬敏感），仅在主通道未收录目标号时按需启用
            "sogou_fallback_enabled": False,
            # 默认清空：由学生在信源卡片工作台从零自行添加，不再预置任何学校公众号
            "targets": [],
        },
        # 微信读书通道（当前主数据源）
        "weread": {
            # 单号最多翻几页：单页回执固定 15 条，页码越深相关度越低
            "max_pages": 2,
            # 同号翻页之间的等待区间（秒）
            "page_interval": [3, 5],
            # 单次请求超时（秒）与重试次数，遵循「超时要宽容」原则
            "timeout": 30,
            "retries": 3,
            # 触发限流后的递增退避间隔（秒）
            "rate_limit_backoff": [10, 30, 60],
            # 监控目标：由学生在信源卡片工作台自行添加（写回 collectors.wechat.targets）
            "targets": [],
        },
    },
    "pusher": {
        "enable_console_report": True,
        "enable_wecom": True,
    },
    "scheduler": {
        "enabled": True,
        "failure_alert_threshold": 3,
        "run_times": ["12:00", "22:00"],
    },
    "web_ui": {
        "dashboard_page_size": 20,
        "port": 7860,
    },
}

def _deep_merge(base, override):
    """递归合并字典，override 覆盖 base"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# 旧版本预置的默认公众号（v2.3 及以前）。升级到通用版时清空，
# 由学生从零自行添加；仅当存量列表与旧默认值完全一致才迁移，不误伤用户自定义列表。
_LEGACY_DEFAULT_TARGETS = {
    "西小电星球", "西电社团", "西电体育", "西安电子科技大学", "西电青年",
}


def _migrate_legacy_targets(saved: dict, config_path: str) -> bool:
    """把存量 settings.yaml 里的旧默认公众号清空并落盘。返回是否发生迁移。"""
    targets = (saved.get("collectors") or {}).get("wechat", {}).get("targets")
    if not isinstance(targets, list) or not targets:
        return False
    if set(targets) != _LEGACY_DEFAULT_TARGETS:
        return False
    saved["collectors"]["wechat"]["targets"] = []
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(saved, f, allow_unicode=True, default_flow_style=False)
    except OSError:
        # 只读文件系统等场景：迁移失败不阻塞启动，内存里仍然按清空处理
        pass
    return True


def load_config():
    # 获取项目根目录路径
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_dir = os.path.join(base_dir, "configs")
    config_path = os.path.join(config_dir, "settings.yaml")

    if not os.path.exists(config_path):
        # configs 目录和 settings.yaml 都不存在时，自动创建默认配置
        os.makedirs(config_dir, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, default_flow_style=False)
        return DEFAULT_CONFIG

    with open(config_path, "r", encoding="utf-8") as f:
        saved = yaml.safe_load(f) or {}

    # 升级迁移：旧默认公众号清空（仅完全匹配旧默认值时，不误伤用户自定义）
    _migrate_legacy_targets(saved, config_path)
    # 用默认值补全缺失字段（新增配置项时向下兼容）
    return _deep_merge(DEFAULT_CONFIG, saved)


# 全局配置对象
CONFIG = load_config()


# ---- profile 便捷读取（所有身份/展示硬编码点统一走这里） ----
def get_profile() -> dict:
    """返回身份与展示配置（始终含 DEFAULT_CONFIG 补全后的全部字段）"""
    return CONFIG.get("profile", {})


def get_display_name() -> str:
    """助手显示名：面向任意学校的通用默认，可由配置覆盖"""
    return get_profile().get("assistant_display_name") or "校园情报助手"


def get_school_name() -> str:
    """学校名：空字符串表示通用模式（未绑定特定学校）"""
    return (get_profile().get("school_name") or "").strip()


def get_identity_prompt() -> str:
    """生成系统身份提示词。school_name 为空时给出通用学校表述，绝不写死某所学校。"""
    template = get_profile().get("identity_prompt") or DEFAULT_CONFIG["profile"]["identity_prompt"]
    school = get_school_name()
    school_context = f"当前服务的学校是「{school}」。" if school else "当前面向任意学校提供服务。"
    return template.replace("{school_context}", school_context)


def get_report_title() -> str:
    """简报/推送标题前缀（如「校园情报提醒」）"""
    return get_profile().get("report_title") or "校园情报提醒"


def get_probe_query() -> str:
    """微信读书检索探活关键词：优先配置，其次学校名，最后通用兜底"""
    q = get_profile().get("probe_query")
    if q and str(q).strip():
        return str(q).strip()
    return get_school_name() or "大学"
