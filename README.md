# 西电校园情报 Agent v2.0

针对"学习通/学在西电"与微信公众号的校园资讯自动化采集、AI 筛选与推送系统。自动抓取并汇总竞赛报名、限额选课、志愿招募等关键情报，经大模型去重提炼后推送到企业微信 / Server酱。

> **v2.0.0 发布 (2026-06-28)**：移除 Gradio，全面升级为 FastAPI + React 前后端分离架构。多 Agent 扩展、WebSocket 实时日志、去重体系重构、一键推送脚本。详见 [RELEASE_NOTES.md](./RELEASE_NOTES.md)
>
> **v2.1.0 (2026-09-13)**：微信情报主数据源由「公众号后台通道」迁移至「微信读书通道」；新增凭证静默续期与登录态自愈；采集失败不再静默为「无新情报」；新增 CTF 赛事时间表模块。**含破坏性接口变更，详见下方「接口变更（v2.1）」章节。**
>
> **v2.3.0 (2026-09-18)**：事件日历按 Agent 解析出的**事件发生日期**（`event_date`）打点，与消息获取时间彻底分离，解析不出日期的情报不进日历；竞赛报名/初赛/决赛等多时间点以**事件时间轴**展示，且每个节点在日历上独立打点、可点击跨月跳转；新增可选**多模态识图**（独立视觉模型 API，失败静默降级）。详见下方「事件日期 / 时间轴 / 多模态（v2.3）」章节。
>
> **v2.3.4 (2026-10-06)**：修复 Agent 对话偶发 `HTTP 500`（httpx 默认读取 Windows 系统代理，节点抖动即 TLS 断连）——统一 `trust_env=False` + 连接类错误指数退避重试 + 可读降级返回；定位并修复微信读书**扫码窗口弹不出**的真因（持久化档案与 Playwright 自带 Chromium **版本错配**），并新增**启动自检 + 自动对齐**与 Agent 工具 `align_weread_browser_env`。详见下方「LLM 连接韧性 与 浏览器环境对齐（v2.3.4）」章节。

## 功能概览

- **多源采集**：超星（学习通）校园通知 + 微信公众号文章（主通道经微信读书检索接口），双通道并行抓取
- **智能解析**：超星 JSON 清洗、微信 HTML 正文提取、多源合流统一时间轴
- **AI 筛选**：调用 LLM 对全量情报进行"核心/垃圾"二分类，自动生成 Markdown 简报
- **记忆去重**：基于 SQLite + MD5 指纹的情报去重，已推送内容不再重复通知
- **多渠道推送**：企业微信机器人（主）+ Server酱（备），支持独立开关
- **定时调度**：内置 APScheduler，可配置每日多次自动运行
- **Web 管理界面**：FastAPI + React 前后端分离，暗色主题，涵盖配置、仪表盘、偏好、报告、Agent 对话、CTF 时间表、事件日历七大模块
- **多 Agent 架构**：BaseAgent 抽象 + AgentRegistry 注册机制，支持动态加载多个 Agent
- **实时日志流**：WebSocket 推送 Agent 执行日志，终端风格实时渲染
- **CTF 赛事时间表**：抓取 CTFtime 即将开始 / 进行中 / 近期结束赛事，支持赛制与权重排序过滤、置顶关注，每日 12:00 自动刷新
- **事件日历**：按**事件发生日期**（而非消息获取时间）打点，CTF 赛事与情报合并展示，多阶段事件的时间轴节点独立打点并可点击跨月跳转
- **LLM 连接韧性**：统一客户端工厂绕开本地系统代理，连接类错误自动退避重试，失败时返回可读原因而非裸 500
- **浏览器环境自检与自动对齐**：启动时自检「持久化档案 vs Playwright 自带 Chromium」版本一致性，扫码前自动改用匹配的浏览器二进制，避免"扫码窗口弹不出来"
- **RESTful API**：完整的 API 接口，支持跨项目联动

## 系统架构

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

