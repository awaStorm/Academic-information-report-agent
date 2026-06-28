## v2.0.0 更新内容 (2026-06-28)

### 架构重构：Gradio → FastAPI + React

**彻底告别 Gradio**，全面迁移至**前后端分离架构**：
- **后端**：FastAPI + WebSocket，RESTful API 设计，支持跨项目联动
- **前端**：React 18 + TypeScript + Tailwind CSS，暗色主题，五模块管理面板
- 端口：后端 8138 / 前端 7860，`start.bat` 一键启动两个独立窗口

### 多 Agent 架构

- **BaseAgent 抽象类 + AgentRegistry 注册机制**：支持动态加载多个 Agent，各 Agent 独立上下文、独立调度
- 每个 Agent 携带自己的 `system_prompt`、工具集、历史记录
- 为后续接入更多校园数据源（教务系统、图书系统等）奠定基础

### Agentic Loop 完整实现（核心修复）

- **while True 多轮循环**：LLM 返回 `tool_calls` 后自动执行工具，结果反馈回 LLM 继续推理
- **Token 计数**：累计显示每次对话的 Token 消耗，通过 WebSocket 实时推送
- **异常保护**：工具执行失败时捕获异常并反馈给 LLM，Agent 自行处理而不是直接崩溃
- **asyncio 兼容**：Playwright Sync API 在独立线程池执行，彻底解决 asyncio 事件循环冲突

### 去重体系重构（核心修复）

| 层级 | 修复前 | 修复后 |
|------|--------|--------|
| 指纹源 | MD5 基于 AI 生成的 `brief`（AI 理解变动即失效） | `raw_hash` 基于标题 + ID/链接，抓取阶段即生成 |
| 标题匹配 | 精确匹配（空格/换行/标点差异即漏判） | `clean_title()` 清洗 + SQLite LIKE 模糊匹配兜底 |
| 过期过滤 | 正则匹配日期（误杀"发布日期早但事件日期晚"的通知） | 保守过期过滤 + deadline 结构化比对（YYYY-MM-DD） |

### WebSocket 实时日志流

- Agent 执行全程通过 WebSocket 推送结构化日志（`info` / `tool` / `error` / `token`）
- 前端终端风格实时渲染，告别 Gradio Chatbot 的严重卡顿
- WebSocket 实例统一为全局单例，根治"连接注册在 A 实例，日志查找 B 实例"的致命 Bug

### 上下文滑窗清理

- Agent `history` 在 `while True` 循环中无限累积 → Token 滚雪球至 22891
- 新增 `_trim_history()`：每轮完成后只保留 `system_prompt` + 最近 3 轮对话

### 配置面板完善

- **恢复公众号列表管理 UI**：Gradio 迁移时遗漏的增删控件已补全（标签展示 + 添加/删除按钮）
- 导航栏顺序调整：仪表盘置顶，配置面板移至末尾
- 统计卡片仅保留在仪表盘，配置面板去除冗余统计

### 推送脚本

- **`push-to-github.bat`**：一键安全检查 → 变更预览 → 确认 → 提交 → 推送，支持手动输入版本号自动打 `git tag`
- **`start.bat`**：一键启动前后端双窗口，自动打开浏览器

---

## v1.1.0 更新内容

### 新特性
- **终端风格 Agent 对话 UI**：用 `gr.HTML` + 后台线程 + 队列轮询替代 `gr.Chatbot`，解决严重卡顿问题，实现 CMD 风格实时流式输出

### Bug 修复
- **工具返回值误判为失败**：所有工具函数返回 `None` 被判定为失败显示 ❌，现已修复判定逻辑并补充结构化返回值
- **企业微信显示假链接**：`pusher.py` 的 link 字段缺少 http 校验，LLM 填入的 ID（如 35）被渲染为 `[🔗详情](35)`，已加上 `startswith('http')` 校验
- **LLM 误填 ID 为链接**：`analyzer.py` system prompt 现已明确要求 link 字段不填 ID/数字
- **合流文件路径不对齐**：`analyzer.py` INPUT_FILE 已对齐为 `data/processed/full_intelligence_stream.json`
- **硬编码"截止"限制 LLM 表达**：移除 `pusher.py` 和 `analyzer.py` 中硬编码的"⏰截止"前缀和"📅常规动态"默认值，LLM 可自由描述时间属性

### 重构
- `Scraper.fetch_and_save` → 返回 `{"success": True, "count": N}`
- `WechatScraper.run_scraper_flow` → 返回 `{"success": True, "count": N}`
- `DataProcessor.run` → 返回 `{"success": True, "count": N, "unread": N}`
- `ContentExtractor.clean_and_refine` → 返回 `{"success": True, "count": N}`
- `WechatParser.run_parser` → 返回 `{"success": True, "count": N}`
- `FinalMerger.merge_intelligence` → 返回 `{"success": True, "count": N}`
- `run_analysis_flow` → 返回 `{"success": True/False, ...}` 替代 `True/False`
