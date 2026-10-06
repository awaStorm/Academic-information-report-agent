# Bug 修复日志

> **维护说明**: 每次发现并修复 Bug 后，请在此文档中记录，帮助团队避免重复踩坑。

---

## [2026-10-06] v2.3.4：Agent 对话不再裸 500（httpx 走了系统代理）+ 微信读书扫码崩溃真因（浏览器与档案版本错配）

> 背景：用户两次报障——① Agent 对话返回 `HTTP 500`，日志为 `httpx.ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING]`；② 微信扫码登录弹不出窗口，报 `BrowserType.launch_persistent_context: Target page, context or browser has been closed`。扫码问题此前曾被归因为「档案目录被残留进程锁定」，并据此给出「关闭所有 Chrome 窗口」的无效指引；本轮定位到真因并纠正该结论。

### 一、Agent 对话 500：httpx 默认读取 Windows 系统代理

**根因**：[xidian_agent.py](../../backend/agents/xidian_agent.py) 等处直接使用 `OpenAI(api_key, base_url)`，其内置 httpx 客户端 `trust_env=True`。在 Windows 上 httpx 会经 `urllib.request.getproxies()` 读取**注册表里的系统代理**（实测 `ProxyEnable=1` / `ProxyServer=127.0.0.1:7897`，由 Clash Verge 提供），于是每句 LLM 请求都被塞进代理隧道；节点抖动的那一瞬间 TLS 握手以 `UNEXPECTED_EOF_WHILE_READING` 失败，冒泡为 `openai.APIConnectionError`，最终打成 HTTP 500，前端只看到一句「发送失败」。而 `api.deepseek.com` **直连 0.76s 即返回 200**（实测），把 LLM 可用性绑在一个会抖动的本地代理上没有任何收益。

**修复**：

- 新增统一客户端工厂 [llm_client.py](../../src/utils/llm_client.py)：
  - `build_llm_client()` 默认 `trust_env=False` **绕开系统代理**，读超时放宽至 600s（本项目 `max_tokens` 配到 30000，宁可等也不打断）。需要代理时设 `LLM_USE_SYSTEM_PROXY=1` 即恢复原行为。
  - `call_with_retry()`：**仅对连接类错误**做 2s→4s 指数退避重试（SDK 自带退避是 0.4s/0.8s 量级，扛不住代理节点切换）；业务错误不重试。重试过程经 WebSocket 推 `warn` 日志，界面不再像卡死。
  - `describe_llm_error()`：把连接类异常翻译成可操作的提示（含「关闭系统代理后重试」）。
- 四处客户端构造统一收口：`backend/agents/xidian_agent.py`、`agent_core.py`、`src/agent/analyzer.py`（主分析 + 多模态识图）。
- [agents.py](../../backend/api/v1/agents.py)：连接类异常不再抛 500，改为返回 `{success:false, error_type:"LLM_UNREACHABLE", message:"..."}`，前端按既有 `success=false` 路径展示可操作文案；`run_agent_task` 同步补齐（接口层双保险，防止将来新增 Agent 再漏）。
- [client.ts](../../frontend/src/api/client.ts)：错误文案补取 FastAPI 的 `detail`，不再只显示「Request failed with status code 500」。

### 二、扫码窗口弹不出：Playwright 与持久化档案的 Chromium 版本错配（真因）

**排查与错误结论的纠正**：先按「档案被残留进程锁定」排查——实测档案**无任何进程占用**、`Local State`/`History`/`Preferences` 均可独占打开、无 `SingletonLock` 残留，且档案 `Crashpad\reports` 下有 6 份**浏览器崩溃转储**（异常码恒为 `0x80000003` STATUS_BREAKPOINT、异常地址恒为 `0x7FFFE460A504`），说明浏览器是**自己主动 abort**，而非被别人锁住。当时据时间相关性误判为「NVIDIA 容器崩溃连带覆盖层注入」，**该结论是错的**，本条予以纠正（NVIDIA 侧全部时间点的相关性经复核均为巧合，未对用户显卡配置做任何改动）。

**真因（三步实验 100% 复现）**：

1. 项目 `venv` 装的是 `playwright 1.58.0` → 绑定 chromium **1208**（Chromium `145.0.7632.6`）；
2. 系统 Python 装的是 `playwright 1.59.0` → chromium **1217**（Chromium `147.0.7727.15`）；
3. 档案 `configs/weread_profile` 的 `Last Version` 曾被 147 写过，此后再用 145 **有头启动必然 abort**。

实验记录：全新空档案 + 1208 有头 → **成功**；用 1217 打开同一档案（写入 `Last Version=147.0.7727.15`）；再换回 1208 有头 → **启动即崩**。Playwright 只报 `Target page, context or browser has been closed`，随后 `taskkill` 提示「找不到进程」（进程已自行崩溃）——这正是用户看到的现象全貌。**无头模式不受影响**（`chrome-headless-shell` 不校验档案版本），所以症状表现为「静默续期一直正常，唯独扫码登录必崩」。

**修复**：

- `venv` 升级 `playwright` 1.58.0 → **1.59.0**，与档案版本对齐；升级后 venv 有头/无头均启动成功，**新增崩溃转储 0**。
- [requirements.txt](../../requirements.txt)：`playwright>=1.40.0` → **`playwright==1.59.0`**（档案与 Playwright 绑定的 Chromium 强耦合，必须精确锁版本，已附原因注释）。
- [weread_harvester.py](../../src/collectors/sessions/weread_harvester.py) 新增**版本预检**：比较档案 `Last Version` 与本次 Chromium 版本（取自 Playwright 自带 `browsers.json` 的 `browserVersion`），检测到降级时打印明确警告，有头模式**只试 1 次**即抛出点名「版本错配」的 `RuntimeError` 并附可执行修法，不再白刷崩溃转储。

### 三、顺带加固（同一文件，防止衍生问题）

