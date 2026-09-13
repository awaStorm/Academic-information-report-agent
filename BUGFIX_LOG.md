# Bug 修复日志

> **维护说明**: 每次发现并修复 Bug 后，请在此文档中记录，帮助团队避免重复踩坑。

---

## [2026-09-13] v6.0：微信情报来源通道迁移（后台通道关闭 → 微信读书通道）

### Added
- **新增微信读书通道采集器** `src/collectors/scrapers/weread_scraper.py`：原微信公众号后台通道（`searchbiz` + `appmsg/list_ex`）已对「查询他号」精准软拒绝，抓取结果恒为空列表。改为复用微信读书 Web 端搜一搜数据源 `POST https://weread.qq.com/web/wx_search_broker_proxy`，产出与旧通道**完全同构**的原始文章结构（`title` / `link` / `update_time` / `aid` / `source_account` / `raw_hash`）并写入同一产物 `data/raw/data_raw_wechat.json`，下游解析、合流、分析、推送链路零改动。
- 新增统一状态语义常量（`ok` / `not_found` / `empty` / `auth_expired` / `rate_limited` / `source_unavailable` / `error`），为后续编排层的「失败不再静默」打底。
- 新增规范身份键 `raw_key`（优先 `__biz` + `mid` + `idx`，缺失时退化为「来源公众号 + 标题」），用于跨来源去重；**不改动**旧 `raw_hash` 算法，以零风险兼容存量数据。
- 新增分页抓取能力（单号默认翻 2 页）。
- **新增来源编排层** `src/collectors/scrapers/wechat_scraper.py`：按配置的来源优先级依次尝试各通道并支持降级；聚合 + 跨来源去重后**统一写入** `data/raw/data_raw_wechat.json`（单一写入口）；`run_wechat_scraper_flow` 函数签名与 `success` / `count` 字段保持兼容，`main.py` / `backend` / `tools_config.py` 调用方式无需改动。原公众号后台通道降级为 legacy 适配器并默认关闭（其接口自 2026-07 起已失效，保留仅为恢复时一键切回）。
- **新增微信读书凭证采集器** `src/collectors/sessions/weread_harvester.py`：复用 Playwright 持久化档案（`configs/weread_profile`），扫码一次后长期复用；等待上限 10 分钟并实时提示剩余时间；凭证值打码输出，仅取 `weread.qq.com` 域下 Cookie。**登录判定以业务接口 `wx_search_broker_proxy` 的真实回执为权威依据**，而不是「本地 cookie 里存在 wr_vid 就算已登录」——后者会误判并导致扫码工具秒退（详见 Fixed 第 3 条）。
- 新增配置项（`src/utils/config_loader.py` + `configs/settings.yaml`）：`source_priority` / `legacy_backend_enabled` / `sogou_fallback_enabled`，以及 `collectors.weread` 段（`max_pages` / `page_interval` / `timeout` / `retries` / `rate_limit_backoff`）。
- 新增工具 `harvest_weread_session`（`tools_config.py`），并同步注册到 `TOOL_MAP`。
- 新增 `WereadHarvester.refresh_cookies()` 与 `WereadScraper.refresh_auth()`：**静默续期**，复用档案里已有的登录态刷新 cookie 并落盘，不打扰用户。实测证据：同一时刻 `[落盘 cookie] → {"errCode":-2012,"errMsg":"登录超时"}` 被拒，而 `[档案 cookie] → {"content":{...}}` 正常，且两边**值不同的字段恰为 `wr_gid` / `wr_skey`**（服务端轮换）。即这种情况**根本不需要重新扫码**。
- 新增编排层「登录态自愈」：`run_scraper_flow` 首个目标返回 `auth_expired` 时，自动调用 `refresh_auth()` 并重试一次（每轮至多一次），成功则整轮照常继续。
- 新增「凭证失效短路」：`auth_expired` 属**全局性**问题，一旦确认即提前结束巡检，不再对剩余目标发起无谓请求（原先 9 个号要白等一分多钟的切换间隔）。

