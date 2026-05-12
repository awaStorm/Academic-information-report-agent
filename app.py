"""
app.py - 西电校园情报助手 Web UI
基于 Gradio 构建的本地管理界面 (重构版)
"""

import sys
import io

# 禁用输出缓冲 + Windows 编码修复
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stdout.reconfigure(line_buffering=True)
else:
    sys.stdout.reconfigure(line_buffering=True)

import os
import json
import yaml
import shutil
import threading
import gradio as gr
from PIL import Image
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 导入项目模块
from dotenv import load_dotenv
from src.agent.database import (
    get_preferences,
    update_preferences,
    AgentMemory
)
from src.agent.analyzer import run_analysis_flow
from src.agent.pusher import Pusher

from src.utils.config_loader import CONFIG
from agent_core import XidianAgent
from tools_config import TOOLS_METADATA, execute_tool

load_dotenv()


# ============================================================
# 现代化暗色主题 (Linear / Vercel 风格)
# ============================================================

DARK_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.violet,
    secondary_hue=gr.themes.colors.slate,
    neutral_hue=gr.themes.colors.slate,
    font=gr.themes.GoogleFont("Inter"),
    font_mono=gr.themes.GoogleFont("JetBrains Mono"),
).set(
    body_background_fill="#0a0a0f",
    body_background_fill_dark="#0a0a0f",
    block_background_fill="#13131f",
    block_background_fill_dark="#13131f",
    block_border_color="rgba(255,255,255,0.06)",
    block_border_color_dark="rgba(255,255,255,0.06)",
    block_border_width="1px",
    block_radius="14px",
    block_shadow="none",
    button_primary_background_fill="rgba(139,92,246,0.12)",
    button_primary_background_fill_dark="rgba(139,92,246,0.12)",
    button_primary_background_fill_hover="rgba(139,92,246,0.22)",
    button_primary_background_fill_hover_dark="rgba(139,92,246,0.22)",
    button_primary_border_color="rgba(139,92,246,0.4)",
    button_primary_border_color_dark="rgba(139,92,246,0.4)",
    button_primary_text_color="#c4b5fd",
    button_primary_text_color_dark="#c4b5fd",
    button_secondary_background_fill="rgba(255,255,255,0.03)",
    button_secondary_background_fill_dark="rgba(255,255,255,0.03)",
    button_secondary_background_fill_hover="rgba(255,255,255,0.07)",
    button_secondary_background_fill_hover_dark="rgba(255,255,255,0.07)",
    button_secondary_border_color="rgba(255,255,255,0.08)",
    button_secondary_border_color_dark="rgba(255,255,255,0.08)",
    button_secondary_text_color="#a1a1aa",
    button_secondary_text_color_dark="#a1a1aa",
    input_background_fill="rgba(255,255,255,0.03)",
    input_background_fill_dark="rgba(255,255,255,0.03)",
    input_border_color="rgba(255,255,255,0.08)",
    input_border_color_dark="rgba(255,255,255,0.08)",
    input_border_width="1px",
    input_border_width_dark="1px",
    input_radius="10px",
    input_placeholder_color="#52525b",
    slider_color="#8b5cf6",
    checkbox_background_color_selected="#8b5cf6",
    checkbox_border_color_selected="#8b5cf6",
    shadow_drop="none",
    shadow_drop_lg="none",
    shadow_inset="none",
)

# ============================================================
# 自定义 CSS (现代化重构)
# ============================================================

