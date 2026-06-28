# 西电校园情报 Agent v2.0

针对"学习通/学在西电"与微信公众号的校园资讯自动化采集、AI 筛选与推送系统。自动抓取并汇总竞赛报名、限额选课、志愿招募等关键情报，经大模型去重提炼后推送到企业微信 / Server酱。

> **v2.0.0 发布 (2026-06-28)**：移除 Gradio，全面升级为 FastAPI + React 前后端分离架构。多 Agent 扩展、WebSocket 实时日志、去重体系重构、一键推送脚本。详见 [RELEASE_NOTES.md](./RELEASE_NOTES.md)

## 功能概览

- **多源采集**：超星（学习通）校园通知 + 微信公众号文章，双通道并行抓取
- **智能解析**：超星 JSON 清洗、微信 HTML 正文提取、多源合流统一时间轴
- **AI 筛选**：调用 LLM 对全量情报进行"核心/垃圾"二分类，自动生成 Markdown 简报
- **记忆去重**：基于 SQLite + MD5 指纹的情报去重，已推送内容不再重复通知
- **多渠道推送**：企业微信机器人（主）+ Server酱（备），支持独立开关
- **定时调度**：内置 APScheduler，可配置每日多次自动运行
- **Web 管理界面**：FastAPI + React 前后端分离，暗色主题，涵盖配置、仪表盘、偏好、报告、Agent 对话五大模块
- **多 Agent 架构**：BaseAgent 抽象 + AgentRegistry 注册机制，支持动态加载多个 Agent
- **实时日志流**：WebSocket 推送 Agent 执行日志，终端风格实时渲染
- **RESTful API**：完整的 API 接口，支持跨项目联动

## 系统架构（v2.0）

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (React + TypeScript)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 配置面板  │ │ 仪表盘    │ │ 偏好设置  │ │ Agent对话 │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
└───────┼────────────┼────────────┼────────────┼──────────────┘
        │     HTTP/WebSocket       │     │
┌───────┼─────────────────────────┼─────┼──────────────────────┐
│       ▼                         ▼     ▼                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │             后端 (FastAPI + WebSocket)                │    │
│  │  /api/v1/*  RESTful API    /ws/logs  WebSocket        │    │
│  │  AgentRegistry → BaseAgent → XidianAgent             │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
        │                 │                 │
        ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                      核心逻辑层 (src/)                        │
│  采集 (collectors) → 处理 (processors) → 分析 (agent)        │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构（v2.0）

```
.
├── main.py                    # CLI 一键流水线入口
├── agent_core.py              # Agent 核心（LLM Tool Calling 交互循环）
├── tools_config.py            # LLM 工具描述元数据 + 分发表
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板
│
├── backend/                   # 后端服务（新增）
│   ├── main.py                # FastAPI 入口
│   ├── core/                 # Agent 架构核心
│   │   ├── base_agent.py     # Agent 抽象基类
│   │   └── agent_registry.py # Agent 注册器
│   ├── api/v1/               # RESTful API 路由
│   │   ├── agents.py         # Agent 管理 API
│   │   ├── config_api.py     # 配置管理 API
│   │   ├── dashboard_api.py  # 仪表盘 API
│   │   ├── reports_api.py    # 报告管理 API
│   │   └── preferences_api.py # 偏好设置 API
│   ├── agents/               # Agent 实现
│   │   └── xidian_agent.py   # 西电情报 Agent
│   ├── ws/                   # WebSocket
│   │   └── connection_manager.py
│   └── services/             # 业务服务
│       └── scheduler_service.py
│
├── frontend/                  # 前端项目（新增，Vite + React + TypeScript）
│   ├── src/
│   │   ├── api/              # API 客户端
│   │   ├── components/       # 共享组件
│   │   ├── pages/            # 页面组件
│   │   └── App.tsx           # 路由配置
│   └── package.json
│
├── configs/                   # 配置与凭证（不提交到仓库）
│   ├── settings.yaml          # 全局运行配置
│   ├── auth_cookies.json      # 超星登录凭证
│   └── wechat_auth.json       # 微信公众平台凭证
│
├── data/                      # 数据文件（不提交到仓库）
│   ├── memory.db              # SQLite 情报记忆库
│   ├── raw/                   # 原始抓取数据
│   └── processed/             # 处理后数据
│
├── reports/                   # AI 生成的情报简报
│
└── src/                       # 核心业务逻辑（保留）
    ├── agent/
    ├── collectors/
    ├── processors/
    └── utils/
```

## 快速开始

### 1. 环境准备

```bash
# 克隆仓库
git clone https://github.com/awaStorm/Academic-information-report-agent.git
cd Academic-information-report-agent

# 创建虚拟环境（Python 3.10+）
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（扫码登录需要）
playwright install chromium

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 2. 配置文件

```bash
# 复制模板并填入你的 API Key
cp .env.example .env
```

编辑 `.env`：

```env
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

### 3. 启动服务

```bash
# 终端 1：启动后端（FastAPI，端口 8138）
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8138 --reload

# 终端 2：启动前端（Vite，端口 7860）
cd frontend && npm run dev -- --port 7860
```

访问 **http://localhost:7860** 进入管理界面。

- 后端 API 文档：**http://localhost:8138/docs**
- WebSocket 日志流：**ws://localhost:8138/ws/logs**

### 4. 命令行模式（无前端）

```bash
python main.py
```

## API 文档

启动后端后访问 **http://localhost:8138/docs** 查看完整 Swagger API 文档。

主要接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/agents/` | 列出所有已注册 Agent |
| POST | `/api/v1/agents/{name}/chat` | 与 Agent 对话 |
| GET | `/api/v1/config/` | 获取配置 |
| POST | `/api/v1/config/` | 更新配置 |
| GET | `/api/v1/dashboard/records` | 获取推送记录 |
| GET | `/api/v1/dashboard/stats` | 获取统计数据 |
| GET | `/api/v1/reports/` | 列出报告文件 |
| WS | `/ws/logs?session_id=xxx` | 实时日志流 |

## 技术栈

| 类别 | 技术 |
|---|---|
| 后端 | FastAPI + Uvicorn + Pydantic v2 |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| 实时通信 | WebSocket (fastapi-websockets) |
| 爬虫 | Requests + Playwright (Chromium) |
| HTML 解析 | BeautifulSoup4 |
| LLM | OpenAI SDK（兼容 DeepSeek / Qwen / GPT） |
| 数据库 | SQLite3 |
| 定时调度 | APScheduler |
| 配置管理 | PyYAML + python-dotenv |
| 推送 | 企业微信 Webhook + Server酱 |

## 扩展：添加新 Agent

1. 在 `backend/agents/` 下创建新 Agent 类，继承 `BaseAgent`
2. 实现 `get_name()`, `get_tools()`, `chat()`, `run_task()` 等方法
3. 在 `backend/agents/__init__.py` 中注册：

```python
from backend.agents.my_new_agent import MyNewAgent
registry.register(MyNewAgent)
```

## 许可证

[MIT License](LICENSE) &copy; 2026 awaStorm