- **启动参数**：补 `--disable-gpu` / `--disable-gpu-compositing` / `--disable-features=CalculateNativeWinOcclusion` 等稳定性开关（扫码只需渲染静态二维码，不用 GPU 无功能损失）。需说明：证据显示崩溃与 GPU 无关，此项属纯加固。
- **并发踩踏**：新增类级 `threading.Lock` 串行化浏览器会话。此前 `run_harvest`（有头、等扫码最长 10 分钟）与 `refresh_cookies`（无头静默续期）可并发，后者一旦启动失败触发自愈，会调用 `_kill_orphan_browsers()` 把**正在等用户扫码的有头窗口**一起杀掉（匹配条件「进程名含 chrome 且命令行含 weread_profile」对该窗口完全成立）。现在：续期侧拿不到锁直接跳过；扫码侧最多等 90s 后如实返回可读失败。
- **自愈重试**：`_launch` 由「固定重试 1 次」改为最多 3 次、退避递增；失败提示不再一口咬定「档案被锁」，而是把「未发现占用进程」与「已清理孤儿进程」分开陈述，并指向 `Crashpad\reports` 转储作为判据。

### 四、新增：浏览器环境版本自检 + 自动对齐 + Agent 工具（同日追加）

> 起因：用户提出「我们应该加一个启动时自动更新/对齐，或者给 agent 选择更新/对齐的能力」。先把「能不能无损救回旧档案」测清楚，再据此定型。

**实测结论（决定了方案只能这么做）**：把一份被 147 写过的档案，① 改回 `Last Version=145.0.7632.6`、② 乃至直接删除 `Last Version`，再用 145 打开**仍然启动即崩**（每次都新增 1 份 Crashpad 转储）。即不兼容来自档案**内部 schema**，不是那个标记文件——**「旧版本打开新档案」无法无损修复**，所以唯一可行的方向是让**运行版本 ≥ 档案版本**。

**Added**：

- **自动对齐**（[weread_harvester.py](../../src/collectors/sessions/weread_harvester.py) `_resolve_compatible_chromium`）：有头启动前，从本机 `ms-playwright` 里扫描已安装的 `chromium-<rev>`，挑一个「修订号 ≥ 档案最后使用者、且尽量贴近」的二进制，用 `executable_path` 启动。**无需人工干预，且保留登录态**（不必重新扫码）。若本机确实没有足够新的二进制，才如实报错。对齐所用的二进制起不来时会自动退回 Playwright 自带版本，保证「对齐」只做增强、不成为新的故障点。
  - 判定用**修订号**而非版本号：档案 `Last Browser` 记录的 `chromium-<rev>` 与 Playwright 修订号可比，而档案的 `Last Version`（`147.0.7727.15`）与修订号之间没有离线映射表。
- **环境自检** `WereadHarvester.diagnose_browser_env()`：**纯读取**（不启动浏览器、不改文件），返回 `profile_version` / `profile_writer_revision` / `running_revision` / 已安装修订号列表 / 崩溃转储数量，以及结论 `status`：`ok`（版本一致）、`auto_align`（档案更新但本机有新版，会自动对齐）、`needs_rebuild`（无法对齐，只能升级 Playwright 或重建档案）、`no_profile`、`unknown`。
- **后端启动自检**（[backend/main.py](../../backend/main.py)）：启动时调用上述自检并记日志，错配提前告警；用 try/except 包住，**自检失败绝不影响后端启动**。
- **档案重建** `WereadHarvester.rebuild_profile()`：**改名备份**为 `<profile>.bak-YYYYmmdd-HHMMSS` 而不是删除（改名失败即中止，绝不静默丢用户数据）；有浏览器会话在跑时直接拒绝，不硬来。
- **Agent 工具** `align_weread_browser_env`（[tools_config.py](../../tools_config.py)，工具总数 12 → 13）：`action=diagnose`（默认，只读自检，附 `next_step` 指引）/ `action=rebuild`（破坏性，需先征得用户同意）。工具描述里写明了症状特征，便于 Agent 在 `harvest_weread_session` 报「版本错配」时自行定位。

**Fixed（本轮新发现的真实缺陷）**：`Last Browser` 是 **UTF-16LE** 编码，而 `Last Version` 是 UTF-8。按 UTF-8 通读会得到夹着 `\x00` 的字符串，正则永远匹配不上 → 版本判定会**静默失效**（表现为 `status=unknown`、自动对齐不触发）。已抽出 `_read_mixed_text()` 按「字节里是否含 NUL」自动选择解码方式，两种编码都能吃。

### 五、文档与仓库卫生（为 GitHub 部署检查做准备，同日追加）

**Added / Changed（仅文档与忽略规则）**：

- [README.md](../../README.md)：补 v2.3.4 版本说明；「功能概览」补事件日历、LLM 连接韧性、浏览器环境自检与自动对齐三条；「项目结构」按当前代码重写（补 `calendar_api.py` / `CalendarPage.tsx` / `calendar.ts` / `websocket.ts` / `src/utils/llm_client.py` / `weread_profile` / `start.bat` / `push-to-github.bat` 等）；「系统架构」补前端路由清单；「快速开始」补 `playwright` 精确锁版本的原因与升级步骤、`start.bat` 一键启动、`configs/settings.yaml` 缺失自动生成；新增「常见问题」表（对话 500 / `LLM_UNREACHABLE` / 扫码窗口弹不出 / 版本无法对齐 / `--reload` 不生效）；新增「LLM 连接韧性 与 浏览器环境对齐（v2.3.4）」章节，含 LLM 客户端工厂接口表、降级契约、版本错配三步实测表、`diagnose_browser_env` 的 `status` 取值表、`align_weread_browser_env` 两个动作说明。
- [.gitignore](../../.gitignore)：把**本地编辑器 / IDE 工作区目录整体**加入忽略（不再保留任何例外，目录内文件一律不进仓库），并同步清理注释措辞；补 `*.tsbuildinfo`（`tsc -b` 增量缓存，正常情况下落在 `node_modules/.tmp` 内）。
- [.env.example](../../.env.example)：补可选开关 `LLM_USE_SYSTEM_PROXY`（留空即直连 LLM、绕开系统代理），与 README 的说明对应。
- **文档脱敏与悬空引用清理**：README 与本文档（含历史条目）中原先出现的本地开发工具 / 编辑器名称已全部替换为中性表述（如「本地编辑器 / IDE 工作区数据」）；同时清理了指向已被忽略的本地方案文档的引用（原文「计划书第 67/109/138 行」改为语义等价的独立描述），避免对外仓库出现无法解析的引用。

