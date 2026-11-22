"""
backend/api/v1/config.py - 配置管理 API
替代原 app.py 中的配置面板逻辑
"""
import sys
import os
import yaml
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import set_key
from src.utils.config_loader import CONFIG

router = APIRouter()


class ProfileUpdate(BaseModel):
    """身份与展示配置（面向任意学校，不再绑定特定院校）"""
    school_name: Optional[str] = None
    assistant_display_name: Optional[str] = None
    probe_query: Optional[str] = None
    report_title: Optional[str] = None
    identity_prompt: Optional[str] = None


class ConfigUpdate(BaseModel):
    profile: Optional[ProfileUpdate] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    wecom_webhook: Optional[str] = None
    serverchan_key: Optional[str] = None
    enable_wecom: Optional[bool] = None
    enable_console_report: Optional[bool] = None
    fetch_count: Optional[int] = None
    delay_min: Optional[int] = None
    delay_max: Optional[int] = None
    wechat_targets: Optional[List[str]] = None
    scheduler_enabled: Optional[bool] = None
    run_times: Optional[List[str]] = None
    failure_alert_threshold: Optional[int] = None
    dashboard_page_size: Optional[int] = None
    hidden_nav: Optional[List[str]] = None  # 侧边栏隐藏的栏目 to 路径列表
    # 多模态识图
    multimodal_enabled: Optional[bool] = None
    multimodal_api_key: Optional[str] = None
    multimodal_base_url: Optional[str] = None
    multimodal_model: Optional[str] = None
    max_images: Optional[int] = None


def _get_project_root():
    return str(PROJECT_ROOT)


def _deep_merge(base, override):
    result = base.copy() if isinstance(base, dict) else {}
    for k, v in (override or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _save_settings_yaml(settings_dict: dict):
    """保存配置到 settings.yaml，并同步内存"""
    config_path = os.path.join(_get_project_root(), "configs", "settings.yaml")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}
    else:
        current = {}
    result = _deep_merge(current, settings_dict)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False)
    # 同步更新内存中的 CONFIG
    for k, v in settings_dict.items():
        if k in CONFIG and isinstance(CONFIG[k], dict) and isinstance(v, dict):
            CONFIG[k] = _deep_merge(CONFIG[k], v)
        else:
            CONFIG[k] = v


@router.get("/")
async def get_config():
    """获取当前配置（敏感字段脱敏）"""
    def _mask(val: str) -> str:
        return "***" if val else ""

    return {"success": True, "data": {
        "profile": dict(CONFIG.get("profile", {})),
        "llm_api_key": _mask(os.getenv("LLM_API_KEY")),
        "llm_base_url": os.getenv("LLM_BASE_URL", ""),
        "llm_model": os.getenv("LLM_MODEL", CONFIG.get("analysis", {}).get("model_name", "")),
        "temperature": CONFIG.get("analysis", {}).get("temperature", 0.1),
        "max_tokens": CONFIG.get("analysis", {}).get("max_tokens", 20000),
        "wecom_webhook": _mask(os.getenv("WECOM_WEBHOOK")),
        "serverchan_key": _mask(os.getenv("SERVERCHAN_SENDKEY")),
        "enable_wecom": CONFIG.get("pusher", {}).get("enable_wecom", True),
        "enable_console_report": CONFIG.get("pusher", {}).get("enable_console_report", True),
        "fetch_count": CONFIG.get("collectors", {}).get("wechat", {}).get("fetch_count", 5),
        "delay_range": CONFIG.get("collectors", {}).get("wechat", {}).get("delay_range", [8, 12]),
        "wechat_targets": CONFIG.get("collectors", {}).get("wechat", {}).get("targets", []),
        "scheduler_enabled": CONFIG.get("scheduler", {}).get("enabled", False),
        "run_times": CONFIG.get("scheduler", {}).get("run_times", ["08:00"]),
        "failure_alert_threshold": CONFIG.get("scheduler", {}).get("failure_alert_threshold", 3),
        "dashboard_page_size": CONFIG.get("web_ui", {}).get("dashboard_page_size", 20),
        "hidden_nav": [p for p in CONFIG.get("web_ui", {}).get("hidden_nav", []) if p != "/config"],
        # 多模态识图配置
        "multimodal_enabled": CONFIG.get("analysis", {}).get("multimodal", {}).get("enabled", False),
        "multimodal_api_key": _mask(CONFIG.get("analysis", {}).get("multimodal", {}).get("api_key", "")),
        "multimodal_base_url": CONFIG.get("analysis", {}).get("multimodal", {}).get("base_url", ""),
        "multimodal_model": CONFIG.get("analysis", {}).get("multimodal", {}).get("model", ""),
        "max_images": CONFIG.get("analysis", {}).get("multimodal", {}).get("max_images", 3),
    }}