### Fixed
- **微信情报静默断流**：原抓取器在业务失败时只打印错误并返回空数组，上层据此判定为「暂无新情报」，用户以为监控在正常运行而实际已中断。新采集器明确区分各状态并返回可读 `message`，不再以「成功 + 0 条」掩盖失败。
- **任务层把失败包装成成功**：`backend/agents/xidian_agent.py` 的 `run_task` 原先无论子任务结果如何都打印「✅ 任务完成」并返回 `success=True`，采集失败对外显示为成功。现按子任务真实结果回报。
- **抓取返回值被丢弃**：`_run_full_flow` / `_run_scrape` 原先直接丢弃 `run_scraper_flow` 的返回值，失败在界面上完全不可见。现新增 `_report_wechat_result` 按 `error_type` 分类上报，`full_flow` 额外附加 `wechat_error` 字段（不中断整轮，超星数据仍有效）。
- **`empty` 被误判为抓取失败**：`fetch_account_articles` 在「通道正常但该号确实没有文章」时沿用了循环末尾的接口状态（可能为 `ok`），导致编排层将其错记进 `failed_targets`。现精确区分 `empty`（回执里有条目但都不是该号）与 `not_found`（回执里完全没有条目）。
- **进度回调静默失效**：编排层以 4 个参数调用 `progress_callback`，而既有契约是 `(current, total, message)` 3 个参数，`TypeError` 被 `except` 吞掉导致进度日志不再输出。已按契约修正。
- **`-2012 登录超时` 被误判为「数据源不可用」**（2026-09-13 17:05 问题主因）：微信读书在登录态失效时返回 `{"errCode":-2012,"errMsg":"登录超时","errLog":"...","info":""}`，而判据词表只含「未登录 / 登录失效 / 请先登录」，**漏掉了「登录超时」**，于是这条明确的登录失效掉进兜底分支被报成 `SOURCE_UNAVAILABLE`，导致 Agent 得出「数据源宕机、扫码无用」的结论并**拒绝引导用户扫码**。现补全词表并新增已实测确认的 `AUTH_EXPIRED_CODES = (-2012,)`。
- **错误原文被丢弃**：回执的可读原因在 `errMsg` 字段，而代码只读 `errCode` / `msg`，界面上只显示 `-2012`、真正有用的「登录超时」反而丢失。现优先取 `errMsg`。
- **扫码工具秒退死循环**：`run_harvest` 原先只要本地 cookie 存在 `wr_vid` 就判定「已登录」并立即保存退出；但服务端已轮换的过期凭证同样满足该条件，于是形成「抓取失败 → 提示扫码 → 工具秒退宣称已更新 → 抓取依旧失败」的死循环。现改为用业务接口回执做权威验证。
- **空回执被误判为故障**：实测出现 `{"content": null, "msg": "", "ret": 0}`（HTTP 通、`ret=0`、无 content），原先同样落进 `SOURCE_UNAVAILABLE`，让偶发抖动看起来像数据源挂了。现先原地重试一次，仍为空则按 `not_found` 语义上报（属正常情况，不计入 `failed_targets`）。
- **`run_task` 路径在事件循环线程里调用 Playwright 同步 API**：`_run_full_flow` / `_run_scrape` 原先同步调用采集流程，而 Playwright 同步 API 在 asyncio 事件循环中会抛 `Sync API inside the asyncio loop`；该异常还会被 `refresh_cookies` 内部 `except` 吞掉，退化为「静默续期失败 → 误报需要扫码」。现全部改经 `asyncio.to_thread` 执行（工具调用路径原本已如此处理），同时消除了「长抓取阻塞整个后端事件循环」的隐患。