**部署安全检查结论（本轮核查，非代码改动）**：

- `configs/`、`data/`、`reports/`、`.env` 均**未被 git 跟踪**；全库历史中 `configs/` 仅出现过 `configs/.gitkeep`（占位文件），**凭证从未进入版本库**。
- `.env.example` 全部为空占位符；`push-to-github.bat` 不含任何令牌（依赖 git 凭据管理器），且自带 `.env` / `configs/` 泄露前置检查。
- 仓库内体积最大的被跟踪文件为 `assets/avatars/user.jpg`（253 KB），无大文件隐患；`frontend/dist`、`*.tsbuildinfo`、`node_modules` 均已被忽略。
- 全新克隆可直接运行：`configs/settings.yaml` 缺失时由 `config_loader.load_config()` 自动写入默认配置，`configs/` 与数据目录由各写入点在需要时 `makedirs`。

### 验证记录

- `llm_client` 16 项断言全过，含**故障场景回归**：把 `HTTPS_PROXY` 指向死端口后，原生 `OpenAI()` 客户端如预期失败，而 `build_llm_client()` 走直连**依然成功**。
- 版本预检 12 项断言全过：真实环境无误报；伪造 `Last Version=999.0.0.0` 时，有头仅尝试 1 次即抛出点名「版本错配」的错误，无头保留 3 次宽容重试。
- **对齐能力 29 项断言全过**（`aira_align_test.py`）：真实环境判定 `ok`；已安装 chromium 扫描按修订号降序且不混入 headless-shell；档案 1217 vs 运行 1208 时**正确挑出 chromium-1217**；`needs_rebuild` 文案给出两条修法；四种 `status` 分支均正确；重建在临时目录上验证「备份而非删除」+「有会话时拒绝」；工具 schema/分发/`next_step` 均正确。
- **对齐集成实测**：强制构造「档案更新 + 本机可对齐」场景后真跑一次有头启动 → 日志显示 `✅ 版本对齐：…已自动改用本机 chromium-1217 启动`，页面正常打开「微信读书」，**新增崩溃转储 0**。
- 实机端到端：后端重启后启动日志出现 `✅ 微信读书扫码环境自检: 档案修订号 1217 <= 运行修订号 1217，版本一致，可直接扫码。`；`/health`、`/openapi.json` 均 200；`POST /api/v1/agents/xidian/chat` → **HTTP 200 / success=true / 回复「收到」**；venv 下 `_launch` 有头、无头均成功。
- `python -m compileall` 通过；前端 `tsc -b` 通过；lint 无新增错误。

### 发现但本轮未改动（待办）

- **后端 `--reload` 实测不生效**：触碰 `backend/main.py` 时间戳后 12 秒内 worker 无重启，因此本轮修复必须**手动重启后端**才能生效（叠加 venv 依赖已变更，重启无论如何都是必需的）。疑因 uvicorn 监视整个项目根（含 `frontend/node_modules` 约 1.18 万文件、`venv`）导致 Windows 目录监视缓冲区溢出、watcher 失效。
- **`--reload-exclude` 在 Windows 上不可用**：uvicorn 的 click 层会对含通配符的参数做 **Windows 通配符展开**，`--reload-exclude frontend/*` 会被展开成一串路径并报 `Got unexpected extra arguments (...)`（已实测复现）。若需收敛监视范围，应改用不含通配符的 `--reload-dir backend --reload-dir src`（代价：根目录的 `main.py` / `agent_core.py` / `tools_config.py` 改动不再自动重载）。
- 档案 `Crashpad\reports` 累积 10 份崩溃转储（各约 2.3 MiB；`configs/` 已在 `.gitignore`），确认无用后可自行清理。

---

## [2026-09-21] v2.3.3：expired 状态链路统一 —— 读取时重算状态，四处过滤口径对齐

> 背景：`NNS/TFC/SUNCTF 2026`（均 9/6 结束）在 CTF 页显示灰点「未知」。排查确认不是解析失败——它们是 `expired`（结束超 14 天、滑出 `recently_ended` 窗口），而前端 `STATUS_CONFIG` 只认三态，`expired` 落入 `STATUS_FALLBACK` 被渲染成「未知」。

### 根因：状态快照冻结 + 四处过滤口径不一致

- **四处对 expired 的处置各不相同**：`refresh_cache` upcoming 侧（丢弃）、主列表侧（丢弃）、`get_events`（放行）、`calendar_api`（丢弃）。导致同一条 `expired` 赛事 CTF 页可见、日历页不可见，且可见时标签是「未知」兜底。
- **status 是抓取时的快照，读取时不重算**：`get_events` 仅在 status 缺失/非法时补算。事件在两次刷新之间跨越 14 天线时，缓存值冻在 `recently_ended`，`expired` 实际上到不了前端——单纯加前端标签是死代码。

### 修复（统一策略：unknown=脏数据全滤；expired=合法第四态，读取链路放行并标注「已结束」）

