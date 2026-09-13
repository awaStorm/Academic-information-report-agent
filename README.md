# 西电校园情报 Agent v2.0

针对"学习通/学在西电"与微信公众号的校园资讯自动化采集、AI 筛选与推送系统。自动抓取并汇总竞赛报名、限额选课、志愿招募等关键情报，经大模型去重提炼后推送到企业微信 / Server酱。

> **v2.0.0 发布 (2026-06-28)**：移除 Gradio，全面升级为 FastAPI + React 前后端分离架构。多 Agent 扩展、WebSocket 实时日志、去重体系重构、一键推送脚本。详见 [RELEASE_NOTES.md](./RELEASE_NOTES.md)
>
> **v2.1.0 (2026-09-13)**：微信情报主数据源由「公众号后台通道」迁移至「微信读书通道」；新增凭证静默续期与登录态自愈；采集失败不再静默为「无新情报」；新增 CTF 赛事时间表模块。**含破坏性接口变更，详见下方「接口变更（v2.1）」章节。**

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
- **CTF 赛事时间表**：抓取 CTFtime 即将开始 / 进行中 / 近期结束赛事，支持赛制与权重排序过滤、置顶关注，每日 12:00 自动刷新
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
│   │   ├── preferences_api.py # 偏好设置 API
│   │   └── ctf.py            # CTF 赛事时间表 API（CTFtime 抓取 + 缓存 + 置顶）
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
| GET | `/api/v1/ctf/events` | CTF 赛事列表 |
| POST | `/api/v1/ctf/refresh` | 异步刷新 CTF 赛事缓存 |
| GET | `/api/v1/ctf/refresh/status` | 查询刷新进度 |
| POST | `/api/v1/ctf/pin/{event_id}` | 切换赛事置顶（大头钉） |
| GET | `/api/v1/ctf/pins` | 获取已置顶赛事 ID 列表 |
| WS | `/ws/logs?session_id=xxx` | 实时日志流 |

## 接口变更（v2.1）

> 本节仅记录**对外契约的变化**。
> 变更背景：原微信公众号后台通道（`searchbiz` + `appmsg/list_ex`）自 2026-07 起对「查询非自身账号」精准软拒绝，抓取结果恒为空列表，并**以 `success=true, count=0` 的形式静默断流**（上层误判为「暂无新情报」，用户以为监控正常运行而实际已中断）。因此微信情报主数据源迁移至微信读书通道，同时收紧返回契约、引入凭证静默续期。

### 1. Agent 工具接口（`tools_config.py`）

| 工具 | 变更 | 说明 |
|---|---|---|
| `harvest_weread_session` | **新增** | 获取 / 刷新微信读书登录凭证。**优先复用档案登录态静默续期，多数情况无需人工扫码**；仅当档案内登录态亦失效时才调起有头浏览器等待扫码（上限约 10 分钟） |
| `harvest_wechat_session` | **降级** | 由主通道扫码工具降级为 legacy 备用通道工具，日常抓取微信情报无需调用 |
| `run_wechat_scraper` | **契约变更** | 主数据源改为微信读书通道；工具描述明确要求按 `error_type` 解读返回值，严禁把抓取失败说成「没有新情报」 |
| `run_chaoxing_scraper` | 描述变更 | 凭证失效判据由「返回 `AUTH_EXPIRED`」改为「返回的 `error_type` 为 `AUTH_EXPIRED` 或 `SESSION_EXPIRED`」 |

工具总数由 8 个增至 9 个。

### 2. 微信采集编排层返回契约（`src/collectors/scrapers/wechat_scraper.py`）

函数签名**保持不变**，返回值语义收紧：

```python
run_wechat_scraper_flow(extra_query=None, progress_callback=None)
```

| 情况 | 返回值 |
|---|---|
| 成功 | `{"success": True, "count": N, ...}` |
| 失败 | `{"success": False, "error_type": "...", "message": "...", "failed_targets": [...]}` |

`error_type` 取值与处置：