> 前端路由与侧边栏（7 项）：情报仪表盘 `/dashboard`、偏好设置 `/preferences`、情报报告 `/reports`、
> CTF 时间表 `/ctf`、事件日历 `/calendar`、Agent 对话 `/agents/:agentName/chat`、配置面板 `/config`；
> 未匹配路径重定向到 `/dashboard`。

## 项目结构

```
.
├── main.py                    # CLI 一键流水线入口
├── agent_core.py              # CLI Agent 核心（LLM Tool Calling 交互循环）
├── tools_config.py            # LLM 工具描述元数据 + 分发表（TOOLS_METADATA / TOOL_MAP）
├── requirements.txt           # Python 依赖（playwright 精确锁版本，原因见「浏览器环境对齐」章节）
├── .env.example               # 环境变量模板
├── start.bat                  # Windows 一键启动（后端 8138 + 前端 7860 + 打开浏览器）
├── push-to-github.bat         # 一键提交推送（内置 .env / configs 泄露检查）
├── BUGFIX_LOG.md              # 变更日志（踩坑记录与修复依据，排查问题先看这里）
│
├── backend/                   # 后端服务（FastAPI）
│   ├── main.py                # FastAPI 入口（含启动自检、WebSocket 日志流）
│   ├── core/                  # Agent 架构核心
│   │   ├── base_agent.py      # Agent 抽象基类
│   │   └── agent_registry.py  # Agent 注册器
│   ├── api/v1/                # RESTful API 路由
│   │   ├── agents.py          # Agent 管理 / 对话 / 任务 API
│   │   ├── config_api.py      # 配置管理 API
│   │   ├── dashboard_api.py   # 仪表盘 API
│   │   ├── reports_api.py     # 报告管理 API
│   │   ├── preferences_api.py # 偏好设置 API
│   │   ├── ctf.py             # CTF 赛事时间表 API（CTFtime 抓取 + 缓存 + 置顶）
│   │   └── calendar_api.py    # 事件日历 API（CTF + 情报按事件日期合并分组）
│   ├── agents/                # Agent 实现
│   │   └── xidian_agent.py    # 西电情报 Agent（LLM 决策循环 + 工具执行）
│   ├── ws/                    # WebSocket
│   │   └── connection_manager.py
│   └── services/              # 业务服务
│       └── scheduler_service.py
│
├── frontend/                  # 前端项目（Vite + React + TypeScript）
│   ├── src/
│   │   ├── api/               # API 客户端（client.ts 统一错误文案与 baseURL）
│   │   ├── components/        # 共享组件
│   │   ├── pages/             # 页面组件（含 CtfPage / CalendarPage / AgentChatPage）
│   │   └── App.tsx            # 路由配置
│   ├── vite.config.ts
│   └── package.json
│
├── configs/                   # 配置与凭证（.gitignore，不提交到仓库）
│   ├── settings.yaml          # 全局运行配置（缺失时自动生成默认配置）
│   ├── auth_cookies.json      # 超星登录凭证
│   ├── wechat_auth.json       # 微信公众平台凭证
│   ├── weread_auth.json       # 微信读书凭证（Cookie + UA）
│   └── weread_profile/        # 微信读书浏览器持久化档案（扫码登录态，与 Chromium 版本强耦合）
│
├── data/                      # 数据文件（.gitignore，不提交到仓库）
│   ├── memory.db              # SQLite 情报记忆库（去重与推送记录）
│   ├── raw/                   # 原始抓取数据
│   ├── processed/             # 处理后数据
│   └── ctf_cache.json         # CTF 赛事缓存
│
├── reports/                   # AI 生成的情报简报（.gitignore）
│
└── src/                       # 核心业务逻辑
    ├── agent/                 # analyzer（LLM 分析）/ database / pusher
    ├── collectors/
    │   ├── scrapers/          # 超星、微信读书、微信通道编排层
    │   └── sessions/          # 扫码登录与凭证续期（Playwright）
    ├── processors/extractors/ # HTML / 正文 / 链接提取
    └── utils/
        ├── config_loader.py   # 配置加载（缺失时自动生成默认 settings.yaml）
        ├── llm_client.py      # LLM 客户端工厂 + 重试 + 错误翻译
        └── models_config.json
```