- **读取时重算状态**（[ctf.py](../../backend/api/v1/ctf.py) `get_events`）：无条件 `compute_status`，就地完成 running→recently_ended→expired 迁移；重算得 `unknown` 时回退缓存值——upcoming 页脏数据在 refresh 时已被宽容为 upcoming，读取时不能反杀。
- **`calendar_api` 对齐**：同样读取时重算 + 只滤 `unknown`，`expired` 赛事在日历的历史日期上显示「已结束」。
- **refresh 两处过滤明确为「采集边界」**（行为不变）：缓存只收 14 天窗口内数据，"已结束"的展示由读取路径现算负责——这正是「刷新后 expired 消失」的预期保留策略；若放开会把主列表数月历史全部灌入缓存。
- **前端**：[CtfPage.tsx](../../frontend/src/pages/CtfPage.tsx) `STATUS_CONFIG`/统计条补 `expired`（灰点「已结束」，仅在 >0 时显示计数）；[CalendarPage.tsx](../../frontend/src/pages/CalendarPage.tsx) 徽标映射补 `expired`；[ctf.ts](../../frontend/src/api/ctf.ts) `CtfStatus` 类型补 `"expired"`；`status_filter` 参数文档与默认排序（expired 置底、按最近结束在前）同步支持。

### 验证记录

- 合成缓存 10 项断言全过：出窗事件快照 `recently_ended`→迁移 `expired` 且保留展示；快照 `running`→迁移 `recently_ended`；不可解析 start 回退缓存值不被过滤；默认排序 expired 在 recently_ended 之后；`status_filter=expired` 精确命中；日历同步展示 expired 并正确迁移状态。
- 真实缓存副本演练：47 upcoming + 14 recently_ended，无异常迁移（当日 09:54 已刷新，暂无出窗赛事）。
- 后端 `compileall`、前端 `tsc -b && vite build` 通过；lint 无新增错误。

---

## [2026-09-21] v2.3.2：CTF 日期解析改用 python-dateutil

> 背景：原计划要求时间解析层使用 `python-dateutil` 处理自然语言日期。此前出于「标准库 `re` 够用」的判断改用了手写正则，按用户要求回退该自选方案，切换至 dateutil。

### Changed

- [ctf.py](../../backend/api/v1/ctf.py)：删除手写月份映射 `_MONTH_MAP` 与 7 段日期正则 `_parse_ctftime_date_only()`，改用 `dateutil.parser.parse(fuzzy=True)` 实现 `parse_date_range()`（106 行 → 51 行）。
- [requirements.txt](../requirements.txt)：显式声明 `python-dateutil>=2.8.0`（此前仅为传递依赖，未声明）。

**保持不变的关键约定**（切换时不得破坏）：

- **日期与时刻职责分离**：`parse_date_range` 只产出日期（`end` 落 `23:59:59`），真实 `HH:MM` 仍由 `_apply_clock()` 从**原始文本**按出现顺序回填。若让 dateutil 直接吞掉时刻，会重新引入「赛事已结束却判 `running`」的 Bug（v2.3.1 修的那个）。
- **缺省年份取文本中的显式年份**（取最后一个），覆盖 `25 Sept. — 27 Sept. 2026` 这类「前半缺年份」的非对称写法。
- **仅用 em/en dash 切分前后段**：普通连字符属于日期内部（如 `Jul 3-5, 2026`），不能当分隔符，需转交同月区间正则处理。
- 对外函数 `_parse_ctftime_date` / `_try_parse_date_text` 签名与行为不变，[calendar_api.py](../../backend/api/v1/calendar_api.py) 无需改动。

### 验证记录

- **回归基线**：以切换前解析器对 `data/ctf_cache.json` 全部 **61 条**真实日期文本的输出为基线，切换后逐条比对，**差异 0 条**。
- **格式覆盖**：`Jul 3-5, 2026`、`July 01-07, 2026`、`July 01, 2026`、`01 July, 2026`、`May 1-7, 2026`、`July 01, 2026 — July 07, 2026`、`July 01, 2026, 12:00 UTC — July 03, 2026, 12:00 UTC`、`03-07 July 2026`、`03 July, 21:00 UTC — 04 July 2026, 06:00 UTC` 全部解析正确（时刻保留）。
- **健壮性**：`TBD` / 空串 / 纯符号输入返回 `(None, None)`，不抛异常。
- `python -m compileall` 通过；`calendar_api` 依赖导入正常。

---

## [2026-09-20] v2.3.1：CTF 时间解析修复 —— 结束时刻丢失导致状态误判与日历跨日

> 背景：用户反馈两点——① 日历中 9/20 的所有 CTF 都显示 `9/19 — 9/21 07:59（UTC）`，与 CTF 时间表里的原始文本不符；② `WATCHLIST` 在 CTFtime 上已经结束，但无论怎么刷新缓存都显示「正在进行」。

### 根因：解析层丢弃 `HH:MM UTC`，并把 end 硬编码为 23:59:59

- [ctf.py](../../backend/api/v1/ctf.py) 的 `_parse_ctftime_date` 在清洗阶段用 `re.sub(r',?\s*\d{1,2}:\d{2}\s*(?:UTC|utc)', '', text)` 剥掉时刻，随后 `end = datetime(..., 23, 59, 59)`。
- **后果一（状态误判）**：`WATCHLIST` 真实结束 `20 Sept. 03:30 UTC` 被存成 `2026-09-20T23:59:59`，膨胀约 20.5 小时，使 `compute_status` 的 `now <= end_dt` 恒成立而判为 `running`。刷新无效是因为每次刷新都在重犯同一个错。
- **后果二（日历跨日）**：`fmtDate` 用 `getHours()`（本地 UTC+8）渲染却标注「（UTC）」，`23:59:59 UTC` 被推到本地次日 `07:59`；再叠加 start 被抹平成 `00:00`，最终呈现 `9/19 — 9/21 07:59`。

### 修复