### Changed
- **不再因「已够 N 篇」提前停止翻页**：实测单页回执内同一公众号条目的时间序列**严重非单调**（西小电星球第 1 页依次 `09-07 / 09-09 / 09-11 / 08-31 / 07-13 …`；西电青年 `08-14 / 08-24 / 09-10 / 09-09 / 2025-04 / 2023-03`），即回执为**相关度序**而非时间序。提前停止会静默漏掉更新时间更晚、但排序更靠后的文章，因此改为翻满 `max_pages` 后再按发布时间降序截断。
- 抓取节奏加入随机抖动；网络异常与 HTTP 异常均带宽容重试（最多 3 次、递增退避），单个目标号失败不影响整轮；公众号切换间隔由 `[5, 8]` 秒调整为 `[8, 12]` 秒。
- 限流与登录失效的处置彻底分离：仅 `rate_limited` 做递增退避重试，且提示「稍后重试即可，**无需重新扫码**」；只有 `auth_expired` / 凭证缺失才引导扫码。
- 接口与翻页契约均由真实登录态实测确认：回执顶层 `ret` 恒为 `-1`，成功判定必须看 `content` 段；翻页需把上一页的 `content.offset` / `content.cookies` / `content.searchID` 原样回传为请求侧 `offset` / `searchcookies` / `searchid`（请求侧字段名为小写 `searchid`，仅传 offset 无效）。`errCode` 仅使用**已实测确认**的取值（`-2012` = 登录超时），其余数值一律不作为判定依据。
- 产物内每号条目按 `update_time` 降序重排（接口原始顺序为相关度序）。
- **修正误导性 Agent 指引**：`agent_core.py` 与 `backend/agents/xidian_agent.py` 中「run_wechat_scraper 返回 count 为 0 即代表没有新通知」的说明，在新语义下会直接掩盖断流，已改为按 `error_type` 区分「确实无新文章」与「抓取失败」；`tools_config.py` 中 `run_wechat_scraper` / `harvest_wechat_session` 的描述同步更新。
- `configs/settings.yaml` 的 `collectors.wechat.delay_range` 同步为 `[8, 12]`（`_deep_merge` 以文件值覆盖默认值，不同步则不生效）；`backend/api/v1/config_api.py` 的默认值同步。
- 凭证落盘字段随档案完整同步（由 6 个增至 10 个，含 `wr_avatar` / `wr_gender` / `wr_localvid` / `wr_name`），更贴近真实浏览器特征以降低风控概率；`configs/` 已在 `.gitignore` 中（第 213 行），凭证不会进版本库。
- `tools_config.py` 中 `run_wechat_scraper` / `harvest_weread_session` 描述同步更新：明确「`SESSION_EXPIRED` 表示**已自动尝试静默续期仍未成功**，此时才需扫码」「`NOT_FOUND` 属正常情况、不要报成故障」。
- 提示词新增两条约束：**尊重用户显式指令**（用户明确要求扫码/重试时必须照办，不得以「这样做没用」为由替用户拒绝——本次会话中用户说「扫码登录看看」被 Agent 拒绝；`agent_core.py` 第 6 条 / `backend/agents/xidian_agent.py` 第 8 条）与**回复简洁**（先给结论与关键事实——失败数量、`error_type`、错误码等可核验信息，再给必要说明；同一结论只讲一次，不反复论证、不长篇铺垫；`agent_core.py` 第 7 条 / `backend/agents/xidian_agent.py` 第 9 条）。

- `README.md` 新增「接口变更（v2.1）」章节：逐项说明 Agent 工具接口、采集编排层返回契约、新增模块公开接口、配置项、REST API 与前端路由的变化，并显式标注**破坏性变更**（失败路径不再返回 `success=true/count=0`，调用方须改按 `error_type` 判断）；版本说明同步更新至 v2.1.0。

### Removed
- 清理调试遗留物：删除根目录 47 个一次性探针产物（`_probe_*.py` 排查脚本、`_probe_*.json` 原始回执、`_probe_*.log` 运行日志、`_shot_*.png` 页面截图、`_snap_*.yaml` DOM 快照、`_weread_trial_run.log`，合计约 1.18 MB），以及 `.playwright-cli/` 会话缓存目录。清理前已全库检索确认**无任何正式代码引用**这些文件；其中 `_probe_browser_state.json` / `_probe_weread_*_result.json` 含登录态快照，一并清除。`_title_keep.bat` 为 2026-06-27 的既有文件、非本次遗留，予以保留。
- `.gitignore` 新增 `_probe_*` / `_shot_*` / `_snap_*` / `.playwright-cli/` 忽略规则——原先只忽略了 `.playwright/`，导致上述产物每次调试都会污染 `git status`。