## 快速开始

### 1. 环境准备

```bash
# 克隆仓库
git clone https://github.com/awaStorm/Academic-information-report-agent.git
cd Academic-information-report-agent

# 创建虚拟环境（Python 3.10+；本仓库以 Python 3.13 + Windows 验证）
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（扫码登录需要）
python -m playwright install chromium

# 安装前端依赖
cd frontend && npm install && cd ..
```

> **注意：`requirements.txt` 把 `playwright` 锁在精确版本上（当前 `1.59.0`），不要随手升级。**
> 微信读书的扫码登录态存放在持久化档案 `configs/weread_profile/` 里，该档案与 Playwright 绑定的
> Chromium 版本**强耦合**：更高版本的 Chromium 写过档案后，更低版本再打开会在启动瞬间 abort，
> 而 Playwright 只会抛一句 `Target page, context or browser has been closed`，极难定位。
> 若确需升级：先改 `requirements.txt` 的版本号，装完再执行一次
> `python -m playwright install chromium`，然后重启后端（系统也会在启动时自检并在必要时自动对齐）。

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
ALLOWED_ORIGINS=http://localhost:7860,http://127.0.0.1:7860
```

`configs/settings.yaml` 无需手工创建：首次启动时若缺失，会自动写入一份默认配置。

### 3. 启动服务

**Windows 一键启动**：

```bat
start.bat
```

它会拉起后端（`:8138`）、前端（`:7860`）并打开浏览器。

**手动启动（跨平台）**：

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

### 5. 常见问题

| 现象 | 原因与处置 |
|---|---|
| 对话报 `HTTP 500`，日志出现 `httpx.ConnectError` / `UNEXPECTED_EOF_WHILE_READING` | httpx 默认会读取**系统代理**（Windows 注册表 / 环境变量）。本项目已默认绕开系统代理直连 LLM；若你的网络**必须**走代理，在 `.env` 里设 `LLM_USE_SYSTEM_PROXY=1` |
| 对话返回 `error_type=LLM_UNREACHABLE` | LLM 服务连接失败（已自动退避重试 3 次仍未成功）。多为网络中断 / 代理节点抖动 / 服务端临时不可用，直接重试通常即可 |
| 扫码登录时**浏览器窗口弹不出来** | 优先看后端启动日志里那行「微信读书扫码环境自检」；也可让 Agent 调用 `align_weread_browser_env`（`action=diagnose`）拿结论。**不要**去手动结束 `chrome.exe` 进程——该报错几乎与「档案被占用」无关 |
| 扫码窗口提示版本无法对齐 | 需二选一：① 升级 Playwright 以取得更高版本 Chromium；② 用 `align_weread_browser_env` 的 `action=rebuild` 重建档案（**会丢失登录态、需重新扫码**，旧档案会先被备份） |
| 改了 `.py` 代码但行为没变 | 本仓库目录树较大（`frontend/node_modules` 约 1.18 万文件），uvicorn 的 `--reload` 在 Windows 上可能因目录监视失效而**完全不触发**。请手动重启后端；若要缩小监视范围，用 `--reload-dir backend --reload-dir src`（注意：`--reload-exclude <通配符>` 在 Windows 上会被 click 展开而报 `Got unexpected extra arguments`，不可用） |

## API 文档

启动后端后访问 **http://localhost:8138/docs** 查看完整 Swagger API 文档。

主要接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/agents/` | 列出所有已注册 Agent |
| POST | `/api/v1/agents/{name}/chat` | 与 Agent 对话。LLM 连不上时不返回 500，而是返回 `{"success": false, "error_type": "LLM_UNREACHABLE", "message": "..."}` |
| POST | `/api/v1/agents/{name}/task/{task_name}` | 执行既定任务（`full_flow` / `scrape`） |
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
| GET | `/api/v1/calendar` | 事件日历（参数 `month=YYYY-MM`），CTF 赛事 + 情报按事件发生日期合并分组，timeline 节点独立打点 |
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