- **解析层保留真实时刻**：新增 `_apply_clock()`，按出现顺序从原始文本提取 `HH:MM` 回填（第 1 个给 start、第 2 个给 end，仅 1 个则两端共用）；原日期匹配逻辑原地拆为 `_parse_ctftime_date_only()`，由 `_parse_ctftime_date()` 组合二者。
- **旧缓存自愈**：`get_events` 的兜底修复从「仅 `start_time` 为纯文本」扩展到「`start=T00:00:00` + `end=T23:59:59` 且原文确实带时刻」的整天占位脏数据，现场重解析并回写缓存——**下次打开页面即自动修复，无需等待全量刷新**。
- **日历时区与启发式修正**（[CalendarPage.tsx](../../frontend/src/pages/CalendarPage.tsx)）：`fmtDate` 改用 `getUTC*()` 渲染以匹配「（UTC）」标签；同时**删除** `hasTime = !/T00:00:00/.test(iso)` 这一「用时刻恰好为午夜反推没有时刻」的错误启发式——`SUNCTF 2026`（`06 Sept., 00:00 UTC` 开赛）的开始时间会被它隐藏。现始终输出 `HH:MM`；`end_time` 为空时不再留下悬空的 `—`。

### 验证记录

- 全量 61 条赛事解析成功，`end < start` 异常 0 条，残留 `23:59` 占位 0 条，`end` 为空 0 条。
- 状态分布：`running 6 → 4`、`recently_ended 11 → 13`；`WATCHLIST`（`9/19 03:30 ~ 9/20 03:30`）与 `Cyber League 2026 - Major`（`~ 9/20 02:00`）由 `running` 正确回归 `recently_ended`。
- 日历渲染抽样（均 UTC）：`SUNCTF 2026 → 9/6 00:00 — 9/6 09:00`、`WATCHLIST → 9/19 03:30 — 9/20 03:30`、`LUN4R CTF Quals → 9/20 04:30 — 9/20 16:30`、单日赛 `end` 为空 → `9/19 03:30（UTC）`。
- 后端 `compileall` 通过；前端 `tsc -b && vite build` 通过；lint 无新增错误。

---

## [2026-09-18] v2.3.0：Agent 深度解读 —— 事件日期分离 + 事件时间轴 + 多模态识图

> 背景：用户希望 Agent 真正读懂内容，把「获取日期」与「事件发生日期」分离（日历按事件发生日期打点，解析不出则不进日历），并支持竞赛报名/初赛/决赛等多时间点事件链；同时希望 Agent 能识别通知图片中的信息。

### 核心改造：获取日期与事件日期彻底分离

- **数据模型**：`pushed_records` 幂等迁移新增 `event_date TEXT`（事件发生日期）与 `timeline TEXT`（JSON 时间轴数组）。`push_time` 保留为获取时间，两者语义独立。
- **Agent 解析**（[analyzer.py](../../src/agent/analyzer.py)）：系统提示词新增「事件日期与事件时间轴」约束，输出 schema 增加 `event_date`（主事件日期，无法识别填 null）与 `timeline`（`[{label, date, time}]` 数组，报名/初赛/决赛按时间顺序）。推送写入时 `event_date` 做兜底清洗（`null` 字符串/非 ISO → null）。
- **日历 API**（[calendar_api.py](../../backend/api/v1/calendar_api.py)）：情报事件分组从 `push_time` 改为 `event_date`。查询范围放宽（push_time 当月前后 ±90/±30 天），但只把 `event_date` 落在当月的记录归入日历；**`event_date` 为 null 的记录不进日历**（符合「无法识别就不加入」要求）。
- **前端展示**：仪表盘与日历详情面板均渲染「📅 事件时间轴」chip 流（`报名截止 9/25 23:59 → 初赛 10/1 → 决赛 10/15`）。

### 新增：多模态识图（可选增强，失败静默降级）

- **采集层**（[wechat_parser.py](../../src/processors/extractors/wechat_parser.py)）：`parse_single_article` 同时收集正文 `<img data-src>`/`<img src>` URL，存入 `images` 字段（微信正文图片常用 data-src 懒加载）。
- **分析层**（[analyzer.py](../../src/agent/analyzer.py)）：新增 `extract_text_from_images(item)`——若多模态开启，下载前 N 张图转 base64 data URI（微信防盗链需带 UA+Referer），调用独立多模态模型提取图片中的文字/日期/地点，追加到正文后送 LLM。**未开启/无图/调用失败均返回空串，绝不阻塞主流程**。
- **配置**（[config_loader.py](../../src/utils/config_loader.py) + [config_api.py](../../backend/api/v1/config_api.py) + ConfigPage）：新增 `analysis.multimodal` 配置（enabled / api_key / base_url / model / max_images），API Key/Base URL/Model 留空则复用主 LLM 配置；配置面板新增「多模态识图」折叠区。

### 第二阶段（同日补全）：timeline 节点级日历打点 + 节点跳转

> 本阶段的出发点：上一阶段只按主 `event_date` 打点、timeline 仅在详情面板静态展示，多阶段事件的时间点无法在日历上体现。

- **后端**（[calendar_api.py](../../backend/api/v1/calendar_api.py)）：情报分组循环重构——除主 `event_date` 外，遍历 `timeline` 每个带有效日期的节点，在节点所在日期桶各放一张卡片并附 `timeline_node={label,time}` 标记（前端据此显示「📌 此日节点」副标题）。
  - **去重**：`placed_dates` 集合保证同一记录同一天只出现一张卡片（主日期与节点同日、多个节点同日均不重复）。
  - **语义补全**：主 `event_date` 缺失/不在当月不再整条 `continue`——只要 timeline 节点本身带明确日期仍按节点打点（节点日期明确即「可识别」，符合「宁可漏不可错」原则）。
  - **查询窗口放宽**：push_time 窗口由前 90 天扩大到前 180 天，覆盖「提前数月通知、决赛在数月后」的跨月节点（如 8 月推送 12 月决赛）。
- **前端**（[CalendarPage.tsx](../../frontend/src/pages/CalendarPage.tsx)）：时间轴节点由静态 `<span>` 改为可点击按钮，点击跳转节点日期（`goToDate` 支持跨月，切换月份后自动加载该月数据）；无合法日期的节点保持不可点。节点打点卡片在标题下显示琥珀色「📌 此日节点：初赛 14:00」标记。类型见 [calendar.ts](../../frontend/src/api/calendar.ts) 的 `timeline_node` 字段。