CUSTOM_CSS = """

/* ===== SVG 图标基类 ===== */
.icon {
    display: inline-block;
    width: 16px;
    height: 16px;
    vertical-align: -2px;
    stroke: currentColor;
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}
.icon-lg { width: 20px; height: 20px; vertical-align: -3px; }

/* 按钮内图标对齐 */
.gr-button .icon {
    vertical-align: -3px;
    margin-right: 4px;
}
/* Markdown 标题内图标对齐 */
.gr-markdown h3 .icon {
    vertical-align: -3px;
    margin-right: 6px;
}
/* 聊天气泡内图标对齐 */
.gr-chatbot .message .icon {
    vertical-align: -2px;
    margin-right: 3px;
}
/* details summary 内图标对齐 */
details summary .icon {
    vertical-align: -2px;
    margin-right: 4px;
}

/* ===== 全局基底 ===== */
.gradio-container {
    background: #0a0a0f !important;
    color: #e4e4e7 !important;
    max-width: 1100px !important;
    margin: 0 auto !important;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ===== 隐藏默认 Label 背景 ===== */
.gr-input-label, .gr-dropdown-label, .gr-number-label, .gr-checkbox-label,
label.svelte-1b6s6s, label.svelte-1sgjba4 {
    background: transparent !important;
    border: none !important;
    padding: 0 0 6px 0 !important;
    margin: 0 !important;
    font-weight: 500 !important;
    font-size: 0.8rem !important;
    color: #a1a1aa !important;
    letter-spacing: 0.02em;
}

label span.info { color: #71717a !important; font-size: 0.7rem !important; }

/* ===== 轻量卡片 (替代厚重的 Group) ===== */
.gr-group, fieldset.svelte-1b6s6s {
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 14px !important;
    background: rgba(255,255,255,0.02) !important;
    padding: 20px !important;
    margin-bottom: 0 !important;
    box-shadow: none !important;
    transition: border-color 0.2s ease !important;
}
.gr-group:hover {
    border-color: rgba(255,255,255,0.1) !important;
}

/* ===== 输入框 ===== */
input[type="text"], input[type="number"], input[type="password"],
textarea, select, .gr-dropdown {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 10px !important;
    color: #e4e4e7 !important;
    font-size: 0.85rem !important;
    transition: all 0.2s ease !important;
}
input:focus, textarea:focus, select:focus {
    border-color: rgba(139,92,246,0.5) !important;
    box-shadow: 0 0 0 3px rgba(139,92,246,0.08) !important;
    outline: none !important;
}
input::placeholder, textarea::placeholder { color: #52525b !important; }

/* ===== 按钮 ===== */
.gr-button {
    border-radius: 10px !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.01em;
    transition: all 0.2s ease !important;
}
.gr-button.primary {
    background: rgba(139,92,246,0.12) !important;
    border: 1px solid rgba(139,92,246,0.35) !important;
    color: #c4b5fd !important;
}
.gr-button.primary:hover {
    background: rgba(139,92,246,0.2) !important;
    border-color: rgba(139,92,246,0.55) !important;
    transform: translateY(-1px);
}
.gr-button.secondary {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    color: #a1a1aa !important;
}
.gr-button.secondary:hover {
    background: rgba(255,255,255,0.06) !important;
    border-color: rgba(139,92,246,0.3) !important;
    color: #c4b5fd !important;
}

/* ===== Tab 导航 ===== */
.tabs {
    border-bottom: 1px solid rgba(255,255,255,0.06) !important;
    margin-bottom: 24px !important;
}
.tab-nav {
    gap: 4px !important;
}
.tab-nav button {
    color: #71717a !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 16px !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border-radius: 8px 8px 0 0 !important;
    transition: all 0.2s ease !important;
}
.tab-nav button:hover {
    color: #d4d4d8 !important;
    background: rgba(255,255,255,0.03) !important;
}
.tab-nav button.selected {
    color: #c4b5fd !important;
    border-bottom-color: #8b5cf6 !important;
    background: rgba(139,92,246,0.06) !important;
}

/* ===== Checkbox 芯片化 ===== */
.gr-checkbox {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 10px !important;
    padding: 10px 14px !important;
    transition: all 0.2s ease !important;
}
.gr-checkbox:hover {
    border-color: rgba(139,92,246,0.25) !important;
    background: rgba(139,92,246,0.04) !important;
}
.gr-checkbox input:checked + span {
    color: #c4b5fd !important;
    font-weight: 500 !important;
}

/* ===== 状态标签 ===== */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 500;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
}
.status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 6px rgba(34,197,94,0.4);
}
.status-dot.warn { background: #f59e0b; box-shadow: 0 0 6px rgba(245,158,11,0.4); }
.status-dot.off { background: #ef4444; box-shadow: 0 0 6px rgba(239,68,68,0.4); }

/* ===== 统计卡片 ===== */
.stat-card {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 20px;
    text-align: center;
    transition: all 0.2s ease;
}
.stat-card:hover {
    border-color: rgba(255,255,255,0.1);
    transform: translateY(-2px);
}
.stat-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: #fff;
    line-height: 1;
    margin-bottom: 6px;
}
.stat-label {
    font-size: 0.75rem;
    color: #71717a;
    font-weight: 500;
}

/* ===== 记录列表项 ===== */
.record-item {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 8px;
    transition: all 0.15s ease;
}
.record-item:hover {
    background: rgba(255,255,255,0.04);
    border-color: rgba(255,255,255,0.1);
}

/* ===== 聊天界面优化 ===== */
.gr-chatbot {
    background: rgba(255,255,255,0.015) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 14px !important;
}
.gr-chatbot .message.user {
    background: rgba(139,92,246,0.08) !important;
    border: 1px solid rgba(139,92,246,0.15) !important;
    border-radius: 12px 12px 2px 12px !important;
}
.gr-chatbot .message.bot {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 12px 12px 12px 2px !important;
}
/* 圆形头像预览 (GitHub 风格) */
.avatar-upload img {
    border-radius: 50% !important;
    object-fit: cover !important;
}
.avatar-upload .image-container {
    border-radius: 50% !important;
    border: 2px solid rgba(255,255,255,0.1) !important;
    overflow: hidden !important;
}

/* 报告查看器 — 全宽展开 */
.report-viewer {
    border: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    max-height: none !important;
    overflow: visible !important;
}

/* ===== 滚动条 ===== */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #27272a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3f3f46; }

/* ===== 间距优化 ===== */
.gr-row { gap: 12px !important; }
.gr-column { gap: 12px !important; }
.gr-form { gap: 16px !important; }

/* ===== 分割线 ===== */
hr {
    border-color: rgba(255,255,255,0.06) !important;
    margin: 24px 0 !important;
}

/* ===== Markdown 降噪 ===== */
.gr-markdown h1 {
    color: #fafafa !important;
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
    margin-bottom: 4px !important;
}
.gr-markdown h3 {
    color: #e4e4e7 !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    margin: 0 0 8px 0 !important;
}
.gr-markdown p, .gr-markdown li { color: #a1a1aa !important; font-size: 0.85rem !important; }
.gr-markdown strong { color: #d4d4d8 !important; }
.gr-markdown a { color: #a78bfa !important; }
"""


# ============================================================
# SVG 图标常量 (Lucide 风格 — 16px 线框)
# ============================================================

def _svg(paths: str, cls: str = "icon") -> str:
    """生成内联 SVG HTML"""
    return (f'<svg class="{cls}" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
            f'{paths}</svg>')

