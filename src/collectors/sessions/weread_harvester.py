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
import json
import os
import time

from playwright.sync_api import sync_playwright


class WereadHarvester:
    """微信读书凭证采集器 / 静默续期器"""

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
    # 验证登录态用的中性检索词：只要回执含 content 段即说明登录有效
    PROBE_QUERY = "西电"
    # 等待人工扫码的上限（秒）。扫码本身可能很慢，给足 10 分钟，避免中途失败。
    LOGIN_WAIT_SECONDS = 600

    def __init__(self, wait_seconds=None, headless=False):
        self.wait_seconds = int(wait_seconds or self.LOGIN_WAIT_SECONDS)
        # 人工扫码必须可见浏览器，默认有头；静默续期会显式改用无头
        self.headless = headless

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

    def _launch(self, playwright, headless=None):
        """打开持久化档案（复用其中的登录态）"""
        return playwright.chromium.launch_persistent_context(
            self.PROFILE_DIR,
            headless=self.headless if headless is None else headless,
            viewport={"width": 1280, "height": 860},
            user_agent=self.USER_AGENT,
            args=["--disable-blink-features=AutomationControlled"],
        )

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
        payload = {"query": self.PROBE_QUERY, "offset": 0, "searchcookies": "", "searchid": ""}
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
        """
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

    # ---------- 主流程（需要人工扫码时使用） ----------
    def run_harvest(self):
        print("--- 微信读书凭证采集程序启动 ---")
        print("正在调起浏览器：档案中已有有效登录态会直接续期复用，否则请在窗口中扫码登录...")

        context = None
        try:
            with sync_playwright() as p:
                try:
                    context = self._launch(p, headless=self.headless)
                except Exception as e:
                    return {"success": False, "verified": False,
                            "message": "浏览器档案无法打开（可能上一次的浏览器窗口尚未关闭）: %s" % e}

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