### Test Results
```
【真实通道实测】
9/9 目标公众号精确命中，无一条非目标号文章混入；
翻 2 页共取回 137 篇，最新一条为 26 分钟前发布，字段（标题/链接/秒级时间戳/aid）完整；
单页回执固定 15 条，15 条并非硬上限（翻页实测可拿到全新内容）。

【编排层状态回归】产物隔离到临时文件，除真实分支外以 monkeypatch 模拟
1. 凭证缺失       → success=false, error_type=AUTH（不进入抓取循环）
2. 通道不可用     → success=false, error_type=SOURCE_UNAVAILABLE + failed_targets
3. 持续限流       → success=false, error_type=RATE_LIMITED
                    检索调用 6 次 = 2 目标 ×(1+2 次重试)，证明递增退避确实生效
4. 通道正常无文章 → success=true, count=0（唯一允许的 count=0，不报失败）
5. 部分失败       → success=true, count=2, failed_targets=[西电社团(rate_limited)]

【登录态失效根因定位与自愈验证】2026-09-13 17:05
同一时刻两套 cookie 请求同一接口（决定性证据）：
  [落盘 cookie]       -> {"errCode":-2012,"errMsg":"登录超时"}   ← 被拒
  [浏览器档案 cookie] -> {"content":{...}}                       ← 正常
  两边值不同的字段: ['wr_gid', 'wr_skey']  → 服务端轮换所致
页面上下文内调用业务接口同样正常 → 排除「数据源故障」与「请求特征不被认可」两种猜测。
修复后真实抓取：首个目标触发 -2012 → 静默续期 → 业务接口验证通过 → 重试成功，
最终 9/9 目标命中、43 篇；此前偶发空回执的「西电社团」本次正常命中 5 篇。

【线程池必要性对照】
反例（直接在 asyncio 事件循环中调用）：
   ⚠️ 静默续期失败: It looks like you are using Playwright Sync API inside the asyncio loop.
   → 返回 False（异常被吞，表现为「需要扫码」，症状极具迷惑性）
正例（经 asyncio.to_thread）：凭证保存成功 → 业务接口验证通过 → 返回 True
```

---

## [2026-07-01] v5.3：优化默认排序体验

### Changed
- **默认排序改为更直观的时间序**：
  - `upcoming`：开始时间升序（最近即将到来的在前）
  - `running`：开始时间升序
  - `recently_ended`：**结束时间降序**（最近结束的在前，而不是旧赛事排前面）
- 新增 `_sortable_time()` 辅助函数，确保非 ISO 格式的 `start_time` 也能正确参与排序

---

## [2026-07-01] v5.2：请求重试机制

### Fixed
- **偶发 WinError 10053 导致刷新全空** — CTFtime 偶尔拒绝连接（`ConnectionAbortedError(10053)`），`scrape_page` 一次失败即返回 `[]`，导致缓存被清空。新增指数退避重试（1s/2s/4s，最多 3 次），单次网络波动不再导致数据丢失。

---

## [2026-07-01] v5.1 Hotfix：upcoming 页面日期解析失败导致全部消失

### Fixed
- **upcoming 页面 56 条全部被过滤（严重回退）** — v5 中 `_parse_ctftime_date` 只支持 `Month DD, YYYY` / `DD Month, YYYY` 等带年份的对称格式，但 upcoming 页面的日期格式为 `03 July, 21:00 UTC — 04 July 2026, 06:00 UTC`（**前半部分没有年份**），解析全部失败 → `compute_status` 返回 `"unknown"` → 56 条全部被过滤
  - `_parse_ctftime_date()` 新增 3 种不对称格式：
    - `DD Month — DD Month YYYY`（upcoming 页面最常见）
    - `Month DD — Month DD YYYY`
    - `DD-DD Month YYYY`
  - 清理步骤优化：连带去除时间前的逗号 `, 21:00 UTC` → 空
- **upcoming 页面宽容策略** — 即使 `compute_status` 返回 `"unknown"`（极端情况），upcoming 页面的事件也保留并标记为 `"upcoming"`，因为该页面本身就是未来赛事列表