ICONS = {
    # Tab 图标
    "settings":    _svg('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
    "dashboard":   _svg('<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>'),
    "target":      _svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
    "file-text":   _svg('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
    "message":     _svg('<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>'),
    # 区块标题图标
    "cpu":         _svg('<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>'),
    "radio":       _svg('<path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/>'),
    "send":        _svg('<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>'),
    "clock":       _svg('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
    "scroll":      _svg('<path d="M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4"/><path d="M19 3H9v7h12V5a2 2 0 0 0-2-2Z"/>'),
    "save":        _svg('<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>'),
    "refresh":     _svg('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'),
    "user-circle": _svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="8" r="4"/><path d="M6.7 19.3C7.8 17.3 9.8 16 12 16s4.2 1.3 5.3 3.3"/>'),
    # 状态图标 (用于 agent_chat_respond)
    "check":       _svg('<path d="M20 6 9 17l-5-5"/>'),
    "x-circle":    _svg('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "loader":      _svg('<path d="M21 12a9 9 0 1 1-6.219-8.56"/>'),
    "wrench":      _svg('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'),
    "sparkles":    _svg('<path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>'),
    "folder":      _svg('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
}

# HTML 内联快捷函数：图标+文字，用于 Tab / 按钮 / 标题
def _icon_text(icon_name: str, text: str) -> str:
    return f'{ICONS[icon_name]} <span style="margin-left:4px">{text}</span>'


# ============================================================
# 配置加载与保存工具 (保持不变)
# ============================================================

def get_project_root():
    return os.path.dirname(os.path.abspath(__file__))

def load_models_config():
    config_path = os.path.join(get_project_root(), "src", "utils", "models_config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"available_models": []}

def _deep_merge(base, override):
    """递归合并字典"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def save_settings_yaml(settings_dict):
    config_path = os.path.join(get_project_root(), "configs", "settings.yaml")
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                current = yaml.safe_load(f) or {}
        else:
            current = {}
        # 递归合并，保证不丢已有字段
        current = _deep_merge(current, settings_dict)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(current, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception as e:
        return str(e)

def save_env_var(key, value):
    env_path = os.path.join(get_project_root(), ".env")
    try:
        env_vars = {}
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
        env_vars[key] = value
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in env_vars.items():
                f.write(f"{k}={v}\n")
        os.environ[key] = value
        return True
    except Exception as e:
        return str(e)


# ============================================================
# 定时任务管理器 (保持不变)
# ============================================================

class SchedulerManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.failure_count = 0
        self.failure_threshold = CONFIG.get("scheduler", {}).get("failure_alert_threshold", 3)
        self.is_running = False
        self.last_run_time = None
        self.last_run_result = None
        self.scheduler.start()
        self.is_running = True

    def _save_run_log(self, success, message, pushed_count=0):
        try:
            memory = AgentMemory()
            memory.save_pushed_record(
                title=f"定时任务 - {'成功' if success else '失败'}",
                platform="system",
                category="系统日志",
                brief=f"{message} | 推送: {pushed_count} 条",
                link="",
                status="log"
            )
        except Exception as e:
            print(f"保存执行日志失败: {e}")

    def _send_failure_alert(self, error_msg):
        try:
            pusher = Pusher()
            alert_items = [{
                "title": "西电情报助手定时任务告警",
                "source": "系统监控",
                "category": "告警",
                "brief": f"连续失败 {self.failure_count} 次\n错误信息: {error_msg[:100]}",
                "link": ""
            }]
            pusher.send_wecom(alert_items, datetime.now().strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"发送告警失败: {e}")

    def run_scheduled_task(self):
        print(f"[Scheduler] 定时任务开始执行 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.last_run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            result = run_analysis_flow()
            # run_analysis_flow 返回 bool
            success = bool(result)
            if success:
                self.failure_count = 0
                message = "执行成功"
                self.last_run_result = "成功"
            else:
                self.failure_count += 1
                message = "执行异常"
                self.last_run_result = message
                if self.failure_count >= self.failure_threshold:
                    self._send_failure_alert(message)
                    print(f"[Scheduler] 已发送失败告警（连续失败 {self.failure_count} 次）")
            self._save_run_log(success, message)
            print(f"[Scheduler] 定时任务执行完成 | {message}")
        except Exception as e:
            self.failure_count += 1
            error_msg = str(e)
            self.last_run_result = f"执行失败: {error_msg[:50]}"
            self._save_run_log(False, f"异常: {error_msg}")
            if self.failure_count >= self.failure_threshold:
                self._send_failure_alert(error_msg)
            print(f"[Scheduler] 定时任务执行异常: {error_msg}")

    def update_schedule(self, enabled, run_times):
        self.scheduler.remove_all_jobs()
        if not enabled:
            print("[Scheduler] 定时任务已关闭")
            return
        for time_str in run_times:
            try:
                hour, minute = map(int, time_str.strip().split(":"))
                job_id = f"daily_report_{time_str.replace(':', '')}"
                self.scheduler.add_job(
                    self.run_scheduled_task,
                    CronTrigger(hour=hour, minute=minute),
                    id=job_id,
                    replace_existing=True
                )
                print(f"[Scheduler] 已添加定时任务: 每天 {hour:02d}:{minute:02d}")
            except Exception as e:
                print(f"[Scheduler] 时间格式错误: {time_str} - {e}")

    def get_status(self):
        jobs = self.scheduler.get_jobs()
        job_times = [j.id.replace("daily_report_", "") for j in jobs if j.id.startswith("daily_report_")]
        return {
            "enabled": len(jobs) > 0,
            "run_times": job_times,
            "is_running": self.is_running,
            "failure_count": self.failure_count,
            "last_run_time": self.last_run_time,
            "last_run_result": self.last_run_result
        }

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_running = False
            print("[Scheduler] 调度器已关闭")


scheduler_manager = None

def get_scheduler():
    global scheduler_manager
    if scheduler_manager is None:
        scheduler_manager = SchedulerManager()
    return scheduler_manager


# ============================================================
# 头像管理
# ============================================================

AVATAR_DIR = os.path.join(os.path.dirname(__file__), "assets", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

def _avatar_path(role: str) -> str | None:
    """获取已保存的头像路径，不存在则返回 None"""
    for ext in ("png", "jpg", "jpeg", "webp", "gif"):
        p = os.path.join(AVATAR_DIR, f"{role}.{ext}")
        if os.path.exists(p):
            return p
    return None

def _save_avatar(src_path: str, role: str):
    """将上传图片居中裁剪为正方形，压缩到 200x200 保存"""
    dst = os.path.join(AVATAR_DIR, f"{role}.png")
    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((200, 200), Image.LANCZOS)
        img.save(dst, "PNG")
    return dst

def apply_avatar(user_img, bot_img):
    """应用头像：保存图片 + 更新 chatbot"""
    msgs = []
    user_avatar = _avatar_path("user")
    bot_avatar = _avatar_path("bot")

    if user_img:
        user_avatar = _save_avatar(user_img, "user")
        msgs.append("用户头像已更新")
    if bot_img:
        bot_avatar = _save_avatar(bot_img, "bot")
        msgs.append("Bot 头像已更新")

    return (
        gr.update(avatar_images=(user_avatar, bot_avatar)),
        gr.update(value=None),
        gr.update(value=None),
        "  ·  ".join(msgs) if msgs else "未选择图片",
    )

def clear_avatar():
    """重置头像为默认"""
    for role in ("user", "bot"):
        old = _avatar_path(role)
        if old:
            os.remove(old)
    return (
        gr.update(avatar_images=(None, "🤖")),
        gr.update(value=None),
        gr.update(value=None),
        "头像已重置",
    )

# 配置面板逻辑 (保持不变)
# ============================================================

def load_current_config():
    return {
        "llm_api_key": os.getenv("LLM_API_KEY", ""),
        "llm_base_url": os.getenv("LLM_BASE_URL", ""),
        "llm_model": os.getenv("LLM_MODEL", CONFIG["analysis"]["model_name"]),
        "temperature": CONFIG["analysis"].get("temperature", 0.1),
        "max_tokens": CONFIG["analysis"].get("max_tokens", 20000),
        "fetch_count": CONFIG["collectors"]["wechat"].get("fetch_count", 5),
        "delay_range": CONFIG["collectors"]["wechat"].get("delay_range", [5, 8]),
        "wechat_targets": CONFIG["collectors"]["wechat"].get("targets", []),
        "wecom_webhook": os.getenv("WECOM_WEBHOOK", ""),
        "serverchan_key": os.getenv("SERVERCHAN_SENDKEY", ""),
        "enable_wecom": CONFIG["pusher"].get("enable_wecom", True),
        "enable_console_report": CONFIG["pusher"].get("enable_console_report", True),
        "scheduler_enabled": CONFIG["scheduler"].get("enabled", False),
        "run_times": CONFIG["scheduler"].get("run_times", ["08:00"]),
        "failure_alert_threshold": CONFIG["scheduler"].get("failure_alert_threshold", 3),
        "dashboard_page_size": CONFIG["web_ui"].get("dashboard_page_size", 20),
    }

def save_all_config(
    llm_api_key, llm_base_url, llm_model,
    temperature, max_tokens,
    wecom_webhook, serverchan_key,
    fetch_count, delay_min, delay_max,
    wechat_targets,
    enable_wecom, enable_console_report,
    scheduler_enabled, run_times,
    failure_alert_threshold,
    dashboard_page_size
):
    global _agent_instance
    results = []

    if llm_api_key:
        result = save_env_var("LLM_API_KEY", llm_api_key)
        results.append("API Key 已保存" if result is True else f"API Key 保存失败: {result}")

    if llm_base_url:
        result = save_env_var("LLM_BASE_URL", llm_base_url)
        results.append("Base URL 已保存" if result is True else f"Base URL 保存失败: {result}")

    if llm_model:
        result = save_env_var("LLM_MODEL", llm_model)
        if result is True:
            CONFIG["analysis"]["model_name"] = llm_model
        else:
            results.append(f"模型配置保存失败: {result}")

    # 保存 analysis 块 (model_name + temperature + max_tokens)
    result = save_settings_yaml({
        "analysis": {
            "model_name": llm_model or CONFIG["analysis"].get("model_name", ""),
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
    })
    results.append("LLM 配置已保存" if result is True else f"LLM 配置保存失败: {result}")

    if llm_api_key or llm_base_url or llm_model:
        _agent_instance = None
        results.append("Agent 已重建，新配置将在下次对话时生效")

    if wecom_webhook:
        result = save_env_var("WECOM_WEBHOOK", wecom_webhook)
        results.append("企业微信 Webhook 已保存" if result is True else f"Webhook 保存失败: {result}")

    if serverchan_key:
        result = save_env_var("SERVERCHAN_SENDKEY", serverchan_key)
        results.append("Server 酱 SendKey 已保存" if result is True else f"SendKey 保存失败: {result}")

    # 保存采集参数 + 公众号关注列表
    targets_list = [t.strip() for t in wechat_targets.split(",") if t.strip()]
    result = save_settings_yaml({
        "collectors": {
            "wechat": {
                "fetch_count": int(fetch_count),
                "delay_range": [int(delay_min), int(delay_max)],
                "targets": targets_list,
            }
        }
    })
    results.append("采集参数已保存" if result is True else f"采集参数保存失败: {result}")

    # 保存推送设置
    result = save_settings_yaml({
        "pusher": {
            "enable_wecom": enable_wecom,
            "enable_console_report": enable_console_report,
        }
    })
    results.append("推送设置已保存" if result is True else f"推送设置保存失败: {result}")

    # 保存定时任务
    run_times_list = [t.strip() for t in run_times.split(",") if t.strip()]
    result = save_settings_yaml({
        "scheduler": {
            "enabled": scheduler_enabled,
            "run_times": run_times_list,
            "failure_alert_threshold": int(failure_alert_threshold),
        }
    })
    if result is True:
        try:
            scheduler = get_scheduler()
            scheduler.update_schedule(scheduler_enabled, run_times_list)
        except Exception as e:
            results.append(f"调度器更新异常: {e}")
        if scheduler_enabled:
            results.append(f"定时任务已开启: {', '.join(run_times_list)}")
        else:
            results.append("定时任务已关闭")
    else:
        results.append(f"定时任务配置保存失败: {result}")

    # 保存 Web UI 设置
    result = save_settings_yaml({
        "web_ui": {
            "dashboard_page_size": int(dashboard_page_size),
        }
    })
    results.append("界面设置已保存" if result is True else f"界面设置保存失败: {result}")

    return "\n".join(results)

def test_wecom_push():
    try:
        pusher = Pusher()
        test_items = [{
            "title": "配置测试消息",
            "source": "Web UI 测试",
            "category": "测试",
            "brief": "如果你看到这条消息，说明企业微信 Webhook 配置成功！",
            "link": ""
        }]
        result = pusher.send_wecom(test_items, datetime.now().strftime("%Y-%m-%d"))
        return result.get("message", str(result))
    except Exception as e:
        return f"测试失败: {str(e)}"

def test_serverchan_push():
    try:
        pusher = Pusher()
        test_items = [{
            "title": "配置测试消息",
            "source": "Web UI 测试",
            "brief": "如果你看到这条消息，说明 Server 酱配置成功！"
        }]
        result = pusher.send_serverchan(test_items, datetime.now().strftime("%Y-%m-%d"))
        return result.get("message", str(result))
    except Exception as e:
        return f"测试失败: {str(e)}"


# ============================================================
# 情报仪表盘逻辑 (保持不变)
# ============================================================

def load_intelligence_records(start_date, end_date, platform_filter):
    try:
        platform_map = {"全部": None, "超星": "chaoxing", "微信": "wechat"}
        platform = platform_map.get(platform_filter, None)
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        memory = AgentMemory()
        records = memory.get_pushed_records_by_date_range(start_date, end_date, platform, limit=20)

        if not records:
            return "<div style='text-align:center;color:#71717a;padding:40px 0;'>暂无推送记录</div>"

        lines = []
        for r in records:
            platform_tag = "WeChat" if r["platform"] == "wechat" else "ChaoXing"
            status_icon = f'<span class="status-dot"></span>' if r["status"] == "pushed" else f'<span class="status-dot warn"></span>'
            cat_color = {
                "讲座活动": "#8b5cf6", "竞赛信息": "#06b6d4", "考试安排": "#f59e0b",
                "放假通知": "#ef4444", "课程调整": "#10b981", "社团活动": "#ec4899",
                "体育赛事": "#3b82f6", "其他动态": "#71717a", "系统日志": "#52525b"
            }.get(r.get("category", "其他"), "#71717a")

            lines.append(
                f"<div class='record-item'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>"
                f"<span style='font-weight:600;color:#e4e4e7;font-size:0.9rem;'>{r['title']}</span>"
                f"<span style='font-size:0.7rem;color:#71717a;'>{r['push_time']}</span>"
                f"</div>"
                f"<div style='display:flex;gap:8px;align-items:center;margin-bottom:6px;'>"
                f"<span style='background:rgba(255,255,255,0.05);padding:2px 8px;border-radius:4px;font-size:0.7rem;color:#a1a1aa;'>{platform_tag}</span>"
                f"<span style='background:{cat_color}15;padding:2px 8px;border-radius:4px;font-size:0.7rem;color:{cat_color};'>{r.get('category', '其他')}</span>"
                f"<span style='font-size:0.8rem;'>{status_icon}</span>"
                f"</div>"
                f"<div style='color:#a1a1aa;font-size:0.8rem;line-height:1.5;'>{r.get('brief', '无')[:120]}...</div>"
                f"</div>"
            )
        return "\n".join(lines)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"加载失败: {str(e)}"

def get_record_count(start_date, end_date, platform_filter):
    try:
        platform_map = {"全部": None, "超星": "chaoxing", "微信": "wechat"}
        platform = platform_map.get(platform_filter, None)
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        memory = AgentMemory()
        records = memory.get_pushed_records_by_date_range(start_date, end_date, platform)
        return f"共 **{len(records)}** 条记录"
    except Exception:
        return "无法获取统计"

def get_dashboard_stats():
    """获取仪表盘统计数据"""
    try:
        memory = AgentMemory()
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        today_records = memory.get_pushed_records_by_date_range(today, today, None)
        week_records = memory.get_pushed_records_by_date_range(week_ago, today, None)

        wechat_count = len([r for r in week_records if r["platform"] == "wechat"])
        chaoxing_count = len([r for r in week_records if r["platform"] == "chaoxing"])

        return {
            "today": len(today_records),
            "week": len(week_records),
            "wechat": wechat_count,
            "chaoxing": chaoxing_count
        }
    except Exception:
        return {"today": 0, "week": 0, "wechat": 0, "chaoxing": 0}


# ============================================================
# 偏好设置逻辑 (保持不变)
# ============================================================

ALL_CATEGORIES = [
    "讲座活动", "竞赛信息", "考试安排", "放假通知",
    "课程调整", "社团活动", "体育赛事", "其他动态"
]

def load_current_preferences():
    try:
        result = get_preferences()
        categories = result.get("categories", [])
        return tuple(cat in categories for cat in ALL_CATEGORIES)
    except Exception as e:
        print(f"[WARNING] 加载偏好失败: {e}")
        return tuple(False for _ in ALL_CATEGORIES)

def save_preferences_from_ui(
    讲座活动, 竞赛信息, 考试安排, 放假通知,
    课程调整, 社团活动, 体育赛事, 其他动态
):
    selected = [
        cat for cat, is_selected in {
            "讲座活动": 讲座活动, "竞赛信息": 竞赛信息,
            "考试安排": 考试安排, "放假通知": 放假通知,
            "课程调整": 课程调整, "社团活动": 社团活动,
            "体育赛事": 体育赛事, "其他动态": 其他动态
        }.items() if is_selected
    ]
    try:
        result = update_preferences(selected)
        if result.get("success"):
            return f"偏好已保存\n当前偏好: {', '.join(selected) if selected else '全部类别'}"
        return f"保存失败: {result.get('message', '未知错误')}"
    except Exception as e:
        return f"保存异常: {str(e)}"


# ============================================================
# Agent 聊天模块 (保持不变)
# ============================================================

_agent_instance = None

def _get_agent() -> XidianAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = XidianAgent()
    return _agent_instance

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def agent_chat_respond(user_message: str, chat_history: list):
    if not user_message.strip():
        yield chat_history
        return

    agent = _get_agent()
    chat_history = chat_history + [{"role": "user", "content": user_message}]

    original_console = CONFIG['pusher']['enable_console_report']
    CONFIG['pusher']['enable_console_report'] = False
    original_stdout = sys.stdout
    captured_logs = []

    class ChatCapture(io.StringIO):
        def write(self, text):
            if text and text.strip():
                captured_logs.append(text.rstrip())
            return super().write(text)

    capture = ChatCapture()

    try:
        sys.stdout = capture
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timed_input = f"【当前系统时间：{current_time_str}】\n用户指令：{user_message}"
        agent.history.append({"role": "user", "content": timed_input})

        status_lines = []
        all_responses = []

        status_lines.append(f"{ICONS['loader']} [{_ts()}] 收到指令，正在思考...")
        current_status = "\n".join(status_lines)
        chat_history_with_status = chat_history + [{"role": "assistant", "content": current_status}]
        yield chat_history_with_status

        while True:
            response = agent.client.chat.completions.create(
                model=agent.model,
                messages=agent.history,
                tools=TOOLS_METADATA,
                tool_choice="auto",
                temperature=agent.temperature,
                max_tokens=agent.max_tokens
            )

            response_msg = response.choices[0].message
            agent.history.append(response_msg)

            if response_msg.content:
                all_responses.append(response_msg.content)

            if not response_msg.tool_calls:
                break

            for tool_call in response_msg.tool_calls:
                function_name = tool_call.function.name
                args_str = tool_call.function.arguments
                args = json.loads(args_str) if args_str else {}

                tool_display = _friendly_tool_name(function_name)
                status_lines.append(f"{ICONS['wrench']} [{_ts()}] 调用工具: **{tool_display}**")
                current_status = "\n".join(status_lines)
                chat_history_with_status = chat_history + [{"role": "assistant", "content": current_status}]
                yield chat_history_with_status

                progress_lines_ref = [0]

                def _make_scraper_callback():
                    def callback(idx, total, name, new_count):
                        if progress_lines_ref[0] > 0:
                            status_lines.pop()
                        status_lines.append(
                            f"{ICONS['radio']} [{_ts()}] 抓取公众号 ({idx}/{total}): {name}... {ICONS['check']} 累计新增 {new_count} 条"
                        )
                        progress_lines_ref[0] += 1
                    return callback

                def _make_parser_callback():
                    def callback(idx, total, title):
                        if progress_lines_ref[0] > 0:
                            status_lines.pop()
                        short_title = title[:20] + "..." if len(title) > 20 else title
                        status_lines.append(
                            f"{ICONS['file-text']} [{_ts()}] 解析文章 ({idx}/{total}): {short_title}"
                        )
                        progress_lines_ref[0] += 1
                    return callback

                if function_name == "run_wechat_scraper":
                    args["progress_callback"] = _make_scraper_callback()
                elif function_name == "parse_wechat_content":
                    args["progress_callback"] = _make_parser_callback()

                result = execute_tool(function_name, **args)

                success = result.get("success", False) if isinstance(result, dict) else True
                result_icon = f"{ICONS['check']}" if success else f"{ICONS['x-circle']}"
                result_summary = _summarize_tool_result(function_name, result)
                status_lines.append(f"{result_icon} [{_ts()}] {tool_display} → {result_summary}")

                current_status = "\n".join(status_lines)
                chat_history_with_status = chat_history + [{"role": "assistant", "content": current_status}]
                yield chat_history_with_status

                agent.history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })

        reply_parts = []
        if all_responses:
            main_reply = "\n".join(all_responses)
            reply_parts.append(main_reply)

        if captured_logs:
            log_block = "\n".join(f"- {l}" for l in captured_logs)
            reply_parts.append(
                f"\n\n<details><summary>{ICONS['scroll']} 工具调用日志（{len(captured_logs)} 条）</summary>\n\n{log_block}\n\n</details>"
            )

        status_lines.append(f"{ICONS['sparkles']} [{_ts()}] 全部完成！")
        final_status = "\n".join(status_lines)
        final_reply = final_status + "\n\n---\n\n" + ("\n".join(reply_parts) if reply_parts else "（Agent 无文字回复）")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        status_lines.append(f"{ICONS['x-circle']} [{_ts()}] 执行异常: `{type(e).__name__}: {e}`")
        final_status = "\n".join(status_lines)
        final_reply = f"{final_status}\n\n---\n\n**Agent 执行异常**: `{type(e).__name__}: {e}`\n\n请检查 LLM API Key 和网络连接。\n\n```\n{tb[-300:]}\n```"

    finally:
        CONFIG['pusher']['enable_console_report'] = original_console
        sys.stdout = original_stdout

    chat_history = chat_history + [{"role": "assistant", "content": final_reply}]
    yield chat_history


def _friendly_tool_name(name: str) -> str:
    name_map = {
        "harvest_chaoxing_session": "超星扫码登录",
        "harvest_wechat_session": "微信扫码登录",
        "run_chaoxing_scraper": "抓取超星通知",
        "run_wechat_scraper": "抓取微信公众号",
        "process_raw_data": "清洗超星数据",
        "refine_data_for_ai": "字段对齐",
        "parse_wechat_content": "解析微信正文",
        "merge_all_intelligence": "合流情报数据",
        "check_intelligence_memory": "情报去重检查",
        "send_final_report": "推送情报报告",
        "analyze_and_push_intelligence": "AI 分析与推送",
    }
    return name_map.get(name, name)

def _summarize_tool_result(name: str, result) -> str:
    if not isinstance(result, dict):
        return str(result)[:80]
    success = result.get("success", False)
    if not success:
        error_type = result.get("error_type", "UNKNOWN")
        msg = result.get("message", "")[:50]
        return f"失败 [{error_type}]: {msg}"
    if name == "run_chaoxing_scraper":
        count = result.get("count", 0)
        return f"抓取 {count} 条通知"
    elif name == "run_wechat_scraper":
        count = result.get("count", 0)
        scanned = result.get("total_scanned", 0)
        return f"发现 {count} 条新增 (共扫描 {scanned} 条)"
    elif name == "parse_wechat_content":
        count = result.get("count", 0)
        return f"解析 {count} 篇正文"
    elif name == "process_raw_data":
        count = result.get("count", 0)
        return f"清洗 {count} 条数据"
    elif name == "refine_data_for_ai":
        count = result.get("count", 0)
        return f"对齐 {count} 条数据"
    elif name == "merge_all_intelligence":
        count = result.get("count", 0)
        return f"合流 {count} 条情报"
    elif name == "check_intelligence_memory":
        return "去重检查完成"
    elif name == "send_final_report":
        msg = result.get("message", "已推送")
        return msg[:60]
    elif name == "analyze_and_push_intelligence":
        pushed = result.get("pushed_count", 0)
        status = result.get("status", "")
        if status == "no_new_data":
            return "无新增情报"
        return f"推送 {pushed} 条情报"
    elif name in ("harvest_chaoxing_session", "harvest_wechat_session"):
        msg = result.get("message", "登录完成")
        return msg[:60]
    else:
        msg = result.get("message", "")[:60]
        return msg if msg else "完成"

def reset_agent_chat():
    global _agent_instance
    _agent_instance = None
    return [], "**Agent 会话已重置**"

# --- 报告查看相关 ---

def list_report_files() -> list[str]:
    """返回 reports 目录下所有 .md 报告文件名（按修改时间倒序）"""
    report_dir = os.path.join(os.path.dirname(__file__), "reports")
    if not os.path.exists(report_dir):
        return []
    files = [f for f in os.listdir(report_dir) if f.endswith(".md")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(report_dir, f)), reverse=True)
    return files

def load_report_content(filename: str) -> str:
    """读取指定报告文件内容，返回 Markdown 文本"""
    if not filename:
        return "请选择一份报告"
    report_path = os.path.join(os.path.dirname(__file__), "reports", filename)
    if not os.path.exists(report_path):
        return f"文件不存在: {filename}"
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取失败: {e}"

def refresh_report_list():
    """刷新报告列表下拉框"""
    files = list_report_files()
    if not files:
        return gr.update(choices=[], value=None), "reports 目录下暂无报告"
    return gr.update(choices=files, value=files[0]), f"共 {len(files)} 份报告"

def on_report_selected(filename):
    """选择报告后加载内容"""
    content = load_report_content(filename)
    return content

def get_scheduler_status():
    try:
        scheduler = get_scheduler()
        status = scheduler.get_status()
        if status["enabled"]:
            times_str = ", ".join(status["run_times"]) if status["run_times"] else "未设置"
            status_icon = "RUNNING" if status["is_running"] else "STOPPED"
            failure_info = f" | 连续失败 {status['failure_count']} 次" if status["failure_count"] > 0 else ""
            last_run = f"\n- 上次执行: {status['last_run_time']}" if status["last_run_time"] else ""
            last_result = f"\n- 上次结果: {status['last_run_result']}" if status["last_run_result"] else ""
            return (f"**状态**: `{status_icon}`\n"
                    f"**运行时间**: {times_str}{failure_info}{last_run}{last_result}")
        else:
            return "**状态**: `DISABLED`"
    except Exception as e:
        return f"**状态**: 获取失败 ({str(e)[:50]})"

def get_scheduler_logs():
    try:
        memory = AgentMemory()
        records = memory.get_pushed_records_by_date_range(
            (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d"),
            platform=None
        )
        logs = [r for r in records if r.get("category") == "系统日志"]
        if not logs:
            return "暂无执行日志"
        lines = []
        for log in logs[:10]:
            lines.append(f"`{log['push_time']}` {log.get('brief', '无描述')}")
        return "\n".join(lines) if lines else "暂无执行日志"
    except Exception as e:
        return f"获取日志失败: {str(e)}"


# ============================================================
# 构建 Gradio 界面 (重构版)
# ============================================================

def build_ui():
    config = load_current_config()
    try:
        prefs_result = get_preferences()
        initial_categories = prefs_result.get("categories", [])
    except Exception:
        initial_categories = []

    # 预加载仪表盘统计
    stats = get_dashboard_stats()

    with gr.Blocks(title="西电校园情报助手") as app:

        # ===== 顶部标题栏 =====
        gr.Markdown(
            "# 西电校园情报助手"
        )
        gr.Markdown(
            "基于 AI 的校园情报采集、分析与推送系统"
        )

        with gr.Tabs():

            # ==================== Tab 1: 配置面板 ====================
            with gr.TabItem("配置面板"):

                # -- 顶部状态栏 --
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.HTML(
                            f"<div class='stat-card'>"
                            f"<div class='stat-value' style='color:#8b5cf6;'>{stats['today']}</div>"
                            f"<div class='stat-label'>今日推送</div></div>"
                        )
                    with gr.Column(scale=1):
                        gr.HTML(
                            f"<div class='stat-card'>"
                            f"<div class='stat-value' style='color:#06b6d4;'>{stats['week']}</div>"
                            f"<div class='stat-label'>本周推送</div></div>"
                        )
                    with gr.Column(scale=1):
                        gr.HTML(
                            f"<div class='stat-card'>"
                            f"<div class='stat-value' style='color:#22c55e;'>{stats['wechat']}</div>"
                            f"<div class='stat-label'>微信情报</div></div>"
                        )
                    with gr.Column(scale=1):
                        gr.HTML(
                            f"<div class='stat-card'>"
                            f"<div class='stat-value' style='color:#f59e0b;'>{stats['chaoxing']}</div>"
                            f"<div class='stat-label'>超星通知</div></div>"
                        )

                gr.Markdown("---")

                # -- 两栏配置区 --
                with gr.Row():
                    # 左栏：模型 + 采集
                    with gr.Column(scale=1):
                        gr.Markdown(f"### {_icon_text('cpu', 'LLM 模型')}")
                        llm_api_key = gr.Textbox(
                            label="API Key",
                            value=config["llm_api_key"],
                            placeholder="sk-...",
                            type="password",
                        )
                        with gr.Row():
                            llm_base_url = gr.Textbox(
                                label="Base URL",
                                value=config["llm_base_url"],
                                placeholder="https://api.openai.com/v1",
                                scale=2,
                            )
                            llm_model = gr.Textbox(
                                label="模型",
                                value=config["llm_model"],
                                placeholder="gpt-4o / deepseek-chat",
                                scale=1,
                            )
                        with gr.Row():
                            temperature = gr.Number(
                                label="Temperature",
                                value=config["temperature"],
                                minimum=0, maximum=2, step=0.1,
                            )
                            max_tokens = gr.Number(
                                label="Max Tokens",
                                value=config["max_tokens"],
                                minimum=100, maximum=128000, step=1000,
                            )

                        gr.Markdown(f"### {_icon_text('radio', '采集参数')}")
                        with gr.Row():
                            fetch_count = gr.Number(
                                label="每次抓取",
                                value=config["fetch_count"],
                                minimum=1, maximum=20, step=1,
                            )
                            delay_min = gr.Number(
                                label="最小间隔(秒)",
                                value=config["delay_range"][0],
                                minimum=1, maximum=30, step=1,
                            )
                            delay_max = gr.Number(
                                label="最大间隔(秒)",
                                value=config["delay_range"][1],
                                minimum=1, maximum=60, step=1,
                            )
                        wechat_targets = gr.Textbox(
                            label="公众号关注列表",
                            value=",".join(config["wechat_targets"]),
                            placeholder="西小电星球, 西电社团, 西电体育",
                        )
                        gr.Markdown(
                            "<span style='color:#71717a;font-size:0.75rem;'>多个公众号用英文逗号分隔</span>"
                        )

                    # 右栏：推送 + 定时
                    with gr.Column(scale=1):
                        gr.Markdown(f"### {_icon_text('send', '推送渠道')}")
                        wecom_input = gr.Textbox(
                            label="企业微信 Webhook",
                            value=config["wecom_webhook"],
                            placeholder="https://qyapi.weixin.qq.com/...",
                            type="password",
                        )
                        serverchan_input = gr.Textbox(
                            label="Server酱 SendKey",
                            value=config["serverchan_key"],
                            placeholder="输入 SendKey",
                            type="password",
                        )
                        enable_wecom = gr.Checkbox(
                            label="启用企业微信推送",
                            value=config["enable_wecom"],
                        )
                        enable_console_report = gr.Checkbox(
                            label="启用控制台报告输出",
                            value=config["enable_console_report"],
                        )
                        with gr.Row():
                            wecom_test_btn = gr.Button("测试企业微信", size="sm")
                            wecom_test_result = gr.Textbox(
                                show_label=False, interactive=False, container=False
                            )
                            serverchan_test_btn = gr.Button("测试 Server酱", size="sm")
                            serverchan_test_result = gr.Textbox(
                                show_label=False, interactive=False, container=False
                            )

                        gr.Markdown(f"### {_icon_text('clock', '定时任务')}")
                        scheduler_enabled = gr.Checkbox(
                            label="开启每日定时推送",
                            value=config["scheduler_enabled"],
                        )
                        run_times_input = gr.Textbox(
                            label="运行时间",
                            value=",".join(config["run_times"]),
                            placeholder="12:00, 22:00",
                        )
                        failure_alert_threshold = gr.Number(
                            label="连续失败告警阈值",
                            value=config["failure_alert_threshold"],
                            minimum=1, maximum=20, step=1,
                        )
                        with gr.Row():
                            refresh_scheduler_btn = gr.Button("刷新状态", size="sm")
                            scheduler_status = gr.Markdown("**状态**: --")

                gr.Markdown("---")

                # -- 高级设置 --
                with gr.Row():
                    with gr.Column(scale=1):
                        dashboard_page_size = gr.Number(
                            label="仪表盘每页记录数",
                            value=config["dashboard_page_size"],
                            minimum=5, maximum=100, step=5,
                        )

                gr.Markdown("---")

                # -- 执行日志 --
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown(f"### {_icon_text('scroll', '执行日志')}")
                        log_btn = gr.Button("查看最近日志", size="sm")
                    with gr.Column(scale=3):
                        log_display = gr.Textbox(
                            label="", interactive=False, lines=4, show_label=False,
                            placeholder="点击上方按钮查看日志..."
                        )

                gr.Markdown("---")

                # -- 保存按钮 --
                with gr.Row():
                    save_btn = gr.Button("保存所有配置", variant="primary", size="lg")
                save_result = gr.Textbox(
                    label="", interactive=False, lines=3, show_label=False
                )

                # 事件绑定
                save_btn.click(
                    save_all_config,
                    inputs=[
                        llm_api_key, llm_base_url, llm_model,
                        temperature, max_tokens,
                        wecom_input, serverchan_input,
                        fetch_count, delay_min, delay_max,
                        wechat_targets,
                        enable_wecom, enable_console_report,
                        scheduler_enabled, run_times_input,
                        failure_alert_threshold,
                        dashboard_page_size
                    ],
                    outputs=save_result
                )
                wecom_test_btn.click(test_wecom_push, outputs=wecom_test_result)
                serverchan_test_btn.click(test_serverchan_push, outputs=serverchan_test_result)
                refresh_scheduler_btn.click(get_scheduler_status, outputs=scheduler_status)
                log_btn.click(get_scheduler_logs, outputs=log_display)

            # ==================== Tab 2: 情报仪表盘 ====================
            with gr.TabItem("情报仪表盘"):
                gr.Markdown("### 情报推送记录")

                with gr.Row():
                    with gr.Column(scale=3):
                        with gr.Row():
                            start_date = gr.Textbox(
                                label="开始日期",
                                placeholder="YYYY-MM-DD",
                                value=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                            )
                            end_date = gr.Textbox(
                                label="结束日期",
                                placeholder="YYYY-MM-DD",
                                value=datetime.now().strftime("%Y-%m-%d"),
                            )
                            platform_filter = gr.Dropdown(
                                choices=["全部", "超星", "微信"],
                                value="全部",
                                label="平台",
                            )
                    with gr.Column(scale=1):
                        refresh_btn = gr.Button("刷新记录", variant="primary")
                        count_display = gr.Markdown("**记录数**: --")

                records_display = gr.HTML(
                    "<div style='text-align:center;color:#71717a;padding:40px 0;'>点击「刷新记录」加载推送历史...</div>"
                )

                refresh_btn.click(
                    load_intelligence_records,
                    inputs=[start_date, end_date, platform_filter],
                    outputs=records_display
                )
                refresh_btn.click(
                    get_record_count,
                    inputs=[start_date, end_date, platform_filter],
                    outputs=count_display
                )

            # ==================== Tab 3: 偏好设置 ====================
            with gr.TabItem("偏好设置"):
                gr.Markdown(
                    "### 选择感兴趣的类别"
                )
                gr.Markdown(
                    "勾选的类别将在情报分析时获得更高优先级"
                )

                preferences = {}
                with gr.Row():
                    for cat in ALL_CATEGORIES[:4]:
                        preferences[cat] = gr.Checkbox(
                            label=cat,
                            value=(cat in initial_categories),
                        )
                with gr.Row():
                    for cat in ALL_CATEGORIES[4:]:
                        preferences[cat] = gr.Checkbox(
                            label=cat,
                            value=(cat in initial_categories),
                        )

                with gr.Row():
                    save_prefs_btn = gr.Button("保存偏好", variant="primary")
                prefs_result = gr.Textbox(
                    label="", interactive=False, show_label=False
                )

                save_prefs_btn.click(
                    save_preferences_from_ui,
                    inputs=list(preferences.values()),
                    outputs=prefs_result
                )

            # ==================== Tab 4: 情报报告 ====================
            with gr.TabItem("情报报告"):
                gr.Markdown("### 历史情报报告")
                gr.Markdown("查看 AI 生成的每日情报分析报告。即使推送失败，报告也会保存在本地。")

                with gr.Row():
                    _init_files = list_report_files()
                    _init_val = _init_files[0] if _init_files else None
                    report_selector = gr.Dropdown(
                        choices=_init_files,
                        value=_init_val,
                        label="选择报告",
                        scale=4,
                    )
                    report_refresh_btn = gr.Button("刷新列表", scale=1)
                report_status = gr.Markdown(
                    f"共 {len(_init_files)} 份报告" if _init_files else "reports 目录下暂无报告"
                )

                # 初始加载选中报告内容
                _init_content = load_report_content(_init_val) if _init_val else ""
                report_viewer = gr.Markdown(
                    _init_content,
                    elem_classes=["report-viewer"],
                )

                # 事件绑定
                report_selector.change(
                    on_report_selected,
                    inputs=[report_selector],
                    outputs=[report_viewer],
                )
                report_refresh_btn.click(
                    refresh_report_list,
                    outputs=[report_selector, report_status],
                ).then(
                    on_report_selected,
                    inputs=[report_selector],
                    outputs=[report_viewer],
                )

            # ==================== Tab 5: Agent 对话 ====================
            with gr.TabItem("Agent 对话"):
                gr.Markdown(
                    "### 智能对话助手"
                )
                gr.Markdown(
                    "与 AI Agent 对话，自主执行采集、分析、推送等操作。支持自然语言指令。"
                )

                # 加载已保存的头像
                _saved_user = _avatar_path("user")
                _saved_bot = _avatar_path("bot")
                chatbot = gr.Chatbot(
                    label="对话",
                    height=520,
                    show_label=False,
                    avatar_images=(_saved_user, _saved_bot or "🤖"),
                )

                # 头像上传区 (GitHub 风格)
                with gr.Accordion("自定义头像", open=False):
                    with gr.Row(equal_height=True):
                        with gr.Column(scale=1, min_width=160):
                            user_avatar_input = gr.Image(
                                label="用户头像", type="filepath",
                                height=140, width=140, sources=["upload"],
                                elem_classes=["avatar-upload"],
                            )
                            gr.HTML("<div style='text-align:center;font-size:12px;color:#8b949e'>点击上传用户头像</div>")
                        with gr.Column(scale=1, min_width=160):
                            bot_avatar_input = gr.Image(
                                label="Bot 头像", type="filepath",
                                height=140, width=140, sources=["upload"],
                                elem_classes=["avatar-upload"],
                            )
                            gr.HTML("<div style='text-align:center;font-size:12px;color:#8b949e'>点击上传 Bot 头像</div>")
                    with gr.Row():
                        avatar_apply_btn = gr.Button("保存", variant="primary", size="sm")
                        avatar_reset_btn = gr.Button("重置", size="sm")
                    avatar_status = gr.Textbox(show_label=False, interactive=False, container=False)

                with gr.Row():
                    chat_input = gr.Textbox(
                        label="输入消息",
                        placeholder="输入指令，如：帮我采集今天的情报...",
                        scale=8,
                        show_label=False,
                    )
                    chat_send_btn = gr.Button("发送", variant="primary", scale=1)
                    chat_reset_btn = gr.Button("重置", scale=1)

                agent_status = gr.Markdown("", visible=True)

                # 发送消息：chatbot 更新 + 清空输入框
                chat_input.submit(
                    agent_chat_respond,
                    inputs=[chat_input, chatbot],
                    outputs=[chatbot],
                ).then(
                    lambda: gr.update(value=""),
                    outputs=[chat_input],
                )

                chat_send_btn.click(
                    agent_chat_respond,
                    inputs=[chat_input, chatbot],
                    outputs=[chatbot],
                ).then(
                    lambda: gr.update(value=""),
                    outputs=[chat_input],
                )

                chat_reset_btn.click(
                    reset_agent_chat,
                    outputs=[chatbot, agent_status],
                )

                # 头像事件绑定
                avatar_apply_btn.click(
                    apply_avatar,
                    inputs=[user_avatar_input, bot_avatar_input],
                    outputs=[chatbot, user_avatar_input, bot_avatar_input, avatar_status],
                )
                avatar_reset_btn.click(
                    clear_avatar,
                    outputs=[chatbot, user_avatar_input, bot_avatar_input, avatar_status],
                )

        # 页脚
        gr.Markdown(
            "---"
        )
        gr.Markdown(
            f"页面加载于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 如遇问题请检查 .env 配置和日志输出"
        )

    return app


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    os.makedirs("configs", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    app = build_ui()
    port = CONFIG.get("web_ui", {}).get("port", 7860)
    print(f"\n西电校园情报助手 Web UI 启动中...")
    print(f"访问地址: http://localhost:{port}")
    print(f"按 Ctrl+C 停止服务\n")

    app.queue().launch(
        server_port=port,
        server_name="0.0.0.0",
        theme=DARK_THEME,
        css=CUSTOM_CSS,
    )