# Bug 修复日志

> **维护说明**: 每次发现并修复 Bug 后，请在此文档中记录，帮助团队避免重复踩坑。

---

## [2026-06-28] v2.0.0 正式发布

### Changed
- 编写 `RELEASE_NOTES.md` v2.0.0 完整更新日志（架构重构 + 核心修复 + 工具链）
- `README.md` [UPDATE] — 更新版本说明，添加 RELEASE_NOTES.md 链接
- `push-to-github.bat` [UPDATE] — 新增版本号输入 + 自动 `git tag -a` + `git push origin vX.X.X`

---

## [2026-06-28] 推送脚本纯 ASCII 化：修复特殊字符报错

### Fixed
- `push-to-github.bat` [FIX] — 移除所有 UTF-8 特殊字符（框线符号 `╔╗╚╝`、对勾 `√` 等），改为纯 ASCII 表示（`[OK]`、`===`、`---`），彻底解决 CMD 中 "xxx is not recognized" 错误

---

## [2026-06-28] 新增一键推送 GitHub 脚本 + 完善 .gitignore

### Added
- `push-to-github.bat` — 一键推送脚本，5 步流程：
  1. 安全检查：自动检测 `.env`、`configs/` 等敏感文件是否被正确排除
  2. 变更预览：展示 `git status --short` 供用户确认
  3. 确认交互：Y/N 二次确认防误推送
  4. 提交：自动生成 `[YYYY-MM-DD] 描述` 格式的提交信息
  5. 推送：先 `pull --rebase` 再 `push origin main`，防冲突
- `.gitignore` [UPDATE] — 新增排除项：`node_modules/`、`.codebuddy/`、`_title_keep.bat`、`task_human.txt`

---

## [2026-06-28] 配置面板补完：恢复公众号列表管理 UI

### 问题
从 Gradio 迁移到 React 前端时，配置面板漏掉了公众号列表的增删管理 UI。后端 API 和前端数据类型虽已预留 `wechat_targets` 字段，但 ConfigPage.tsx 无对应操作控件，用户无法在页面上管理抓取的公众号列表。

### 修复
- `frontend/src/pages/ConfigPage.tsx` [MODIFY] — 新增公众号管理区域：
  - 输入框 + 添加按钮（支持回车快捷添加）
  - 标签式展示当前公众号列表，每个标签带 × 删除按钮
  - 空列表时显示引导提示
  - 新增 `newTarget` 状态和 `handleAddTarget`/`handleRemoveTarget` 处理函数
  - 去重检查：添加时自动过滤逗号、检测重复名称

---

## [2026-06-28] 多 Agent 架构重构：去重失效、过期消息、上下文稀释修复

### 核心问题
1. **去重失效**：数据总量没变却推送了更多消息（昨天9条→今天21条）
2. **过期消息混入**：Agent 缺乏时间锚点，推送了已过期的内容
3. **上下文稀释**：单 Agent 串行流水线 Token 滚雪球至22891，Agent 后期失焦

### 解决方案（5个关键补丁）

#### 补丁1：哈希前置去重
- **根因**：原 MD5 基于 AI 生成的 `brief`，如果 AI 理解有细微变化，hash 就会改变，导致去重失效
- **修复**：
  - `scraper.py`：为超星通知生成 `raw_hash`（基于标题 + 通知ID），在抓取阶段写入原始数据
  - `wechat_scraper.py`：为微信文章生成 `raw_hash`（基于标题 + 文章链接），在抓取阶段写入原始数据
  - `analyzer.py`：去重逻辑优先使用 `raw_hash`，旧数据无此字段时回退到 `title + brief` 生成 hash

#### 补丁2：标题清洗 + 模糊匹配兜底
- **根因**：标题中的空格、换行符、中英文标点抖动会导致精确匹配失效
- **修复**：
  - 新增 `clean_title()` 函数：去除首尾空格、换行符、统一中文标点
  - 去重逻辑增加模糊匹配兜底：SQLite `LIKE '%标题前10字%'` 匹配