### 第三阶段（健壮性修复）：timeline 脏数据防御 + 细节优化

> 代码审查发现：LLM 偶发输出非标准 timeline（如 `["报名", null]`）会导致 `render_markdown` 的 `node.get()` 抛 AttributeError 使**整轮分析失败**，且前端访问 `node.label` 会**页面白屏崩溃**。

- **P1（高，已修）**：
  - [analyzer.py](../../src/agent/analyzer.py) 新增 `_sanitize_timeline()`：只保留 dict 节点、字段强制字符串、斜杠日期（`2026/09/20`）归一为横杠、剔除空节点；在 LLM 结果解析后与 `render_markdown` 内两处收口（后者覆盖当日缓存恢复的旧条目）。`event_date` 入库清洗同步支持斜杠归一。
  - [database.py](../../src/agent/database.py)：`get_pushed_records_by_date_range` 解析存量 timeline 时过滤非 dict 元素并归一日期，防御旧库脏数据。
  - 前端 [DashboardPage.tsx](../../frontend/src/pages/DashboardPage.tsx) / [CalendarPage.tsx](../../frontend/src/pages/CalendarPage.tsx)：timeline 渲染前 `.filter(n => n && typeof n === "object")`，杜绝脏元素白屏。
- **P3（细节优化）**：① 日历 `totals.intel` 改为主卡片+节点卡片实际总数；② 跨月点节点跳转时，目标月数据加载期间右侧面板显示「加载中」而非瞬闪「当天暂无事件」；③ 主 `event_date` 与节点日期在日历 API 再做一次斜杠归一（双保险）。
- **P2（仅文档/界面说明，不改逻辑）**：配置页「多模态识图」区补充三点注意——保存后需重启后端、每条含图情报串行调用（含图多时耗时显著增加）、大图/接口异常自动跳过；README 新增「事件日期 / 时间轴 / 多模态（v2.3）」章节，含字段表、多模态行为说明与升级当天旧缓存处理方式。

### 验证记录

- `compileall backend src tools_config.py` 通过；`npm run build` 通过。
- DB 迁移 + event_date/timeline 读写闭环实测通过。
- 多模态默认关闭时 `extract_text_from_images` 返回空串（降级）。
- 日历按 event_date 分组：有 `event_date` 的记录出现在对应日期，`event_date=null` 的记录不进日历。
- 节点级打点真实库实测（插入后清理）：主日期打点、同日节点去重、跨日期节点展开（初赛/决赛各进当天）、空日期坏节点跳过、主日期缺失但节点有效仍打点、timeline 完整随卡片下发——7 项断言全部 PASS。
- 脏数据防御真实库实测（插入后清理）：`_sanitize_timeline` 非 dict 剔除/斜杠归一/空节点剔除/非 list 兜底、存量脏 JSON 入库后查询不崩且被过滤、脏记录日历正常打点、斜杠主日期打点、totals 口径一致——12 项断言全部 PASS。

---

## [2026-09-17] v2.2.0：五项改进（CTF 状态解析 / 暗色控件 / 降 token / 链接贯穿 / 事件日历）

> 背景：用户报告五个问题——①仪表盘平台下拉样式缺失；②Agent 缓存命中率低、token 消耗高；③CTF 时间表永远没有「进行中/近期结束」；④希望新增月份事件日历；⑤超星/公众号链接希望被识别后在仪表盘/日历一目了然。

### Fixed（P3 - CTF 状态解析全量失效，严重）

- **根因不是「只查不存」，而是日期正则全挂**：CTFtime 上游改用月份缩写带尾点格式（如 `18 Sept., 04:30 UTC — 18 Sept. 2026, 16:30 UTC`），`_parse_ctftime_date` 的月份正则匹配 `Sept.` 时因尾点全部失败，`start_time` 退化为原始文本、`end_time: null`、`status` 恒为 `upcoming`——缓存里 45 条无一例外（证据：`data/ctf_cache.json`）。修复 `backend/api/v1/ctf.py`：
  - 清洗段去除月份缩写尾点；
  - `parse_event_row` 策略 1 增强：新增 `data-start`/`data-end` 显式属性对解析，`data-utc`/`title` 顺序兜底；
  - 新增 `_as_utc()` 统一时区：naive 视为 UTC（CTFtime 语义），`compute_status` 的 `now` 改为 `datetime.now(timezone.utc)`，修复 aware/naive 混比；
  - `get_events` 新增旧缓存重解析兜底：`start_time` 非年份开头的条目现场重跑 `_parse_ctftime_date` 修复并回写缓存文件，无需等全量刷新。
  - **实测**：离线修复 45/45 条全部解析成功；真实全量刷新后 `进行中 1 / 近期结束 6 / 即将 45`（此前 running/recently_ended 恒为 0）。

### Fixed（P1 - 仪表盘下拉暗色适配）

- **根因**：原生 `<select>` 弹层与 `<input type="date">` 日历弹层由系统渲染，暗色页面上出现白色弹层/黑字割裂（即用户看到的「样式缺失 + 语法问题」观感）。修复：
  - `frontend/src/index.css` body 增加 `color-scheme: dark`（原生控件弹层跟随暗色渲染）；
  - 新增 `.select-field` 组件类（`appearance` 区域统一 + `option` 暗色兜底 `background-color: #18181b`）；
  - `DashboardPage.tsx` 平台下拉换用 `.select-field`；筛选条件变化 300ms 防抖自动刷新（保留手动刷新按钮）。

### Added（P2 - 降 token：当日分析缓存 + 垃圾入记忆）

