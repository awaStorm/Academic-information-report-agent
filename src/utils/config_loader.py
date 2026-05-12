import yaml
import os

DEFAULT_CONFIG = {
    "analysis": {
        "max_tokens": 20000,
        "model_name": "deepseek-v4-flash",
        "temperature": 0.1,
    },
    "collectors": {
        "wechat": {
            "delay_range": [5, 8],
            "fetch_count": 5,
            "targets": [
                "西小电星球",
                "西电社团",
                "西电体育",
                "西安电子科技大学",
                "西电青年",
            ],
        }
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