#### 补丁3：保守过期过滤 + deadline 结构化
- **根因**：原正则匹配日期会误杀"发布日期早于今天但事件日期晚于今天"的通知
- **修复**：
  - 新增 `_filter_expired_items_conservative()`：只过滤"所有日期都过期"的硬过期条目
  - 注入强时间锚点到 `system_instruction`：要求 AI 输出结构化 `deadline` 字段（YYYY-MM-DD）
  - 代码层比对 `deadline`：如果 `deadline < today` 则跳过

#### 补丁4：上下文滑窗清理
- **根因**：`self.history` 随着 `while True` 循环滚雪球，导致 Token 累积至22891
- **修复**：
  - 新增 `_trim_history()` 方法：只保留 `system_prompt` + 最近3轮对话
  - 在 `_run_full_flow()` 完成后调用清理

#### 补丁5：空数据中断保护
- **根因**：当所有数据都被过滤后，`final_pushed_list` 为空，Agent 可能无中生有
- **修复**：在3个关键节点增加空判定，直接 `return` 终止流程

### 修改文件
- `src/agent/analyzer.py` [MODIFY] - 核心重构：新增 clean_title、保守过期过滤、raw_hash去重、标题精确匹配、deadline比对、空数据保护、审计日志
- `backend/agents/xidian_agent.py` [MODIFY] - 新增 _trim_history()、优化 system_prompt
- `src/collectors/scrapers/scraper.py` [MODIFY] - 抓取阶段生成 raw_hash
- `src/collectors/scrapers/wechat_scraper.py` [MODIFY] - 抓取阶段生成 raw_hash

---

## [2025-06-28] 导航栏与页面布局优化

### Changed - 配置面板去除统计卡片，导航顺序调整
- **ConfigPage.tsx**：移除配置面板顶部统计卡片（今日推送/本周推送/微信情报/超星通知），统计仅保留在仪表盘
- **Layout.tsx**：导航栏顺序调整，配置面板移至末尾，情报仪表盘移至首位
- **App.tsx**：默认路由从 `/config` 改为 `/dashboard`，进入系统首先看到情报仪表盘

---

## [2025-06-27] 前后端架构重构与多项 Bug 修复

### Changed - 端口调整
- 后端端口 `8000` → `8138`
- 前端端口 `5173` → `7860`

### Changed - 一键启动脚本
- 新增 `start.bat`，独立窗口启动后端和前端，并自动打开 Edge 浏览器
- 所有窗口标题统一加 `AIRA -` 前缀，便于在多 CMD 窗口中识别
- 后台保活循环每 5 秒重置标题，防止 Vite/uvicorn 启动时覆盖窗口标题
- 标题守卫逻辑抽至 `_title_keep.bat`，解决 `cmd /k` 嵌套引号导致 `&` 泄露为外层命令分隔符、最终主窗口被 `python -m uvicorn` 阻塞的致命 Bug

### Fixed - Layout.tsx 子页面不渲染（核心 Bug）
- `Layout.tsx` 使用 `{children}` props 接收子页面，但 `App.tsx` 用的 React Router v6 Layout Route 模式要求 `<Outlet />`，导致所有子页面空白
- 修复：`{children}` → `<Outlet />`

### Fixed - preferences_api.py 函数名冲突
- 路由函数名与从 `database.py` 导入的函数名重名导致递归崩溃
- 修复：使用别名导入 `get_preferences as db_get_preferences`

### Fixed - 前端代码规范问题
- `client.ts`：封装类型安全的 `api` 对象，修复 axios 拦截器返回值类型不一致
- 所有页面：`catch (e: any)` → `catch (e)` + `(e as Error).message`
- `DashboardPage.tsx`：`const d = new Date(); d.setDate(...)` 一行双语句拆为两行
- 多个 `useEffect`/`useCallback` 缺少依赖项已添加 `eslint-disable` 注释

### Fixed - Agent 对话无响应（WebSocket 实例不同步，核心 Bug）
- **根因**：`main.py` 创建了本地 `ws_manager = ConnectionManager()`，但 `XidianAgent._send_log()` 使用的是 `connection_manager.py` 全局 `manager`。WebSocket 连接注册在 A 实例，日志推送查找 B 实例 → `send_log` 永远找不到 session 直接 `return`
- **修复**：`main.py` 改为 `from backend.ws.connection_manager import manager as ws_manager`，统一使用全局单例
- **前置降级**：`AgentChatPage.tsx` 对 REST 响应添加 `.then()` 降级逻辑，当 WebSocket 日志未到达时 1s 后用 REST 响应填充
- **附带修复**：`ConnectionManager.disconnect()` 支持按具体连接移除，session 下无连接时彻底清理 key