## 事件日期 / 时间轴 / 多模态（v2.3）

### 1. 获取日期与事件发生日期分离

`pushed_records` 表新增两列（首次启动自动幂等迁移，旧库安全）：

| 列 | 含义 | 用途 |
|---|---|---|
| `push_time` | 消息**获取时间**（原有，语义不变） | 审计与统计 |
| `event_date` | Agent 从正文解析的**事件发生日期** `YYYY-MM-DD`，无法识别为 `null` | 事件日历打点；`null` 不进日历 |
| `timeline` | JSON 时间轴数组 `[{label, date, time}]`，如报名截止/初赛/决赛 | 仪表盘时间轴展示；每个有效节点在日历独立打点 |

日历查询窗口为 push_time 前 180 天 ~ 后 30 天（覆盖提前数月通知、决赛在数月后的跨月节点），再按 `event_date` / 节点日期过滤到所选月份；同一事件同一天只出现一张卡片。

### 2. 多模态识图（可选，默认关闭）

配置位于 `configs/settings.yaml` 的 `analysis.multimodal`（也可在 Web 配置页「多模态识图」区编辑）：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `false` | 总开关 |
| `api_key` / `base_url` / `model` | 空 | 留空则复用主 LLM 配置；可填独立视觉模型（如 `qwen-vl-max`、`deepseek-vl`） |
| `max_images` | `3` | 单条情报最多送识图的图片张数（控 token） |

行为与注意：

- 微信正文图片（`data-src` 懒加载）自动保留；图片下载转 base64 后调用视觉模型，提取文字追加到正文再送主分析 LLM。
- **配置保存后需重启后端生效**（配置在进程启动时载入内存）。
- **每条含图情报都会单独串行调用一次视觉模型**，含图情报较多时整轮分析耗时明显增加；当前无整批配额上限（仅单条 `max_images` 限制）。
- 未开启、无图片、图片过大、接口报错等情况一律静默降级为纯文本分析，**绝不阻塞主流程**（后端日志可见 `⚠️ 多模态识图失败`）。

### 3. 升级注意（v2.2 → v2.3）

当日分析缓存 `data/analysis_cache_YYYY-MM-DD.json` 中升级前生成的条目不携带 `event_date` / `timeline`，升级当天这些条目仍不会出现在事件日历中——**删除当天缓存文件后重新分析，或次日缓存自动轮换后即恢复正常**。

## LLM 连接韧性 与 浏览器环境对齐（v2.3.4）

### 1. LLM 客户端统一（`src/utils/llm_client.py`）

**为什么需要**：`OpenAI()` 内置的 httpx 客户端默认 `trust_env=True`，在 Windows 上会读取**注册表里的系统代理**（`ProxyEnable` / `ProxyServer`）。若本机装了 Clash / 加速器等工具，每句 LLM 请求都会被塞进代理隧道，代理节点抖动的那一瞬间 TLS 握手失败并冒泡为
`openai.APIConnectionError`，最终打成一句没有任何信息量的 `HTTP 500`。而 LLM 服务通常**直连即可**，把可用性绑在一个会抖动的本地代理上并无收益。

| 公开接口 | 作用 |
|---|---|
| `build_llm_client(api_key, base_url, ...)` | 统一构造客户端：默认 `trust_env=False` **绕开系统代理**，读超时放宽到 600s；设 `LLM_USE_SYSTEM_PROXY=1` 可恢复"走系统代理"的旧行为 |
| `call_with_retry(fn, *args, attempts=3, on_retry=...)` | **只对连接类错误**做 2s→4s 指数退避重试（SDK 自带退避仅 0.4s/0.8s 量级，扛不住代理节点切换）；业务错误不重试 |
| `is_connection_error(exc)` / `describe_llm_error(exc)` | 错误归类与可操作的中文文案（含「关闭系统代理后重试」） |
| `use_system_proxy()` | 读取上述开关 |