| error_type | 含义 | 处置 |
|---|---|---|
| `SESSION_EXPIRED` / `AUTH` | 登录态失效，**且工具已自动静默续期仍未成功** | 调用 `harvest_weread_session` 扫码，完成后自动重跑抓取 |
| `RATE_LIMITED` | 触发限流，凭证仍然有效 | 稍后重试即可，**无需扫码** |
| `SOURCE_UNAVAILABLE` | 数据源确实不可用（通道超时 / HTTP 异常等） | 如实上报，不得谎报为「无新情报」 |
| `NOT_FOUND` | 目标号未被收录或本次检索无结果 | 属正常情况，不报成故障、不计入 `failed_targets` |

> **破坏性变更**：任何失败路径**不再返回 `success=True` + `count=0`**。旧代码若仅以 `count == 0` 判断「无新情报」，必须改为按 `error_type` 区分。
>
> 另一个易踩的坑：微信读书在登录态失效时返回 `{"errCode":-2012,"errMsg":"登录超时"}`，早期判据词表漏掉了「登录超时」，导致这条明确登录失效被误报为 `SOURCE_UNAVAILABLE`。现补全词表并新增已实测确认的 `AUTH_EXPIRED_CODES = (-2012,)`。

### 3. 新增 Python 模块

| 模块 | 公开接口 |
|---|---|
| `src/collectors/scrapers/weread_scraper.py` | `WereadScraper`：`fetch_account_articles()` / `build_session()` / `load_auth()` / `refresh_auth()`；状态常量 `ST_OK` / `ST_AUTH_EXPIRED` 等 |
| `src/collectors/sessions/weread_harvester.py` | `WereadHarvester`：`run_harvest()`（登录判定以业务接口回执为权威依据，而非「本地存在 cookie 即已登录」）、`refresh_cookies()`（静默续期） |

### 4. 配置项变更（`configs/settings.yaml` / `src/utils/config_loader.py`）

| 配置项 | 变更 | 默认值 |
|---|---|---|
| `collectors.wechat.delay_range` | 调整 | `[5, 8]` → `[8, 12]` |
| `collectors.wechat.source_priority` | 新增 | `["weread"]` |
| `collectors.wechat.legacy_backend_enabled` | 新增 | `false` |
| `collectors.wechat.sogou_fallback_enabled` | 新增 | `false` |
| `collectors.weread.max_pages` | 新增 | `2` |
| `collectors.weread.page_interval` | 新增 | `[3, 5]` |
| `collectors.weread.timeout` | 新增 | `30` |
| `collectors.weread.retries` | 新增 | `3` |
| `collectors.weread.rate_limit_backoff` | 新增 | `[10, 30, 60]` |
| `collectors.weread.targets` | 新增 | `[]`（留空表示复用 `collectors.wechat.targets`） |

### 5. REST API 变更

**新增 CTF 赛事时间表路由**（`backend/api/v1/ctf.py`，前缀 `/api/v1/ctf`，标签 `CTF时间表`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/ctf/events` | 赛事列表，参数 `sort` / `format_filter` / `min_weight` / `status_filter` |
| POST | `/api/v1/ctf/refresh` | 异步触发刷新，立即返回，实际抓取在后台线程执行 |
| GET | `/api/v1/ctf/refresh/status` | 轮询刷新进度（`refreshing` / `phase` / `message`） |
| POST | `/api/v1/ctf/pin/{event_id}` | 切换赛事大头钉（置顶 / 取消置顶） |
| GET | `/api/v1/ctf/pins` | 获取已置顶赛事 ID 列表 |

**配置接口默认值变更**：`GET /api/v1/config/` 返回的 `delay_range` 默认值由 `[5, 8]` 改为 `[8, 12]`。

### 6. 前端路由变更

- 新增 `/ctf` 路由（侧边栏「CTF 时间表」，`Trophy` 图标），对应 `frontend/src/pages/CtfPage.tsx` 与 `frontend/src/api/ctf.ts`。
- 仪表盘推送记录状态圆点新增 `failed`（红色）态，与 `pushed`（绿色）、待推送（琥珀色）区分。

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