### Fixed - Agent 只回"好的"不执行工具（Agentic Loop 缺失，核心 Bug）
- **根因**：`backend/agents/xidian_agent.py` 的 `chat()` 方法是 `agent_core.py` 的不完整移植，缺少三个关键要素：
  1. **while 循环**：只调用一次 LLM API 就 `return`，DeepSeek 返回的 `tool_calls` 直接被丢弃
  2. **工具执行**：`execute_tool()` 从未被调用，工具结果从未反馈回 LLM
  3. **Token 计数**：`response.usage` 从未读取，前端永远看不到 token 消耗
- **修复**：重写 `chat()` 为完整 Agentic Loop：
  - 添加 `while True` 多轮循环，反复调用 LLM 直到无 `tool_calls` 或用户说再见
  - 每轮检查 `response_msg.tool_calls`，遍历执行 `execute_tool()`，将结果追加到 `history`
  - 累计 `response.usage` 并通过 WebSocket 推送 token 日志（`cls: "token"`）
  - 异常保护：工具执行失败时捕获异常并反馈给 LLM 继续处理
- **附带修复 1**：`backend/api/v1/agents.py` 响应去嵌套，`result` 自身已含 `success` 字段，去掉外层 `{"success": True, "data": result}` 包装
- **附带修复 2**：`AgentChatPage.tsx` 添加 `token` 类的颜色映射（`text-purple-400`），修复降级响应解析路径

### Fixed - Playwright Sync API 在 asyncio 循环中报错
- **根因**：`chat()` 改为 `async` 后，同步调用 `execute_tool()` 会在 asyncio 事件循环内执行 `playwright.sync_api`，Playwright 检测到事件循环后拒绝运行
- **现象**：`harvest_wechat_session` / `harvest_chaoxing_session` 报错 `It looks like you are using Playwright Sync API inside the asyncio loop`
- **修复**：`execute_tool()` 调用改为 `asyncio.to_thread(execute_tool, function_name, **args)`，将所有同步工具放到独立线程池执行，与事件循环隔离

### Fixed - 对话末尾总是显示"请求失败"（ChatCompletionMessage 类型混用）
- **根因**：`self.history` 中混合了 dict 和 `ChatCompletionMessage`(Pydantic) 两种类型。循环结束后提取 `final_content` 时用 `msg.get("role")` 遍历，对 Pydantic 对象无 `.get()` 方法，触发 `AttributeError`
- **现象**：所有 WebSocket 日志正常推送，唯独 REST 响应返回 500，前端降级显示"请求失败"
- **修复**：提取时用 `isinstance(msg, dict)` 判断类型，dict 用 `.get()`，对象用 `getattr()` 兼容

### Fixed - Playwright 浏览器版本不匹配
- **根因**：`pip install` 更新了 Playwright 到 1.59.0（需要 chromium-1217），但本地仅有旧版 chromium-1208 浏览器
- **修复**：执行 `playwright install chromium` 下载匹配版本

---

## [2025-06-27] 前端标签页图标与标题更新

### Changed - 网站 Favicon 和 Title 更换
- **变更**：`frontend/index.html` 中将 favicon 从 `/vite.svg` 更换为 `/AIRA.svg`，页面标题从 `Vite + React + TS` 更换为 `AIRA - 学术情报报告智能体`
- **操作**：复制根目录 `AIRA.svg` 到 `frontend/public/AIRA.svg`

---

## [2025-06-10] Gradio 6.x 破坏性变更兼容修复

### 环境信息

| 项目 | 内容 |
|------|------|
| Gradio 版本 | 6.14.0（pip install gradio 默认安装最新版） |
| 项目声明的依赖 | `gradio>=4.0.0`（requirements.txt 未锁定上限） |
| 影响文件 | `app.py` |
| 修复提交 | 未提交（本地修复） |