- **当日分析缓存 `data/analysis_cache_{YYYY-MM-DD}.json`**（`src/agent/analyzer.py`）：同一天内同一 `raw_hash` 的条目不再重复送 LLM——命中缓存的推送/过滤决策直接合并进本轮结果与报告；全部命中时**完全跳过 LLM 调用**。缓存文件 2 天后自动清理。
- **垃圾条目入记忆库（`status='junk'`）**：此前 LLM 判定的垃圾只在当轮丢弃、不入库，同一批垃圾下次还会再送 LLM 浪费 token（缓存命中低的主因之一）。现第 2.5 步将 `filtered_items` 按标题反查 `raw_hash` 后以 `junk` 状态写入 `intelligence_memory`，下次预过滤（`is_seen`）直接排除。
- 附带修正：预过滤阶段统一回填 `item['raw_hash']`，后续缓存与去重共用同一 hash 语义。

### Added（P5 - 链接贯穿全链路）

- **采集层提取**：`content_extractor.py` 新增 `extract_links()`（正文纯文本 URL，去重上限 10）与 `merge_links()`（多组合并、本体链接优先）；超星条目 `links = [本体链接] + 正文内嵌链接`。`wechat_parser.py` 的 `parse_single_article` 改为返回 `(正文, 内嵌 <a> 链接)`，微信条目 `links = [本体链接] + 正文 <a> 链接 + 正文纯文本 URL`（`//` 协议相对形式补全 https）。
- **分析层直取**：推送条目按清洗标题（前 10 字符前缀兜底）反查原始条目，`link`/`links` 直接取自采集数据，不依赖 LLM 复述；当日缓存条目同样携带 links。
- **存储层**：`pushed_records` 幂等迁移新增 `links TEXT` 列（`PRAGMA table_info` 检查后 `ALTER TABLE`）；`save_pushed_record` 接受列表自动序列化 JSON；查询自动解析，旧记录（无 links 仅单 link）兼容回退。
- **展示层**：仪表盘记录卡片与日历详情面板均渲染链接 chip（首个「原文」、其余「引用N」，超出 5 个显示 +N）。

### Added（P4 - 事件日历）

- **后端 `backend/api/v1/calendar_api.py`**：`GET /api/v1/calendar?month=YYYY-MM` 合并 CTF 赛事（缓存 + 状态现算，跨天赛事展开为其覆盖的每一天、钳制月内且单赛事最多展开 14 天防脏数据）与情报推送记录，按日期分组返回 `{days: {"YYYY-MM-DD": {ctf: [...], intel: [...]}}}`。
- **前端 `CalendarPage.tsx`**：月份网格（周一起始、上月/下月切换、回到今天），CTF 青色打点 + 情报琥珀打点，超过 2 个事件显示数量；单击某天右侧面板显示当天 CTF 卡片（状态/时间/赛制/权重/地点/官网与 CTFtime 链接）与情报卡片（平台/分类/链接 chip）。新路由 `/calendar` + 侧边栏「事件日历」（CalendarDays 图标）。
- **实测**：2026-09 合并出 18 个有事件日期（CTF 48 次 / 情报 44 条），跨天赛事正确展开，旧情报记录正确按天分组。

### 验证记录

- `python -m compileall backend src tools_config.py` 通过；`npm run build` 通过（2012 模块，无 TS 错误）。
- `pushed_records.links` 读写闭环 + 旧记录兼容实测通过。
- CTF 真实刷新（ctftime.org 在线）：running=1 / recently_ended=6，验证锚点达成。

---

## [2026-09-16] v2.1.1：代码审查缺陷修复 + 后台阻塞 + WebSocket 跨页保活

> 背景：全量代码审查确认 3 严重 / 6 中等 / 4 轻微缺陷；另修复两个用户直接体验问题——「CTF 拉取时所有页面卡死」与「Agent 对话 WebSocket 换页即断」。

### Fixed（严重）

- **报告接口路径遍历（任意文件读取）**：`backend/api/v1/reports_api.py` 的 `get_report` 将 URL 中的 `filename` 直接 `os.path.join(REPORTS_DIR, filename)`。Windows 下 URL 编码的 `%5C`（反斜杠）可穿过路由参数校验，`GET /api/v1/reports/..%5C..%5C.env` 即可读取 `.env`、`configs/` 凭证等任意文件。现三重防护：`os.path.basename` 归一化 + 拒绝含路径分隔符/点开头的文件名 + `realpath` 确认真实路径仍在报告目录内，另限制 `.md` 后缀。实测 `..%5C` 与 `..%2F` 两种变体均返回 404。
- **Agent 循环无最大迭代保护（无限烧 token）**：`agent_core.py` 与 `backend/agents/xidian_agent.py` 的 `chat()` 均为裸 `while True`，叠加系统提示词「登录完成后自动重跑中断的工具」，一旦扫码成功但抓取仍持续返回 `SESSION_EXPIRED`，LLM 会陷入 harvest→scrape 死循环。现新增 `MAX_TOOL_ROUNDS = 15`：超限后注入系统指令、请求一次**不带工具**的最终文字总结（`_force_summarize`），如实说明未完成原因，后端版同时推送 WS 错误日志并在返回值标注 `hit_tool_limit`。
- **`_trim_history` 切断 tool_call 配对（后续请求 400）**：原实现按消息条数 `self.history[-(max_rounds*2):]` 截断，会把 `assistant(tool_calls)` 与 `role:"tool"` 消息对从中间切断，产生孤儿 tool 消息——OpenAI/DeepSeek 强校验 `tool_call_id` 配对，下一次请求直接 400。现改为按**完整轮次**裁剪：收集 `role=="user"` 的消息下标作为安全边界，仅保留最近 N 个 user 轮，保证配对永不切断。

### Fixed（中等）