@router.post("/")
async def update_config(config: ConfigUpdate):
    """更新配置"""
    results = []
    data = config.model_dump(exclude_unset=True)
    env_path = os.path.join(_get_project_root(), ".env")

    # 保存 .env 字段（跳过 "***" 脱敏值）
    env_fields = {
        "llm_api_key": "LLM_API_KEY",
        "llm_base_url": "LLM_BASE_URL",
        "llm_model": "LLM_MODEL",
        "wecom_webhook": "WECOM_WEBHOOK",
        "serverchan_key": "SERVERCHAN_SENDKEY",
    }
    for field, env_key in env_fields.items():
        if field in data and data[field] is not None and data[field] != "***":
            set_key(env_path, env_key, data[field])
            os.environ[env_key] = data[field]
            results.append(f"{env_key} 已保存")

    # 保存 YAML 配置
    yaml_settings = {}
    if "profile" in data:
        profile_in = data.get("profile") or {}
        yaml_settings["profile"] = {
            k: v for k, v in profile_in.items() if v is not None
        }
    if any(k in data for k in ("temperature", "max_tokens", "llm_model")):
        yaml_settings["analysis"] = {
            "model_name": data.get("llm_model", CONFIG.get("analysis", {}).get("model_name", "")),
            "temperature": data.get("temperature", CONFIG.get("analysis", {}).get("temperature", 0.1)),
            "max_tokens": data.get("max_tokens", CONFIG.get("analysis", {}).get("max_tokens", 20000)),
        }
    if any(k in data for k in ("multimodal_enabled", "multimodal_api_key", "multimodal_base_url", "multimodal_model", "max_images")):
        cur_mm = CONFIG.get("analysis", {}).get("multimodal", {}) or {}
        mm_cfg = {
            "enabled": data.get("multimodal_enabled", cur_mm.get("enabled", False)),
            "api_key": data.get("multimodal_api_key", cur_mm.get("api_key", "")),
            "base_url": data.get("multimodal_base_url", cur_mm.get("base_url", "")),
            "model": data.get("multimodal_model", cur_mm.get("model", "")),
            "max_images": data.get("max_images", cur_mm.get("max_images", 3)),
        }
        # api_key 脱敏值 "***" 不覆盖原值
        if mm_cfg["api_key"] == "***":
            mm_cfg["api_key"] = cur_mm.get("api_key", "")
        # 合并到 analysis
        analysis = yaml_settings.get("analysis", {})
        analysis["multimodal"] = mm_cfg
        yaml_settings["analysis"] = analysis
    if any(k in data for k in ("fetch_count", "delay_min", "delay_max", "wechat_targets")):
        cur_wechat = CONFIG.get("collectors", {}).get("wechat", {})
        wechat_cfg = {
            "fetch_count": data.get("fetch_count", cur_wechat.get("fetch_count", 5)),
            "delay_range": [
                data.get("delay_min", cur_wechat.get("delay_range", [8, 12])[0]),
                data.get("delay_max", cur_wechat.get("delay_range", [8, 12])[1]),
            ],
        }
        # targets 只由信源雷达（source_store.sync_wechat_targets）统一管理，配置面板只读展示。
        # 忽略外部传入的 wechat_targets，避免配置面板保存时覆盖雷达写回的公众号目标。
        # 抓取参数（fetch_count/delay_range）仍照常保存。
        yaml_settings["collectors"] = {"wechat": wechat_cfg}
    if any(k in data for k in ("enable_wecom", "enable_console_report")):
        yaml_settings["pusher"] = {
            "enable_wecom": data.get("enable_wecom", True),
            "enable_console_report": data.get("enable_console_report", True),
        }
    if any(k in data for k in ("scheduler_enabled", "run_times", "failure_alert_threshold")):
        yaml_settings["scheduler"] = {
            "enabled": data.get("scheduler_enabled", False),
            "run_times": data.get("run_times", ["08:00"]),
            "failure_alert_threshold": data.get("failure_alert_threshold", 3),
        }
    if "dashboard_page_size" in data or "hidden_nav" in data:
        cur_web = CONFIG.get("web_ui", {})
        web_cfg = {}
        if "dashboard_page_size" in data:
            web_cfg["dashboard_page_size"] = data["dashboard_page_size"]
        else:
            web_cfg["dashboard_page_size"] = cur_web.get("dashboard_page_size", 20)
        if "hidden_nav" in data:
            # 配置面板入口不可隐藏，避免用户把自己锁在门外
            web_cfg["hidden_nav"] = [p for p in (data.get("hidden_nav") or []) if p != "/config"]
        else:
            web_cfg["hidden_nav"] = cur_web.get("hidden_nav", [])
        yaml_settings["web_ui"] = web_cfg

    if yaml_settings:
        _save_settings_yaml(yaml_settings)
        results.append("YAML 配置已保存")

    return {"success": True, "message": "\n".join(results) if results else "无变更"}


@router.post("/test-wecom")
async def test_wecom():
    """测试企业微信推送"""
    try:
        from src.agent.pusher import Pusher
        pusher = Pusher()
        test_items = [{
            "title": "配置测试消息",
            "source": "API 测试",
            "category": "测试",
            "brief": "如果你看到这条消息，说明企业微信 Webhook 配置成功！",
            "link": ""
        }]
        result = pusher.send_wecom(test_items, "2026-01-01")
        return {"success": result, "message": "测试成功" if result else "测试失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}
