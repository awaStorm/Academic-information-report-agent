# 西电校园情报 Agent

针对"学习通/学在西电"与微信公众号的校园资讯自动化采集、AI 筛选与推送系统。自动抓取并汇总竞赛报名、限额选课、志愿招募等关键情报，经大模型去重提炼后推送到企业微信 / Server酱。

## 功能概览

- **多源采集**：超星（学习通）校园通知 + 微信公众号文章，双通道并行抓取
- **智能解析**：超星 JSON 清洗、微信 HTML 正文提取、多源合流统一时间轴
- **AI 筛选**：调用 LLM 对全量情报进行"核心/垃圾"二分类，自动生成 Markdown 简报
- **记忆去重**：基于 SQLite + MD5 指纹的情报去重，已推送内容不再重复通知
- **多渠道推送**：企业微信机器人（主）+ Server酱（备），支持独立开关
- **定时调度**：内置 APScheduler，可配置每日多次自动运行
- **Web 管理界面**：基于 Gradio 的暗色主题 UI，涵盖配置、仪表盘、偏好、报告、Agent 对话五大模块
- **Agent 对话**：通过 Tool Calling 让 LLM 自主调度采集→处理→分析→推送全链路

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        数据采集层                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ 超星扫码登录  │  │ 微信扫码登录  │  │   凭证管理(自动)   │  │
│  │SessionHarvest│  │WechatHarvest │  │  auth_cookies.json │  │
│  └──────┬───────┘  └──────┬───────┘  │  wechat_auth.json  │  │
│         │                 │          └───────────────────┘  │
│  ┌──────▼───────┐  ┌──────▼───────┐                        │
│  │  超星通知爬虫  │  │ 微信公众号爬虫 │                        │
│  │   Scraper    │  │WechatScraper │                        │
│  └──────┬───────┘  └──────┬───────┘                        │
└─────────┼─────────────────┼────────────────────────────────┘
          │                 │
          ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据处理层                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  超星数据清洗  │  │ 微信正文解析  │  │   字段对齐精炼     │  │
│  │DataProcessor │  │ WechatParser │  │ContentExtractor   │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         └────────┬────────┘                   │             │
│                  ▼                            │             │
│         ┌──────────────┐                      │             │
│         │  多源情报合流  │◄─────────────────────┘             │
│         │ FinalMerger  │                                    │
│         └──────┬───────┘                                    │
└────────────────┼────────────────────────────────────────────┘
                 │ full_intelligence_stream.json
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                      AI 分析与推送层                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  AI 情报筛选  │  │  记忆去重引擎  │  │   推送管理器       │  │
│  │   Analyzer   │  │ AgentMemory  │  │     Pusher        │  │
│  │ (LLM 调用)   │  │  (SQLite)    │  │ (企业微信/Server酱)│  │
│  └──────┬───────┘  └──────────────┘  └───────────────────┘  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐                                           │
│  │ Markdown 报告 │  → reports/ 目录（自动保留最近 5 份）       │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
.
├── main.py                    # 命令行一键流水线入口
├── app.py                     # Gradio Web UI（配置/仪表盘/偏好/报告/Agent 对话）
├── agent_core.py              # Agent 核心 — LLM Tool Calling 交互循环
├── tools_config.py            # LLM 工具描述元数据 + 分发表
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板
├── LICENSE                    # MIT 许可证
│
├── configs/                   # 配置与凭证（不提交到仓库）
│   ├── .gitkeep
│   ├── settings.yaml          # 全局运行配置（首次运行自动生成）
│   ├── auth_cookies.json      # 超星登录凭证
│   └── wechat_auth.json       # 微信公众平台凭证
│
├── data/                      # 数据文件（不提交到仓库）
│   ├── memory.db              # SQLite 情报记忆库
│   ├── raw/                   # 原始抓取数据
│   │   ├── data_raw_notice.json
│   │   └── data_raw_wechat.json
│   └── processed/             # 处理后数据
│       ├── data_refined.json
│       ├── data_ready_for_ai.json
│       ├── data_wechat_ready.json
│       └── full_intelligence_stream.json
│
├── reports/                   # AI 生成的情报简报（自动保留最近 5 份）
│
├── assets/                    # 头像等静态资源
│   └── avatars/
│       ├── bot.png
│       ├── user.jpg
│       └── user.png
│
└── src/
    ├── agent/
    │   ├── analyzer.py        # AI 分析引擎（LLM 筛选 + 报告生成 + 去重推送）
    │   ├── database.py        # SQLite 数据库（去重/推送记录/偏好管理）
    │   └── pusher.py          # 推送管理器（企业微信 + Server酱）
    ├── collectors/
    │   ├── scrapers/
    │   │   ├── scraper.py            # 超星通知爬虫
    │   │   └── wechat_scraper.py     # 微信公众号爬虫
    │   └── sessions/
    │       ├── session_harvester.py  # 超星扫码登录器
    │       └── wechat_harvester.py   # 微信公众平台扫码登录器
    ├── processors/
    │   ├── data_processor.py         # 超星数据清洗
    │   ├── extractors/
    │   │   ├── content_extractor.py  # 字段对齐精炼
    │   │   └── wechat_parser.py      # 微信 HTML 正文解析
    │   └── mergers/
    │       └── final_merger.py       # 多源情报合流
    └── utils/
        ├── config_loader.py          # 全局配置加载器（自动创建 + 向下兼容）
        └── models_config.json        # 可用 LLM 模型列表
```

## 快速开始

### 1. 环境准备

```bash
# 克隆仓库
git clone https://github.com/awaStorm/Academic-information-report-agent.git
cd Academic-information-report-agent

