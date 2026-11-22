# -*- coding: utf-8 -*-
"""
微信读书凭证采集器 / 续期器

用途：
    1. run_harvest()      —— 扫码登录（仅在档案里登录态也已失效时才需要人工参与），
                             把登录凭证（Cookie + UA）落盘到 configs/weread_auth.json；
    2. refresh_cookies()  —— 静默续期：复用持久化档案里已有的登录态，刷新被服务端轮换的
                             cookie 并落盘，**不打扰用户**。

为什么必须有 refresh_cookies（2026-09-13 实测踩坑）：
    微信读书服务端会轮换 `wr_skey` / `wr_gid`（实测两次比对：这两个字段值会变，
    而 wr_vid / wr_rt / wr_ql / wr_fp 不变）。后果是落盘凭证「看起来还在、实际已超时」：
        [落盘 cookie]     -> {"errCode":-2012,"errMsg":"登录超时"}   ← 旧值，业务接口拒绝
        [浏览器档案 cookie] -> {"content":{...}}                     ← 新值，业务接口正常
    即：**同一时刻，档案里有有效登录态，落盘值却已失效**。若只依赖落盘值，用户每两小时
    就得重新扫一次码，而其实完全不必——用档案静默续期即可恢复。

为什么登录判定必须走业务接口，而不能只看本地 cookie：
    早期判定是「本地 cookie 里存在 wr_vid 就算已登录」。这在上述场景下会**误判**：
    本地 wr_vid 明明在，业务接口却返回 -2012。结果是「抓取失败 → 提示扫码 → 扫码工具
    因看到本地 wr_vid 而秒退并宣称已更新 → 抓取依然失败」的死循环。
    因此这里统一以 `wx_search_broker_proxy` 的**真实回执**作为权威判据。

其他设计要点（沿用探针实测通过的机制，非假设）：
- 使用 Playwright「持久化浏览器档案」（configs/weread_profile）：登录态保存在档案里，
  浏览器打开页面时会自动续期，因此多数情况无需人工扫码；
- 等待扫码有明确上限并实时提示剩余时间；超时返回可读原因（重跑即可），
  而不是抛异常或假装成功；
- 打印时对凭证值打码，绝不输出完整 Cookie 值。
"""
import glob
import json
import os
import re
import threading
import time

from playwright.sync_api import sync_playwright

from src.utils.config_loader import get_probe_query