### 错误现象

运行 `python app.py` 时报错：

```
TypeError: Base.set() got an unexpected keyword argument 'layout_display'
```

修复第一轮后运行再次报错：

```
TypeError: Markdown.__init__() got an unexpected keyword argument 'scale'
```

### 根因分析

两个问题都是 **Gradio 6.x 的破坏性变更**导致的：

#### 问题 1：`gr.themes.Base().set()` 移除了布局参数

**移除的参数：**
- `layout_display`
- `layout_fill_width`
- `layout_fill_width_dark`

这些参数在 Gradio 5.x 中可用，但在 6.x 中被移除（布局层概念被重构）。

**受影响代码（app.py 原第 65-67 行）：**
```python
layout_display="block",
layout_fill_width=True,
layout_fill_width_dark=True,
```

#### 问题 2：非布局组件移除了 `scale` 参数

**Gradio 6 规则：** **只有 `gr.Row` 和 `gr.Column`** 支持 `scale=` 参数，以下组件的 `scale=` 全部被移除：

| 受影响的组件 | 出现次数 |
|-------------|---------|
| `gr.Textbox` | 7 处 |
| `gr.Button` | 8 处 |
| `gr.Markdown` | 2 处 |
| `gr.Dropdown` | 4 处 |
| `gr.Number` | 4 处 |

**受影响代码示例（修复前）：**
```python
# 这些都会报错
gr.Textbox(..., scale=3)
gr.Button("发送", scale=1, min_width=80)
gr.Markdown("**记录数**: --", scale=3)
gr.Dropdown(..., scale=5)
gr.Number(..., scale=1)
```

### 修复方案

**修复 1：移除主题中的废弃布局参数**
```python
# 修复前
block_shadow="none",
layout_display="block",         # ← 删除
layout_fill_width=True,          # ← 删除
layout_fill_width_dark=True,     # ← 删除
button_primary_background_fill=...

# 修复后
block_shadow="none",
button_primary_background_fill=...
```

**修复 2：移除所有非布局组件上的 `scale=` 参数**

```python
# 修复前
gr.Textbox(label="Base URL", scale=3)

# 修复后
gr.Textbox(label="Base URL")
```

**特别注意：`gr.Column(scale=N, ...)` 保持不变**，因为布局组件仍然支持 `scale`。

### 经验教训

1. **依赖版本必须锁定上限**

   `requirements.txt` 中 `gradio>=4.0.0` 会导致自动安装最新大版本（6.x），造成不兼容。

   **建议修改为：**
   ```
   gradio>=4.0.0,<5.0.0
   ```
   或关注 Gradio 6 迁移指南后升级到：
   ```
   gradio>=6.0.0,<7.0.0
   ```

2. **每次 Gradio 大版本升级需检查以下变更：**
   - `gr.themes.Base().set()` 的可用参数
   - 非布局组件的 `scale` 参数是否被移除
   - `gr.Markdown()` 等组件的构造函数签名变化
   - 布局系统 API 变化

3. **排查方法**
   ```python
   # 快速检查某个参数是否在组件构造函数中可用
   import gradio as gr
   import inspect
   sig = inspect.signature(gr.Textbox.__init__)
   print('scale' in sig.parameters)  # False → 已移除
   ```

### Checksum（快速自查表）

以下参数在 **Gradio 6.x 中已被移除**，不可在任何非布局组件上使用：

| 已移除参数 | 替代方案 |
|-----------|---------|
| 非布局组件 `.scale=N` | 用 `gr.Column(scale=N)` 包裹，或使用 `min_width` |
| 主题 `.set(layout_display=...)` | 已废弃，无需替代 |
| 主题 `.set(layout_fill_width=...)` | 已废弃，无需替代 |

---

## 日志模板

后续记录 Bug 请复制以下模板：

```markdown
## [YYYY-MM-DD] Bug 标题

### 环境信息
- 相关版本：
- 影响文件：

### 错误现象
（粘贴完整报错）

### 根因分析
（分析为什么出错）

### 修复方案
（修复前后的代码对比）

### 经验教训
（如何防止再犯）
```