### Test Results
```
03 July, 21:00 UTC — 04 July 2026, 06:00 UTC  → upcoming ✅
06 July, 00:00 UTC — 08 July 2026, 00:00 UTC  → upcoming ✅
28 June, 21:00 UTC — 30 June 2026, 21:00 UTC  → recently_ended ✅
May 1-7, 2026                                 → expired ✅ (v5 修复未破坏)
```

---

## [2026-07-01] CTF 时间表 v5：日期解析修复 + 异步刷新 + 翻页逻辑修正

### Fixed
- **`compute_status` 误判过期赛事为 upcoming（核心 Bug）** — 很多赛事日期列只有纯文本（如 "May 1-7, 2026"），没有 `<span data-utc>` 标签，导致 `start_time` 只有字符串 `date_text` 而非 ISO 时间戳。`compute_status` 中 `datetime.fromisoformat("May 1-7, 2026")` 抛异常 → `start_dt = None` → 直接 `return "upcoming"`，所有时间解析失败的历史赛事都被标记为 upcoming
  - 新增 `_parse_ctftime_date()` 函数：支持 "July 01, 2026" / "01 July, 2026" / "July 01-07, 2026" / "July 01, 2026 — July 07, 2026" 等 CTFtime 常见格式
  - `parse_event_row()` 新增策略 2：`<span data-utc>` 缺失时，通过正则解析 `date_text` 生成 ISO 时间戳
  - `compute_status()` 重构：时间完全不可解析时返回 `"unknown"` 而非 `"upcoming"`，并在下游过滤
- **主列表翻页误判** — 第 2 页因去重后 `added == 0`，但日志误判为"后续页面均为过期赛事"。修复：`added == 0` 时直接停止翻页，不再依赖 `all_expired` 判断
- **前端刷新超时** — `/refresh` 同步执行补抓 Official URL（30+ 秒），超前端 axios 30s timeout。改为异步模式：
  - `POST /refresh` 立即返回，后台线程执行
  - `GET /refresh/status` 新增端点，前端每 2 秒轮询进度
  - `CtfPage.tsx` 显示刷新进度提示（带 spinner），完成后自动重载数据

### Changed
- `backend/api/v1/ctf.py` [REWRITE v5] — 新增 `_MONTH_MAP` / `_parse_ctftime_date()` / `_try_parse_event_time()` / `_try_parse_date_text()` 辅助函数；`refresh_cache()` 增加 `unknown` 过滤与 `_refresh_state` 进度更新；新增 `_do_async_refresh()` 后台线程 + `/refresh/status` 端点
- `frontend/src/api/ctf.ts` [UPDATE] — 新增 `RefreshStatusResponse` 类型 + `refreshStatus()` 方法；`refresh()` 返回值新增 `refreshing` 字段
- `frontend/src/pages/CtfPage.tsx` [UPDATE] — `handleRefresh` 改为异步轮询模式；新增 `refreshing` / `refreshPhase` 状态 + 进度提示卡片；刷新按钮 pending 态优化

---

## [2026-06-30] CTF 时间表 v4.1：修复旧缓存 status 空字段导致的渲染崩溃

### Fixed
- **`CtfPage` 崩溃：`Cannot read properties of undefined (reading 'dot')`** — 旧版缓存（v3 生成）中事件 `status` 字段为空字符串 `""`，`STATUS_CONFIG[""]` 返回 `undefined`，导致 `cfg.dot` 报错
  - 后端加固：`get_events` 加载缓存后自动补算所有缺失/无效 `status` 的事件（`compute_status` 兜底）
  - 前端加固：`cfg = STATUS_CONFIG[event.status] || STATUS_FALLBACK`，灰点 + "未知" 兜底

---

## [2026-06-30] CTF 时间表 v4：抓取范围优化 + 状态灯 + 自定义暗色下拉

### Changed
- **抓取范围精简** — 不再全量归档，仅保留 upcoming（即将开始）+ running（进行中）+ recently_ended（近两周内结束），过滤掉老旧归档赛事
- `backend/api/v1/ctf.py` [REWRITE] — 新增 `compute_status()` 按 start_time/end_time 自动计算状态；`refresh_cache()` 改为「upcoming 页面 + 主列表逐页过期即停」双源抓取，大幅减少无效请求
- **暗色主题自定义下拉** — `CtfPage.tsx` 内置 `SortDropdown` 组件，替换原生 `<select>`：深色背景 + 白字选项 + hover 高亮 + 选中态 accent 色 + 点击外部关闭
- **绿/黄/红状态灯** — 每张卡片名称左侧：🟢 即将开始 / 🟡 进行中（带 pulse 动画） / 🔴 近期结束；筛选栏下方新增状态统计条
- `frontend/src/api/ctf.ts` [UPDATE] — 新增 `CtfStatus` 类型 + `status` 字段 + `status_filter` 参数