调用链上的四个客户端构造点已全部收口到该工厂：`backend/agents/xidian_agent.py`、`agent_core.py`、`src/agent/analyzer.py`（主分析 + 多模态识图）。

**降级契约**：对话/任务接口遇到连接类异常时**不再抛 500**，而是返回
`{"success": false, "error_type": "LLM_UNREACHABLE", "message": "..."}`；非连接类异常仍抛 500 并保留完整堆栈便于定位。前端 `client.ts` 的错误文案也补取了 FastAPI 的 `detail` 字段。

### 2. 浏览器持久化档案与 Chromium 版本对齐

**档案（profile）是什么**：`configs/weread_profile/` 是一个 Chromium **user-data-dir**——浏览器把 Cookie、localStorage、IndexedDB、站点权限、缓存等整个用户配置落盘于此。扫码登录态就存在这里，所以「扫一次码可长期复用」。

**为什么会出现"扫码窗口弹不出来"**：档案与 Playwright 绑定的 Chromium 版本**强耦合**，且**只有"低版本打开高版本写过的档案"才崩**（反向与相同版本都正常）。实测三步复现：

| 步骤 | 结果 |
|---|---|
| 全新空档案 + chromium-1208（Chromium 145）有头启动 | 正常 |
| 用 chromium-1217（Chromium 147）打开同一档案，档案根目录 `Last Version` 被写成 `147.0.7727.15` | 正常 |
| 换回 chromium-1208 有头启动 | **启动瞬间 abort**（exitCode `0x80000003`，档案 `Crashpad/reports/` 留下 `.dmp` 转储） |

Playwright 对此只报 `Target page, context or browser has been closed`，随后 `taskkill` 还会提示「找不到进程」（进程已自行崩溃），极易被误判成"档案被占用"或显卡问题。
**无法只靠改标记无损修复**：实测把 `Last Version` 改回旧值、乃至直接删除该文件，旧版本打开仍然崩溃——不兼容来自档案**内部 schema**。

**自动对齐**：有头启动前，从本机 `ms-playwright` 目录扫描已安装的 `chromium-<rev>`，挑一个「修订号 ≥ 档案最后使用者、且尽量贴近」的二进制，用 `executable_path` 启动。**无需人工干预，且保留登录态（不必重新扫码）**；若对齐所用二进制起不来，会自动退回 Playwright 自带版本。
（无头路径不做对齐：`chrome-headless-shell` 不校验档案版本，所以"静默续期"本来就不受影响，这正是症状表现为"只有扫码崩"的原因。）

**环境自检**：`WereadHarvester.diagnose_browser_env()`（**纯读取**，不启动浏览器、不改文件）返回：

| `status` | 含义 | 处置 |
|---|---|---|
| `ok` | 运行版本 ≥ 档案版本 | 直接扫码 |
| `auto_align` | 档案更新，但本机有足够新的 chromium | 系统启动浏览器时会自动对齐，直接扫码 |
| `needs_rebuild` | 档案更新，且本机无足够新的 chromium | 二选一：① 升级 Playwright；② 重建档案（丢登录态、需重新扫码） |
| `no_profile` | 档案不存在 | 首次扫码会自动创建 |
| `unknown` | 读不到 `Last Browser` / 修订号 | 跳过判定，直接尝试 |

后端**启动时**会调用该自检并写入日志（`✅/⚠️ 微信读书扫码环境自检: ...`），用 `try/except` 包住，自检失败绝不影响后端启动。

**Agent 工具** `align_weread_browser_env`（工具总数 12 → 13）：

- `action=diagnose`（默认，只读）：返回自检结论 + `next_step` 指引，便于 Agent 自行判断下一步；
- `action=rebuild`：把档案**改名备份**为 `<profile>.bak-YYYYmmdd-HHMMSS` 后再重建（不直接删除，可回退）；有浏览器会话在跑时直接拒绝，不硬来。**属破坏性操作，需先征得用户同意。**

> 与档案版本强耦合相关的还有一条硬约束：`requirements.txt` 中 `playwright` **必须精确锁版本**，原因见「快速开始」的注意事项。

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