# 创建虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（扫码登录需要）
playwright install chromium
```

### 2. 配置

```bash
# 复制环境变量模板，填入你的 API Key 和推送地址
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 大语言模型配置（支持 OpenAI 兼容 API）
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 推送渠道（至少配置一个）
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
SERVERCHAN_SENDKEY=                    # 可选，Server酱 SendKey
```

> `configs/settings.yaml` 在首次运行时会自动生成，无需手动创建。也可通过 Web UI 进行完整配置。

### 3. 登录凭证采集

数据源需要扫码登录获取凭证，凭证会保存到 `configs/` 目录：

```bash
# 超星/学习通扫码登录
python src/collectors/sessions/session_harvester.py

# 微信公众平台扫码登录
python src/collectors/sessions/wechat_harvester.py
```

> 凭证有效期有限，过期后需重新扫码。爬虫返回 401 或 `AUTH_EXPIRED` 时即表示需要重新登录。

### 4. 运行

**方式一：命令行一键运行**（适合 cron / 定时任务）

```bash
python main.py
```

该命令会按顺序执行：采集 → 解析合流 → AI 分析推送。

**方式二：启动 Web UI**（推荐）

```bash
python app.py
```

启动后访问 `http://localhost:7860`，可在界面中完成所有操作。

**方式三：Agent 交互模式**（对话式执行）

```bash
python agent_core.py
```

通过自然语言与 Agent 对话，Agent 会自主调度工具链完成任务。

## 配置说明

所有运行时配置存储在 `configs/settings.yaml`，首次运行自动生成默认配置。可通过 Web UI 的"配置面板"在线修改。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `analysis.model_name` | `deepseek-v4-flash` | LLM 模型名称 |
| `analysis.temperature` | `0.1` | 生成温度 |
| `analysis.max_tokens` | `20000` | 最大输出 Token |
| `collectors.wechat.fetch_count` | `5` | 每个公众号抓取文章数 |
| `collectors.wechat.delay_range` | `[5, 8]` | 请求间隔范围（秒） |
| `collectors.wechat.targets` | `["西小电星球", ...]` | 关注的公众号列表 |
| `pusher.enable_wecom` | `true` | 启用企业微信推送 |
| `pusher.enable_console_report` | `true` | 启用控制台报告输出 |
| `scheduler.enabled` | `true` | 启用定时任务 |
| `scheduler.run_times` | `["12:00", "22:00"]` | 每日运行时间 |
| `scheduler.failure_alert_threshold` | `3` | 连续失败告警阈值 |
| `web_ui.dashboard_page_size` | `20` | 仪表盘每页记录数 |
| `web_ui.port` | `7860` | Web UI 端口 |

## Web UI

启动 `python app.py` 后可访问以下五个功能模块：

| Tab | 功能 |
|---|---|
| **配置面板** | LLM 模型、采集参数、推送渠道、定时任务的在线配置 |
| **情报仪表盘** | 推送记录查询、分类统计、来源分布 |
| **偏好设置** | 8 类情报类别偏好选择（竞赛/课程/讲座等） |
| **情报报告** | 查看历史 AI 分析报告（Markdown 渲染） |
| **Agent 对话** | 与 AI Agent 自然语言交互，自主执行工具链 |

## 数据流水线

完整的情报处理流水线分为三个阶段：

```
阶段一：数据采集
  超星通知爬虫 → data/raw/data_raw_notice.json
  微信公众号爬虫 → data/raw/data_raw_wechat.json

阶段二：解析与合流
  WechatParser (HTML正文提取) → data/processed/data_wechat_ready.json
  DataProcessor (超星数据清洗) → data/processed/data_refined.json
  ContentExtractor (字段对齐)  → data/processed/data_ready_for_ai.json
  FinalMerger (多源合流)       → data/processed/full_intelligence_stream.json

阶段三：AI 分析与推送
  Analyzer (LLM筛选 + 去重) → Markdown 报告 → reports/
  Pusher (企业微信/Server酱) → 即时推送
```

## LLM 工具链

Agent 通过 Tool Calling 可调用以下工具：

| 工具名 | 功能 |
|---|---|
| `harvest_chaoxing_session` | 超星扫码登录 |
| `harvest_wechat_session` | 微信公众平台扫码登录 |
| `run_chaoxing_scraper` | 抓取超星校园通知 |
| `run_wechat_scraper` | 抓取微信公众号文章（支持 `extra_query` 定向抓取） |
| `process_raw_data` | 清洗超星原始数据 |
| `refine_data_for_ai` | 字段对齐精炼 |
| `parse_wechat_content` | 解析微信文章正文 |
| `merge_all_intelligence` | 多源情报合流 |
| `check_intelligence_memory` | 情报去重检查 |
| `send_final_report` | 推送核心情报 |
| `analyze_and_push_intelligence` | 一键执行 AI 分析 + 去重 + 推送 |

## 技术栈

| 类别 | 技术 |
|---|---|
| 语言 | Python 3.10+ |
| Web UI | Gradio 4.x |
| 爬虫 | Requests + Playwright (Chromium) |
| HTML 解析 | BeautifulSoup4 |
| LLM | OpenAI SDK（兼容 DeepSeek / Qwen / GPT 等任何 OpenAI 兼容 API） |
| 数据库 | SQLite3 |
| 定时调度 | APScheduler |
| 配置管理 | PyYAML + python-dotenv |
| 推送 | 企业微信 Webhook + Server酱 |

## 依赖

```
requests>=2.28.0
beautifulsoup4>=4.11.0
playwright>=1.40.0
python-dotenv>=1.0.0
openai>=1.0.0
gradio>=4.0.0
pyyaml>=6.0
Pillow>=9.0.0
apscheduler>=3.10.0
```

## 许可证

[MIT License](LICENSE) &copy; 2026 awaStorm