class WereadHarvester:
    """微信读书凭证采集器 / 静默续期器"""

    # 同一进程内串行化浏览器会话（类级锁，跨实例共享）。
    # 档案目录 configs/weread_profile 是独占资源：run_harvest（有头、等用户扫码，
    # 最长 10 分钟）与 refresh_cookies（无头静默续期，抓取失败时自动触发）若并发，
    # 后者的启动失败自愈会调用 _kill_orphan_browsers()，把前者**正在等待扫码的
    # 有头窗口**一起杀掉（匹配条件「进程名含 chrome 且命令行含 weread_profile」
    # 对那个窗口完全成立），用户会看到扫码窗口莫名消失。
    _browser_lock = threading.Lock()
    # 等待另一个浏览器会话让出档案的最长时间（秒）
    _BROWSER_LOCK_WAIT = 90

    # 浏览器稳定性开关（2026-10-06 实测补充）。
    # 本机 NVIDIA 容器（nvcontainer.exe）会间歇性崩溃（WER 事件名 BEX64 / 异常码
    # c0000409；7 天内 2 次，历史累计 13 份 WER 报告），崩溃重启会把覆盖层模块
    # 重新注入已运行进程；紧随其后的 2026-10-05 18:53:42 与 18:54:39，chrome.exe
    # 连续崩溃两次（档案 Crashpad 留有两份转储），Playwright 于是报
    #     BrowserType.launch_persistent_context: Target page, context or
    #     browser has been closed
    # 关掉 GPU 光栅化/合成后，浏览器进程不再走 D3D 初始化路径，被覆盖层注入并
    # 连带崩溃的概率显著下降；扫码登录只需渲染静态二维码，不用 GPU 无功能损失。
    # 其余开关避免窗口失焦/被判定遮挡时定时器节流导致页面与二维码卡死。
    LAUNCH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-features=CalculateNativeWinOcclusion",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    # 计算项目根目录的路径 (src/collectors/sessions 是三级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    AUTH_PATH = os.path.join(base_dir, "configs", "weread_auth.json")
    PROFILE_DIR = os.path.join(base_dir, "configs", "weread_profile")

    HOME_URL = "https://weread.qq.com/"
    BROKER_URL = "https://weread.qq.com/web/wx_search_broker_proxy"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    # 验证登录态用的检索词兜底：实际取值由 profile.probe_query / school_name 决定，
    # 只要回执含 content 段即说明登录有效。
    PROBE_QUERY = "大学"
    # 等待人工扫码的上限（秒）。扫码本身可能很慢，给足 10 分钟，避免中途失败。
    LOGIN_WAIT_SECONDS = 600

    def __init__(self, wait_seconds=None, headless=False):
        self.wait_seconds = int(wait_seconds or self.LOGIN_WAIT_SECONDS)
        # 人工扫码必须可见浏览器，默认有头；静默续期会显式改用无头
        self.headless = headless
        self.probe_query = get_probe_query()

    # ---------- 内部工具 ----------
    @staticmethod
    def _mask(value):
        """凭证值打码，仅保留前 4 位与长度，避免日志泄露"""
        if not value:
            return "<empty>"
        return "%s***len=%d" % (str(value)[:4], len(str(value)))

    @staticmethod
    def _cookies_of(context):
        """只取 weread.qq.com 域下的 Cookie，避免把无关站点的凭证写进文件"""
        jar = {}
        for c in context.cookies():
            if "weread.qq.com" in (c.get("domain") or ""):
                jar[c["name"]] = c["value"]
        return jar

    def _launch(self, playwright, headless=None, attempts=3):
        """
        打开持久化档案（复用其中的登录态）。

        先做**版本预检**，启动失败再自愈（结束仍占用档案的残留浏览器进程后
        退避重试）。必须自愈的原因：
          - 无头续期用的是 chrome-headless-shell.exe，**任务栏里看不到**，
            用户按「关闭所有 Chrome 窗口」手动清理时极易遗漏；
          - 上一轮抓取若被中断，无头进程可能成为孤儿，继续持有档案内部的
            LevelDB / Crashpad 锁，导致下一次启动秒退。

        为什么必须做版本预检（2026-10-06 实测三步复现）：
            Playwright 的持久化档案与「它绑定的 Chromium 版本」强耦合。
            实测：① 全新空档案 + chromium-1208(Chromium 145) 有头启动 → 正常；
                  ② 用 chromium-1217(Chromium 147) 打开同一档案（档案根目录的
                     `Last Version` 被写成 147.0.7727.15）；
                  ③ 换回 chromium-1208 有头启动 → **启动瞬间 abort**
                     （exitCode 0x80000003 STATUS_BREAKPOINT，档案 Crashpad 留下
                     转储），Playwright 只抛一句
                     `Target page, context or browser has been closed`。
            即：**低版本 Playwright 打开高版本写过的档案，有头必崩**；无头模式
            不受影响（chrome-headless-shell 不校验档案版本），所以症状是
            「静默续期一直正常，唯独扫码登录必崩」——极容易被误判成档案被锁或
            显卡驱动问题（2026-10-05 就误判成了 NVIDIA 覆盖层连带崩溃）。
            因此 requirements.txt 必须精确锁定 playwright 版本。

        自动对齐策略（2026-10-06 实测确定）：
            无损修复只有「运行版本 >= 档案版本」这一个方向——实测把档案的
            `Last Version` 标记改回旧版本、乃至直接删除该文件，旧版 Chromium
            打开仍然 abort（不兼容来自档案**内部 schema**，不是那个标记文件），
            所以「旧版打开新版档案」无法只靠改标记救回。
            因此这里做**自动对齐**：从本机 ms-playwright 目录挑一个修订号
            >= 档案最后使用者的 chromium 二进制，用 `executable_path` 启动它。
            好处是无需人工干预、且**保留登录态**（不必重新扫码）。若本机根本没有
            足够新的二进制，才如实报错并给出两条修法（升级 Playwright / 重建档案）。

        重要：**启动失败 ≠ 档案被锁**。这里把「未发现占用进程」与「确实清理掉了
        孤儿进程」分开陈述，并优先给出「版本错配」这一实测结论，避免再把人
        引向无效的排查方向。全部尝试失败才抛 RuntimeError。
        """
        effective_headless = self.headless if headless is None else headless
        launch_kwargs = dict(
            headless=effective_headless,
            viewport={"width": 1280, "height": 860},
            user_agent=self.USER_AGENT,
            args=list(self.LAUNCH_ARGS),
        )

        # ---- 版本预检 + 自动对齐 ----
        # 高/低关系用「修订号」判定：档案根目录的 Last Browser 记录了最后一次使用
        # 它的 chromium-<rev>；档案的 Last Version（147.0.7727.15 这种）与 Playwright
        # 的修订号之间没有离线映射表，所以只用修订号比较。
        prof_ver = self._profile_last_version(self.PROFILE_DIR)
        run_ver = self._running_chromium_version()
        p_major, r_major = self._major_version(prof_ver), self._major_version(run_ver)

        # 只有有头模式需要对档案版本负责：无头用的 chrome-headless-shell 不校验
        # 档案版本（实测 145 的无头能正常打开 147 写过的档案）。
        version_downgrade = bool(p_major and r_major and p_major > r_major)
        aligned = False
        if version_downgrade and not effective_headless:
            exe, note = self._resolve_compatible_chromium(playwright)
            if exe:
                launch_kwargs["executable_path"] = exe
                aligned = True
            print("   %s 版本对齐：档案由 Chromium %s 写过，本次环境自带 %s。%s"
                  % ("✅" if aligned else "⚠️", prof_ver, run_ver, note))
            if not aligned:
                print("      Chromium 打开「比自己新」的档案会在启动瞬间 abort，"
                      "有头模式基本必崩；重试无意义，已跳过重试以免白刷崩溃转储。")
                attempts = 1

        errors = []
        killed_any = False
        for attempt in range(1, attempts + 1):
            try:
                return playwright.chromium.launch_persistent_context(
                    self.PROFILE_DIR, **launch_kwargs)
            except Exception as err:
                errors.append(err)
                if attempt >= attempts:
                    break
                if launch_kwargs.pop("executable_path", None):
                    # 自动对齐挑的二进制起不来：退回 Playwright 自带 Chromium 再试一次，
                    # 避免「对齐」本身把原本可用的情况弄坏（对齐是增强，不能成为新的故障点）
                    print("   ↻ 对齐所用的 Chromium 启动失败，退回 Playwright 自带版本重试...")
                    time.sleep(1)
                    continue
                print("   ⚠️ 浏览器启动失败（第 %d/%d 次）: %s" % (attempt, attempts, err))
                print("   🧹 正在检查仍占用档案的残留浏览器进程"
                      "（含无头 chrome-headless-shell）...")
                killed = self._kill_orphan_browsers()
                killed_any = killed_any or bool(killed)
                if killed:
                    print("   🧹 已结束 %d 个残留进程 (pid=%s)" % (
                        len(killed), ",".join(str(k) for k in killed)))
                else:
                    print("   ↻ 未发现占用档案的进程——多半是浏览器进程自身异常退出"
                          "（而非目录被锁），退避后重试...")
                time.sleep(1.5 * attempt)  # 退避：留给残留子进程与系统资源恢复时间

        if version_downgrade:
            # 版本错配是确定性故障，重试再多次也不会好，直接把可执行的修复方式说清
            reason = ("已自动尝试改用本机更高版本的 Chromium 启动，仍失败。"
                      if aligned else
                      "且本机没有版本更高的 Chromium 可供自动对齐。")
            raise RuntimeError(
                "浏览器档案启动失败：检测到 **Chromium 版本错配**。"
                "档案 %s 最后一次由 Chromium %s 写过，而本次环境自带 %s。%s"
                "Chromium 打开「比自己新」的档案会在启动瞬间 abort"
                "（exitCode 0x80000003，档案 Crashpad 会留下 .dmp 转储），"
                "Playwright 因此只报 "
                "Target page, context or browser has been closed。"
                "修复方式（任选其一）："
                "①【推荐】升级到与档案同版本或更高版本的 Playwright "
                "（`pip install -U playwright`，随后重启后端）；"
                "② 换用/补装更高版本的 Chromium 二进制（本机会被自动挑选，"
                "无需手工指定）；"
                "③ 若必须降级使用，删除 %s 让其重建"
                "（登录态会失效，需要重新扫码；也可用 align_weread_browser_env "
                "工具的 rebuild 动作，会先备份旧档案）。原始异常：%s"
                % (self.PROFILE_DIR, prof_ver, run_ver, reason, self.PROFILE_DIR,
                   "；".join(str(e) for e in errors)))

        raise RuntimeError(
            "浏览器档案启动失败（已自愈清理并重试 %d 次仍失败）。"
            "档案目录: %s；该目录%s。"
            "这通常不是目录被占用，而是浏览器进程在启动瞬间异常退出。"
            "已排除的实测结论：若不是版本错配，则多为安全软件拦截或系统资源紧张；"
            "可直接重试，若持续失败请检查 %s\\Crashpad\\reports 是否新增 .dmp"
            "（有转储说明是浏览器主动 abort，而非目录锁）。"
            "原始异常：%s" % (
                attempts, self.PROFILE_DIR,
                "并已清理过占用它的残留进程" if killed_any else "经检查无其他进程占用",
                self.PROFILE_DIR,
                "；".join(str(e) for e in errors)))

    # ---------- 版本预检工具 ----------
    @staticmethod
    def _read_mixed_text(path):
        """
        读取 Chromium 写在档案根目录的小文本文件（`Last Version` / `Last Browser`）。

        实测编码**不一致**：`Last Version` 是 ASCII/UTF-8（`147.0.7727.15`），而
        `Last Browser`（记录最后一次使用的浏览器 exe 路径）是 **UTF-16LE**。
        若统一按 UTF-8 读，`Last Browser` 会解出夹着一堆 `\\x00` 的字符串，正则
        永远匹配不上，导致版本判定静默失效（首个版本就是这么写的，已修）。
        这里统一按「字节里是否含 NUL」自动选择解码方式，两种都能吃。
        """
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return None
        if not raw:
            return None
        text = (raw.decode("utf-16-le", "ignore") if b"\x00" in raw
                else raw.decode("utf-8", "ignore"))
        return text.replace("\x00", "").strip() or None

    @classmethod
    def _profile_last_version(cls, profile_dir):
        """档案最后一次被哪个 Chromium 版本写过（读档案根目录的 `Last Version`）。"""
        return cls._read_mixed_text(os.path.join(profile_dir, "Last Version"))

    @staticmethod
    def _running_chromium_version():
        """
        本次将要启动的 Chromium 版本号（如 "147.0.7727.15"）。

        来源是 Playwright 自带的 `driver/package/browsers.json`：其中同时给出
        revision 与 browserVersion，比读 exe 的 VersionInfo 更稳（不需要额外
        起子进程或依赖 pywin32）。读不到返回 None，此时跳过版本预检，
        不影响正常流程。
        """
        try:
            import json
            import playwright
            path = os.path.join(os.path.dirname(playwright.__file__),
                                "driver", "package", "browsers.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for b in data.get("browsers", []):
                if b.get("name") == "chromium":
                    return str(b.get("browserVersion") or "") or None
        except Exception:
            return None
        return None

    @staticmethod
    def _major_version(version):
        """取版本号主版本（"147.0.7727.15" -> 147），解析失败返回 None。"""
        try:
            return int(str(version).split(".")[0])
        except (ValueError, TypeError):
            return None

    # ---------- 浏览器环境自动对齐 ----------
    @staticmethod
    def _revision_of(text):
        """从 `...\\chromium-1217\\...` 或 `...\\chromium_headless_shell-1208\\...` 里取修订号。"""
        m = re.search(r"chromium[_-]?(?:headless[_-]shell)?[-_](\d+)", text or "")
        return int(m.group(1)) if m else None

    @classmethod
    def _profile_writer_revision(cls, profile_dir):
        """
        档案最后一次被哪个 chromium 修订号使用过。

        读档案根目录的 `Last Browser`（Chromium 每次启动都会写入，内容形如
        `...\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe`，注意是
        UTF-16LE 编码，见 `_read_mixed_text`）。
        这是本模块判定「档案新旧」的唯一依据：档案里的 `Last Version` 是 Chromium
        版本号（147.0.7727.15），与 Playwright 的修订号（1217）之间没有离线映射表。
        读不到返回 None（此时不做对齐）。
        """
        return cls._revision_of(
            cls._read_mixed_text(os.path.join(profile_dir, "Last Browser")))

    @staticmethod
    def _running_chromium_revision():
        """当前 Playwright 绑定的 chromium 修订号（取自自带 browsers.json）。"""
        try:
            import playwright
            path = os.path.join(os.path.dirname(playwright.__file__),
                                "driver", "package", "browsers.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for b in data.get("browsers", []):
                if b.get("name") == "chromium":
                    return int(b.get("revision"))
        except Exception:
            return None
        return None

    @classmethod
    def _browsers_root(cls, playwright=None):
        """
        本机 Playwright 浏览器根目录（如 `C:\\Users\\x\\AppData\\Local\\ms-playwright`）。

        优先用「当前 Playwright 自带 chromium 的可执行文件路径」反推——这样天然兼容
        `PLAYWRIGHT_BROWSERS_PATH` 等自定义安装位置，不必硬编码；拿不到 playwright
        对象时退化为环境变量 / 档案记录的路径 / 系统默认目录。
        """
        if playwright is not None:
            try:
                exe = playwright.chromium.executable_path
                # <root>/chromium-<rev>/chrome-win64/chrome.exe -> 上溯三级
                return os.path.dirname(os.path.dirname(os.path.dirname(exe)))
            except Exception:
                pass
        env_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if env_root and os.path.isdir(env_root):
            return env_root
        # 从档案的 Last Browser 反推（该档案必然是被某个安装位置使用的）
        last = cls._read_mixed_text(os.path.join(cls.PROFILE_DIR, "Last Browser"))
        m = re.search(r"^(.*?)[\\/]chromium[_-]?(?:headless[_-]shell)?[-_]\d+[\\/]", last or "")
        if m and os.path.isdir(m.group(1)):
            return m.group(1)
        if os.name == "nt":
            cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        else:
            cand = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")
        return cand if os.path.isdir(cand) else None

    @classmethod
    def _installed_chromiums(cls, playwright=None):
        """
        扫描本机已安装的有头 chromium，返回 [(修订号, exe路径), ...]（修订号降序）。

        只认 `chromium-<rev>` 目录，不含 `chromium_headless_shell-<rev>`——有头模式
        必须用带窗口的完整 Chromium。
        """
        root = cls._browsers_root(playwright)
        if not root or not os.path.isdir(root):
            return []
        found = []
        for name in os.listdir(root):
            m = re.fullmatch(r"chromium-(\d+)", name)
            if not m:
                continue
            for sub in ("chrome-win64", "chrome-win", "chrome-linux", "chrome-mac"):
                exe = os.path.join(root, name, sub, "chrome.exe" if os.name == "nt"
                                   else "chrome")
                if os.path.isfile(exe):
                    found.append((int(m.group(1)), exe))
                    break
        found.sort(key=lambda x: x[0], reverse=True)
        return found

    @classmethod
    def _resolve_compatible_chromium(cls, playwright=None):
        """
        为「档案被更高版本写过」挑选可用的 Chromium 二进制。

        返回 (exe_path | None, 说明文字)。规则：在本机已安装的有头 chromium 里挑
        「修订号 >= 档案记录、且尽量贴近」的那一个——越贴近，与当前 Playwright
        驱动的协议差异越小；档案更旧时无需改动（返回 None，按默认环境启动）。
        """
        prof_rev = cls._profile_writer_revision(cls.PROFILE_DIR)
        run_rev = cls._running_chromium_revision()
        if not prof_rev:
            return None, "档案尚无使用记录（或读不到 Last Browser），按默认环境启动。"
        if run_rev and prof_rev <= run_rev:
            return None, ("档案修订号 %d 不高于本次的 %d，无需对齐。"
                          % (prof_rev, run_rev))
        cands = cls._installed_chromiums(playwright)
        if not cands:
            return None, "未能在本机识别任何已安装的 chromium 目录，无法自动对齐。"
        usable = [c for c in cands if c[0] >= prof_rev]
        if not usable:
            return None, ("本机已安装的 chromium 修订号最高为 %d，低于档案记录的 %d，"
                          "无法自动对齐。" % (cands[0][0], prof_rev))
        rev, exe = usable[-1]  # 降序列表里最后一个 = 满足条件中最小的（最贴近档案）
        return exe, "档案修订号 %d > 本次 %s，已自动改用本机 chromium-%d 启动。" % (
            prof_rev, run_rev if run_rev else "未知", rev)

    # ---------- 环境自检 / 重建（供后端启动自检与 Agent 工具调用） ----------
    @classmethod
    def diagnose_browser_env(cls):
        """
        自检「浏览器环境 vs 持久化档案」的版本一致性。

        **纯读取**：不启动浏览器、不改动任何文件，因此后端启动时也能安全调用。

        返回 dict，其中 `status` 是最关键的结论：
            no_profile   —— 档案不存在（首次使用，扫码后会自动生成）
            ok           —— 运行版本 >= 档案版本，无需处理
            auto_align   —— 档案更新，但本机有足够新的 chromium，启动时会自动改用
            needs_rebuild—— 档案更新且本机没有足够新的 chromium，只能重建档案
                            （会丢登录态，需重新扫码）或升级 Playwright
            unknown      —— 读不到档案使用记录，无法判定
        """
        prof_dir = cls.PROFILE_DIR
        prof_ver = cls._profile_last_version(prof_dir)
        prof_rev = cls._profile_writer_revision(prof_dir)
        run_ver = cls._running_chromium_version()
        run_rev = cls._running_chromium_revision()
        installed = cls._installed_chromiums()
        crashes = len(glob.glob(os.path.join(prof_dir, "Crashpad", "reports", "*.dmp")))

        info = {
            "profile_dir": prof_dir,
            "profile_exists": os.path.isdir(prof_dir),
            "profile_version": prof_ver,
            "profile_writer_revision": prof_rev,
            "running_chromium_version": run_ver,
            "running_revision": run_rev,
            "installed_chromium_revisions": [r for r, _ in installed],
            "crash_dumps": crashes,
        }

        if not info["profile_exists"]:
            info.update(status="no_profile",
                        message="档案不存在，首次扫码时会自动创建，无需处理。")
            return info
        if not prof_rev or not run_rev:
            info.update(status="unknown",
                        message="读不到档案使用记录或当前 chromium 修订号，跳过版本判定。")
            return info
        if prof_rev <= run_rev:
            info.update(status="ok",
                        message="档案修订号 %d <= 运行修订号 %d，版本一致，可直接扫码。"
                                % (prof_rev, run_rev))
            return info

        usable = [r for r, _ in installed if r >= prof_rev]
        if usable:
            info.update(status="auto_align",
                        message="档案由更新的 chromium-%d 写过，本机已安装 chromium-%d，"
                                "启动时会自动改用后者（保留登录态，无需重新扫码）。"
                                % (prof_rev, min(usable)))
        else:
            info.update(status="needs_rebuild",
                        message="档案由更新的 chromium-%d 写过，但本机已安装的 chromium "
                                "修订号最高仅 %s，无法自动对齐。需二选一："
                                "① 升级 Playwright 以取得更高版本 chromium"
                                "（pip install -U playwright && python -m playwright "
                                "install chromium）；② 重建档案（登录态会失效，"
                                "需要重新扫码）。"
                                % (prof_rev, installed[0][0] if installed else "无"))
        return info

    @classmethod
    def rebuild_profile(cls):
        """
        重建持久化档案（**破坏性操作**：登录态会丢失，需要重新扫码）。

        为保证可回退，默认把旧档案整体**改名备份**为
        `<profile>.bak-YYYYmmdd-HHMMSS`，而不是直接删除；一旦改名失败（目录仍被
        浏览器进程占用等）就中止并如实返回原因，绝不静默删除用户数据。
        返回 (ok, message)。
        """
        if not cls._browser_lock.acquire(blocking=False):
            return False, ("已有浏览器会话正在进行（可能正在等待用户扫码），"
                           "请先完成或关闭它再重建档案。")
        try:
            if not os.path.isdir(cls.PROFILE_DIR):
                return True, "档案本就不存在，无需重建；下次扫码会自动创建。"
            # 先清掉可能仍占用档案的残留浏览器进程，否则目录改名会失败
            cls()._kill_orphan_browsers()
            backup = "%s.bak-%s" % (cls.PROFILE_DIR, time.strftime("%Y%m%d-%H%M%S"))
            try:
                os.rename(cls.PROFILE_DIR, backup)
            except OSError as e:
                return False, ("重建失败：无法重命名档案目录（可能仍被浏览器进程占用）：%s。"
                               "请先关闭所有相关浏览器窗口后重试。" % e)
            return True, ("档案已重建：旧档案已备份为 %s，新档案将在下次扫码时自动生成。"
                          "**登录态已失效，需要重新扫码登录。**" % backup)
        finally:
            cls._browser_lock.release()

    def _kill_orphan_browsers(self):
        """
        结束所有仍以本档案目录为 user-data-dir 的 Chromium 系进程。

        只匹配命令行里含 weread_profile 的进程，不会误伤用户日常打开的
        Chrome/Edge 窗口；同时覆盖 chrome.exe（有头）与 chrome-headless-shell.exe
        （无头续期使用，任务栏不可见，是手动清理的主要遗漏点）。
        Chromium 是进程树：杀掉主进程后 crashpad 等子进程会变成新孤儿继续
        持有档案，因此循环清理直到扫描不到匹配进程为止（上限 3 轮）。
        返回被成功结束的全部 pid 列表。
        """
        import subprocess
        killed = []
        for _round in range(3):
            try:
                ps_cmd = (
                    "Get-CimInstance Win32_Process | Where-Object "
                    "{ $_.CommandLine -like '*weread_profile*' "
                    "-and $_.Name -like '*chrome*' } | "
                    "Select-Object -ExpandProperty ProcessId"
                )
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=20,
                ).stdout
                pids = [int(x) for x in out.split() if x.strip().isdigit()]
            except Exception as e:
                print("   ⚠️ 残留进程扫描失败（忽略，继续重试启动）: %s" % e)
                return killed
            if not pids:
                break  # 已清理干净
            for pid in pids:
                if pid in killed:
                    continue
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=10)
                    killed.append(pid)
                except Exception:
                    pass
            time.sleep(1)  # 等子进程重组为孤儿后进入下一轮扫描
        return killed

    def _verify_broker(self, page):
        """
        用真实业务接口验证登录态（权威判据）。
        本地存在 wr_vid ≠ 服务端认可，必须看业务回执，否则会误判并形成扫码死循环。
        返回 (ok, detail)
        """
        js = """
        async ({url, payload}) => {
          try {
            const r = await fetch(url, {
              method: 'POST',
              credentials: 'include',
              headers: {
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json;charset=UTF-8'
              },
              body: JSON.stringify(payload)
            });
            return {status: r.status, body: (await r.text()).slice(0, 400)};
          } catch (e) {
            return {status: -1, body: 'FETCH_ERROR: ' + String(e)};
          }
        }
        """
        payload = {"query": getattr(self, "probe_query", self.PROBE_QUERY), "offset": 0, "searchcookies": "", "searchid": ""}
        try:
            res = page.evaluate(js, {"url": self.BROKER_URL, "payload": payload})
        except Exception as e:
            return False, "EVAL_ERROR: %s" % e
        body = str((res or {}).get("body") or "")
        if '"content"' in body:
            return True, "业务接口验证通过"
        return False, body[:200]

    @staticmethod
    def _api_user(page):
        """在页面上下文内请求 /api/user，仅作日志辅证（不作判定依据，失败不阻断流程）"""
        js = """
        async (u) => {
          try {
            const r = await fetch(u, {
              credentials: 'include',
              headers: {'Accept': 'application/json, text/plain, */*'}
            });
            return {status: r.status, body: (await r.text()).slice(0, 300)};
          } catch (e) {
            return {status: -1, body: 'FETCH_ERROR: ' + String(e)};
          }
        }
        """
        try:
            return page.evaluate(js, "/api/user")
        except Exception as e:
            return {"status": -2, "body": "EVAL_ERROR: %s" % e}

    def save_auth_data(self, auth_data):
        """保存凭证到本地"""
        os.makedirs(os.path.dirname(self.AUTH_PATH), exist_ok=True)
        with open(self.AUTH_PATH, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, ensure_ascii=False, indent=2)
        print("凭证已成功保存至: %s" % self.AUTH_PATH)

    def _capture_if_valid(self, context, page):
        """
        若当前登录态已通过业务接口验证，则落盘并在返回里带上验证结论。
        返回 (ok, message)
        """
        ok, detail = self._verify_broker(page)
        if not ok:
            return False, detail
        jar = self._cookies_of(context)
        ua = page.evaluate("navigator.userAgent")
        self.save_auth_data({"cookies": jar, "user_agent": ua})
        print("关键凭证字段: %s" % ",".join(sorted(jar.keys())))
        print("登录态验证: %s" % detail)
        return True, detail

    # ---------- 静默续期（供抓取器自愈调用） ----------
    def refresh_cookies(self):
        """
        静默续期：复用档案里已有的登录态刷新 cookie 并落盘，**不等待人工扫码**。

        返回 bool —— True 表示已落盘一份**经业务接口验证有效**的新凭证。
        该方法是「抓取遇到 -2012 登录超时」时的自愈手段：绝大多数情况下档案里
        登录态仍然有效，刷新一下即可恢复，无需打扰用户。

        并发保护：档案目录是独占资源，若已有浏览器会话在跑（多半是用户正在
        扫码的有头窗口），这里**直接跳过**而不是硬起第二个实例——否则一旦启动
        失败触发自愈清理，会把那个正在等用户扫码的窗口一起杀掉。
        """
        if not self._browser_lock.acquire(blocking=False):
            print("   ℹ️ 已有浏览器会话正在进行（可能正在等待扫码），本次跳过静默续期")
            return False
        context = None
        try:
            with sync_playwright() as p:
                context = self._launch(p, headless=True)
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(self.HOME_URL, timeout=60000)
                except Exception as e:
                    print("   ⚠️ 续期时首页加载异常（继续尝试验证）: %s" % e)
                # 留出页面自动续期的时间：服务端会在页面加载时轮换 wr_skey / wr_gid
                page.wait_for_timeout(5000)
                ok, detail = self._capture_if_valid(context, page)
                if not ok:
                    print("   ⚠️ 档案内登录态同样无效: %s" % detail)
                return ok
        except Exception as e:
            print("   ⚠️ 静默续期失败: %s" % e)
            return False
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            self._browser_lock.release()

    # ---------- 主流程（需要人工扫码时使用） ----------
    def run_harvest(self):
        print("--- 微信读书凭证采集程序启动 ---")
        print("正在调起浏览器：档案中已有有效登录态会直接续期复用，否则请在窗口中扫码登录...")

        # 档案是独占资源，同一时刻只允许一个浏览器会话。若另一个会话卡在半途，
        # 这里最多等 _BROWSER_LOCK_WAIT 秒，超时如实返回失败，而不是硬起第二个
        # 实例把对方的窗口杀掉。
        if not self._browser_lock.acquire(timeout=self._BROWSER_LOCK_WAIT):
            return {"success": False, "verified": False,
                    "message": "已有另一个微信读书浏览器会话正在进行"
                               "（可能正在等待扫码），请先完成或关闭它后再重试。"}

        context = None
        try:
            with sync_playwright() as p:
                try:
                    context = self._launch(p, headless=self.headless)
                except Exception as e:
                    # _launch 内部已自动清理残留进程并重试多次；走到这里说明
                    # 仍失败，把真实原因如实返回（含原始异常），便于定位
                    return {"success": False, "verified": False,
                            "message": "浏览器档案无法打开: %s" % e}

                page = context.pages[0] if context.pages else context.new_page()

                try:
                    page.goto(self.HOME_URL, timeout=60000)
                except Exception as e:
                    # 首页加载异常不直接失败：页面可能已部分可用，继续验证登录态
                    print("⚠️ 首页加载异常（继续验证登录态）: %s" % e)
                page.wait_for_timeout(5000)

                # 第一道：档案里可能已有有效登录态（浏览器打开页面时会自动续期），
                # 此时直接刷新并落盘，**无需打扰用户扫码**。
                probe = self._api_user(page)
                print("本地 /api/user 辅证回执: status=%s" % probe.get("status"))
                ok, detail = self._capture_if_valid(context, page)
                if ok:
                    print("你现在可以关闭浏览器窗口了。")
                    return {"success": True, "verified": True, "need_scan": False,
                            "message": "登录态有效，已刷新并保存最新凭证（无需扫码）"}

                print("ℹ️ 当前登录态不可用（%s），请在浏览器窗口中扫码登录..." % detail)
                print("   等待上限约 %d 分钟，扫码完成后会自动验证并保存。" % int(self.wait_seconds / 60))

                # 第二道：等待人工扫码，再用业务接口验证（不是只看本地 cookie 是否存在）
                deadline = time.time() + self.wait_seconds
                tick = 0
                while time.time() < deadline:
                    tick += 1
                    page.wait_for_timeout(2000)
                    # 不必每 2 秒都打业务接口，避免自己的探测行为触发风控
                    if tick % 3 != 0:
                        if tick % 15 == 0:
                            print("  仍在等待扫码... 剩余约 %d 秒 | 已捕获 Cookie 字段: %s" % (
                                int(deadline - time.time()),
                                ",".join(sorted(self._cookies_of(context).keys())) or "-"))
                        continue
                    ok, detail = self._capture_if_valid(context, page)
                    if ok:
                        print("你现在可以关闭浏览器窗口了。")
                        return {"success": True, "verified": True, "need_scan": True,
                                "message": "扫码成功，凭证已更新并通过业务接口验证"}
                    if tick % 9 == 0:
                        print("  尚未检测到有效登录态（%s）... 剩余约 %d 秒" % (
                            detail, int(deadline - time.time())))

                return {"success": False, "verified": False, "need_scan": True,
                        "message": "等待扫码超时（约 %d 分钟未检测到有效登录态），"
                                   "请重新运行并在浏览器窗口中完成扫码" % int(self.wait_seconds / 60)}

        except Exception as e:
            print("运行过程中发生错误: %s" % e)
            return {"success": False, "verified": False, "message": "微信读书登录失败: %s" % e}
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            self._browser_lock.release()


if __name__ == "__main__":
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import sys as _sys2
    if "--refresh" in _sys2.argv:
        print("静默续期结果: %s" % WereadHarvester().refresh_cookies())
    else:
        print("返回值: %s" % json.dumps(WereadHarvester().run_harvest(), ensure_ascii=False))
