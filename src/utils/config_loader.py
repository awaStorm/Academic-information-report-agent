import yaml
import os

DEFAULT_CONFIG = {
    "analysis": {
        "max_tokens": 20000,
        "model_name": "deepseek-v4-flash",
        "temperature": 0.1,
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
            "targets": [
                "西小电星球",
                "西电社团",
                "西电体育",
                "西安电子科技大学",
                "西电青年",
            ],
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
            # 监控目标：留空表示复用 collectors.wechat.targets
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

    # 用默认值补全缺失字段（新增配置项时向下兼容）
    return _deep_merge(DEFAULT_CONFIG, saved)

# 全局配置对象
CONFIG = load_config()