---

## [2026-06-30] CTF 时间表 v3：缓存 + 筛选 + 大头钉 + Official URL

### Added
- **JSON 缓存机制** — `data/ctf_cache.json`：完整赛事列表持久化，避免每次访问都抓取 CTFtime
- **每天 12:00 自动刷新** — 后端 `should_refresh()` 逻辑：若缓存时间 < 今日正午 ≤ 当前时间则自动刷新，未准时执行则在当天首次访问时补刷新
- **完整列表抓取** — `scrape_list_pages()` 分页抓取 `/event/list/`（最多 5 页 ≈ 500 条），覆盖历史 + 即将到来的所有赛事
- **Official URL 懒抓取** — `scrape_official_url()` 从赛事详情页抓取官方链接，每轮刷新至多补抓 20 条（含多策略回退：Official 文本匹配 → nofollow 外链 → 外链兜底）
- **大头钉（关注/置顶）** — `POST /api/v1/ctf/pin/{event_id}` 切换大头钉，`data/ctf_pins.json` 持久化；已关注赛事强制置顶，卡片边框橙色高亮
- **筛选栏**（页面最上方）：
  - 排序方式：默认日期 / 高权重优先 / 低权重优先 / Jeopardy 优先 / Attack-Defense 优先 / Hack quest 优先
  - 仅高权重（≥25）复选框
  - 赛制多选过滤（Jeopardy / Attack-Defense / Hack quest）
  - 一键清除筛选
- **前端卡片增强**：赛事名称改为可点击链接（优先 official_url，回退 ctftime_url），带 ExternalLink 图标；关注赛事卡片带琥珀色边框 + ring 光晕

### Changed
- `backend/api/v1/ctf.py` [REWRITE] — 完全重写：缓存系统 + 分页抓取 + Official URL 懒抓 + 大头钉 API + 过滤排序参数
- `frontend/src/api/ctf.ts` [REWRITE] — 新增 `getEvents(params)` / `refresh()` / `togglePin()` / `getPins()`，更新类型定义
- `frontend/src/pages/CtfPage.tsx` [REWRITE] — 筛选栏 + 大头钉交互 + Official URL 链接 + 缓存时间显示 + 刷新提示区分成功/错误

---

## [2026-06-30] 新增 CTF 时间表 + 仪表盘状态灯增强

### Added
- **CTF 时间表** — 全新模块，位于"情报报告"与"Agent 对话"之间：
  - `backend/api/v1/ctf.py` — 从 CTFtime.org 抓取即将到来的 CTF 赛事列表，解析名称/日期/赛制/地点/权重/备注，返回结构化 JSON
  - `frontend/src/pages/CtfPage.tsx` — 赛事时间表面板：卡片式列表展示，赛制颜色区分（Jeopardy/Attack-Defense/Hack quest），线上/线下图标标识，高权重赛事奖杯标记，底部附 CTFtime 源链接
  - `frontend/src/api/ctf.ts` — 类型安全的 API 模块
  - `backend/main.py` [UPDATE] — 注册 `/api/v1/ctf` 路由
  - `frontend/src/App.tsx` [UPDATE] — 注册 `/ctf` 路由
  - `frontend/src/components/Layout.tsx` [UPDATE] — 导航栏新增"CTF 时间表"（Trophy 图标）

### Changed
- `frontend/src/pages/DashboardPage.tsx` [MODIFY] — 情报列表状态灯由二态升级为三态：
  - 🟢 绿色 (`pushed`) = 已推送
  - 🔴 红色 (`failed`) = 推送失败
  - 🟠 橙色 (其他) = 待推送
  - 每种状态灯添加对应 glow 发光效果 + title tooltip

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