- **CTF 拉取阻塞整个后端（用户报告）**：`backend/api/v1/ctf.py` 的 `get_events`（`async def`）在缓存过期时**同步调用** `refresh_cache()`——多页抓取 + 20 个详情页补抓 + `time.sleep(0.6)` + 指数退避重试，卡死事件循环数分钟，期间所有 API/WebSocket 全部冻结。现抽取 `_start_refresh_thread()`（与 `POST /refresh` 同一套后台线程 + `_refresh_state` 状态守卫），`get_events` 仅触发后台刷新并**立即返回现有缓存**，返回体新增 `refreshing` 字段。实测：刷新期间 `/api/v1/dashboard/stats` 22ms 正常响应（修复前会卡到刷新结束）。
- **LLM 同步调用阻塞事件循环（用户报告的另一半根因）**：`backend/agents/xidian_agent.py` 的 `chat()` 用同步 OpenAI SDK 调用 LLM（单次可达数十秒），期间整个后端 HTTP/WebSocket 一起卡死。工具执行此前已用 `asyncio.to_thread` 隔离，现 LLM 调用同样移入线程池。
- **Agent 会话历史全局共享**：`XidianAgent` 为单例且 `self.history` 全局唯一，多浏览器窗口/多用户同时对话会互相污染上下文。现改为 `self._histories: Dict[session_id, List]` 按 session 隔离（`_get_history` / `_trim_history` 均按 session 存取）。
- **任务接口顶层 success 恒为 True**：`backend/api/v1/agents.py` 的 `run_agent_task` 把 `run_task` 的真实结果再包一层 `{"success": True, "data": ...}`，前端只看顶层会误判失败为成功——与 v2.1「失败不得包装成成功」原则相悖。现直接透传 `run_task` 结果（其已如实含 `success` 字段）。
- **WebSocket 连接泄漏**：`backend/main.py` 的 `websocket_logs` 只捕获 `WebSocketDisconnect`，`receive_json` 解析异常等其他错误不会清理连接记录。现改用 `finally: ws_manager.disconnect(session_id, websocket)` 全路径清理，并传入 websocket 实参精确移除。
- **WS 依赖缺失导致 WebSocket 完全不可用（验证时发现的存量问题）**：`requirements.txt` 写的是 `uvicorn>=0.29.0`，装出来没有 WebSocket 支持，后端日志报 `No supported WebSocket library detected`，`/ws/logs` 握手直接 404。现改为 `uvicorn[standard]>=0.29.0`，实测握手成功（WS_OPEN_OK）。

### Fixed（轻微）

- **CLI 工具参数 JSON 容错**：`agent_core.py` 与后端 `chat()` 中 `json.loads(args_str)` 无保护，LLM 偶发输出非法 JSON 会崩掉整轮对话。现捕获 `JSONDecodeError`，把错误信息作为工具结果喂回模型自行纠正。
- **退出词误判**：CLI 与后端均以「回复含『再见/退出』」判定会话结束，报告正文含该词会误退出。现加长度条件（回复 < 50 字符且无工具调用）。
- **前端地址硬编码**：`AgentChatPage.tsx` 写死 `ws://localhost:8138` 与 `http://localhost:8138`，未复用 `client.ts` 的 `VITE_API_BASE_URL`。现由全局 WS 管理器从 `BASE_URL` 推导 WS 地址（`http→ws`），REST 调用统一走 axios 客户端。
- **存量 TS 构建错误**：`npm run build` 原本失败（`CtfStatus`/`TestTube` 未使用导入、lucide 图标不存在的 `title` prop、`PreferencesPage` 未使用变量），已一并修复，构建恢复通过。

### Added

- **应用级 WebSocket 管理器 `frontend/src/api/websocket.ts`**（修复「WS 换页即断」）：此前 WS 连接绑定在 `AgentChatPage` 组件上，换页即 unmount 关闭，且 `sessionId` 用 `Date.now()` 每次挂载重新生成，旧任务日志彻底丢失。现改为：
  - 生命周期与应用一致（`main.tsx` 启动即连接），**换页/组件卸载不断开**，页面组件只做订阅/退订；
  - **断线自动重连**：指数退避 1s→2s→4s…上限 30s，连接成功后清零；
  - **日志缓冲**：按 sessionId 缓存最近 500 条，换页返回后自动回放；
  - **sessionId 持久化到 sessionStorage**（`agent_session_id`）：同标签页保持不变，关闭标签页才失效；
  - `client.ts` 导出 `BASE_URL` 供其推导 WS 地址，支持 `VITE_WS_URL` 覆盖。
- **CTF 前端自动轮询**：`CtfPage` 检测到 `getEvents` 返回 `refreshing: true`（后端缓存过期自动刷新）时，自动进入既有的 `/refresh/status` 轮询流程，完成后加载新数据；轮询逻辑抽取为 `startPolling()` 供手动/自动刷新共用。

### Changed

- **CORS 收紧**：`backend/main.py` 由 `allow_origins=["*"]` 改为白名单，默认 `http://localhost:7860` / `http://127.0.0.1:7860`，可通过 `.env` 的 `ALLOWED_ORIGINS`（逗号分隔）覆盖；`.env.example` 同步增加说明。
- **Agent 对话 REST 超时延长**：前端发往 `/api/v1/agents/xidian/chat` 的请求超时由 axios 默认 30s 提升为 600s——LLM 多轮工具任务可达数分钟，30s 会导致前端中断而后端仍在执行。

### Removed

- 删除根目录 `app_gradio_backup.py`（84KB 的 v1 Gradio 旧版死代码，git 历史可找回）。

### 验证记录（2026-09-16）

| 项 | 结果 |
|---|---|
| 全量编译 `compileall`（backend + 入口文件） | 通过 |
| 后端启动 `/health` | 200 |
| 路径遍历 `..%5C..%5C.env` / `..%2F..%2F.env` | 均 404 |
| CTF 刷新期间其他接口 | `/api/v1/dashboard/stats` 22ms 正常响应 |
| CTF 后台刷新落盘 | 46 条赛事写入缓存，`refreshing` 字段正确 |
| WebSocket 握手 | WS_OPEN_OK（补装 uvicorn[standard] 后） |
| 前端 `npm run build` | 通过 |


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
- `.gitignore` [UPDATE] — 新增排除项：`node_modules/`、本地编辑器 / IDE 工作区目录、`_title_keep.bat`、`task_human.txt`

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
