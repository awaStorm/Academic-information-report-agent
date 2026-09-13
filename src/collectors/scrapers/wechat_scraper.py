# -*- coding: utf-8 -*-
"""
微信来源编排层（对外唯一入口）

背景（2026-07 实测）：
    原微信公众号后台通道（cgi-bin/searchbiz + cgi-bin/appmsg）已对「查询他号」
    精准软拒绝——凡带 fakeid 的列表请求一律返回频率控制回执，查自己账号正常。
    旧实现把这种业务失败当作「没抓到文章」，只打印错误就返回空数组，上层据此
    判定为「暂无新情报」，形成**静默断流**（产物恒为空，用户以为监控在正常工作）。

本模块职责（只做编排，不碰具体接口细节）：
    1. 按配置的来源优先级依次尝试各通道（当前主通道：微信读书）；
    2. 把各通道结果统一映射为状态语义
       （ok / not_found / empty / auth_expired / rate_limited / source_unavailable / error）；
    3. 触发限流时按递增间隔自动重试，耗尽后才降级，并明确提示「稍后重试即可，无需扫码」；
    4. 聚合 + 跨来源去重后写入 data/raw/data_raw_wechat.json（产物契约与旧通道完全一致）；
    5. 失败时返回明确的 error_type 与可读 message；
       只有「通道都正常、该号确实没发文」才允许返回 success=True / count=0。

兼容性：
    函数签名 run_wechat_scraper_flow(extra_query, progress_callback) 与返回字段
    （success / count）保持不变，main.py、backend、tools_config 的调用方式无需改动。
"""
import hashlib
import json
import os
import random
import time

import requests

from src.utils.config_loader import CONFIG

# 复用通道层的状态语义常量（单一来源，避免两套字符串各自漂移）
from src.collectors.scrapers.weread_scraper import (
    ST_OK, ST_NOT_FOUND, ST_EMPTY, ST_AUTH_EXPIRED,
    ST_RATE_LIMITED, ST_SOURCE_UNAVAILABLE, ST_ERROR, WereadScraper,
)

# 状态语义(小写) → 上报给上层的 error_type(大写)。
# error_type 保持既有大写风格以兼容历史消费方（app_gradio_backup.py 识别 SESSION_EXPIRED）。
STATUS_TO_ERROR_TYPE = {
    ST_AUTH_EXPIRED: "SESSION_EXPIRED",
    ST_RATE_LIMITED: "RATE_LIMITED",
    ST_SOURCE_UNAVAILABLE: "SOURCE_UNAVAILABLE",
    ST_NOT_FOUND: "NOT_FOUND",
    ST_EMPTY: "EMPTY",
    ST_ERROR: "ERROR",
}

# 需要用户重新扫码的状态（其余状态一律不得诱导用户重复扫码）
NEED_LOGIN_STATUS = (ST_AUTH_EXPIRED,)


class _WereadSource:
    """微信读书通道适配（当前主通道）"""

    name = "weread"
    label = "微信读书"

    def __init__(self, extra_query=None):
        self.scraper = WereadScraper(extra_query=extra_query)
        self.session = None

    def prepare(self):
        """准备会话，返回 (ok, error_type, message)"""
        auth = self.scraper.load_auth()
        if not auth:
            return False, "AUTH", "找不到微信读书凭证，请先完成微信读书扫码登录"
        self.session = self.scraper.build_session(auth)
        return True, None, None

    def fetch(self, account_name, limit):
        """返回 (status, articles, message, stats)"""
        res = self.scraper.fetch_account_articles(self.session, account_name, limit=limit)
        return (res.get("status") or ST_ERROR,
                res.get("articles") or [],
                res.get("message") or "",
                res.get("stats") or {})

    def refresh_auth(self):
        """
        静默续期被服务端轮换的 cookie（wr_skey / wr_gid）并重建会话。

        返回 True 表示已拿到经业务接口验证的新凭证、可以重试刚才失败的请求；
        False 表示档案里的登录态也失效了，此时才真的需要用户扫码。
        """
        if not self.scraper.refresh_auth():
            return False
        auth = self.scraper.load_auth()
        if not auth:
            return False
        self.session = self.scraper.build_session(auth)
        return True


class _LegacyMpSource:
    """
    原公众号后台通道适配（legacy）。

    该接口自 2026-07 起对「查询他号」已被官方关闭，保留代码仅为接口万一恢复时
    可一键切回，默认不启用（见 collectors.wechat.legacy_backend_enabled）。
    """

    name = "legacy_mp"
    label = "公众号后台(legacy)"

    def __init__(self, scraper):
        self.scraper = scraper
        self.auth = None

    def prepare(self):
        auth = self.scraper.load_auth()
        if not auth:
            return False, "AUTH", "找不到公众号后台凭证（configs/wechat_auth.json）"
        self.auth = auth
        return True, None, None

    def fetch(self, account_name, limit):
        articles = self.scraper.fetch_single_account(self.auth, account_name)
        if articles == "SESSION_EXPIRED":
            return ST_AUTH_EXPIRED, [], "公众号后台登录态失效", {}
        if not articles:
            return ST_EMPTY, [], "公众号后台未返回文章（该接口自 2026-07 起已关闭，仅作恢复备用）", {}
        if limit:
            articles = articles[:int(limit)]
        return ST_OK, articles, "", {"exact": len(articles)}


class WechatScraper:
    """微信来源编排层"""

    # 计算项目根目录的路径 (src/collectors/scrapers 是三级目录，所以跳三级)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    # 配置路径和URL（legacy 通道使用）
    AUTH_PATH = os.path.join(base_dir, "configs", "wechat_auth.json")
    OUTPUT_FILE = os.path.join(base_dir, "data", "raw", "data_raw_wechat.json")

    def __init__(self, extra_query=None):
        self.extra_query = extra_query
        self._last_stats = []

    # ---------- 配置读取 ----------
    def _wechat_cfg(self, key, default=None):
        return CONFIG.get("collectors", {}).get("wechat", {}).get(key, default)

    def _weread_cfg(self, key, default=None):
        return CONFIG.get("collectors", {}).get("weread", {}).get(key, default)

    def _targets(self):
        """监控目标：优先 collectors.wechat.targets，为空时回退到 collectors.weread.targets"""
        names = list(self._wechat_cfg("targets", []) or [])
        if not names:
            names = list(self._weread_cfg("targets", []) or [])
        if self.extra_query and self.extra_query not in names:
            names.append(self.extra_query)
        return names

    def _delay(self):
        """公众号切换间隔（带随机抖动）"""
        rng = self._wechat_cfg("delay_range", [8, 12])
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except Exception:
            lo, hi = 8.0, 12.0
        return random.uniform(lo, hi)

    def _rate_limit_backoff(self):
        rng = self._weread_cfg("rate_limit_backoff", [10, 30, 60])
        try:
            return [float(x) for x in rng]
        except Exception:
            return [10.0, 30.0, 60.0]

    # ---------- 通道编排 ----------
    def _build_sources(self):
        """按配置的来源优先级构建通道列表（前一个拿不到数据才降级到下一个）"""
        priority = self._wechat_cfg("source_priority", ["weread"]) or ["weread"]
        sources = []
        for name in priority:
            if name == "weread":
                sources.append(_WereadSource(self.extra_query))
            elif name == "legacy_mp":
                if not self._wechat_cfg("legacy_backend_enabled", False):
                    print("ℹ️ 公众号后台通道(legacy)已在配置中关闭，跳过（其接口自 2026-07 起已失效）")
                    continue
                sources.append(_LegacyMpSource(self))
            else:
                print("⚠️ 未知来源通道配置: %s（已跳过）" % name)

        if not sources:
            print("⚠️ 来源优先级为空或全部被关闭，回退到微信读书通道")
            sources.append(_WereadSource(self.extra_query))
        return sources

    def _fetch_with_backoff(self, source, account_name, limit):
        """
        带限流退避的单号抓取：只有 rate_limited 才重试（token 仍有效，稍后即可），
        登录失效 / 通道不可用属于确定性失败，重试无意义，直接交回编排层降级。
        """
        status, articles, message, stats = source.fetch(account_name, limit)
        backoff = self._rate_limit_backoff()
        for i, wait in enumerate(backoff):
            if status != ST_RATE_LIMITED:
                break
            print("   ⏳ [%s] 触发限流，%.0f 秒后自动重试（第 %d/%d 次）—— 无需重新扫码" % (
                source.label, wait, i + 1, len(backoff)))
            time.sleep(wait)
            status, articles, message, stats = source.fetch(account_name, limit)
        return status, articles, message, stats

    # ---------- legacy 通道的原始实现（保留，默认不调用） ----------
    def load_auth(self):
        if not os.path.exists(self.AUTH_PATH):
            print("❌ 找不到微信后台凭证，请先运行 wechat_harvester.py")
            return None
        try:
            with open(self.AUTH_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("❌ 微信后台凭证解析失败: %s" % e)
            return None

    def fetch_single_account(self, auth, account_name):
        """
        抓取单个公众号，返回文章列表 / "SESSION_EXPIRED" / []。
        注意：该接口自 2026-07 起对「查询他号」恒返回频率控制回执，因此返回 []
        只代表「没有数据」，不代表该号没有发文 —— 状态判定统一由 _LegacyMpSource 负责。
        """
        token = auth["token"]

        # 构造基础 Headers
        headers = {
            "User-Agent": auth["user_agent"],
            "Cookie": "; ".join([f"{k}={v}" for k, v in auth["cookies"].items()]),
            "Host": "mp.weixin.qq.com",
            "X-Requested-With": "XMLHttpRequest"
        }

        # 1. 搜索步骤
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        headers["Referer"] = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isadd=1&type=10&token={token}&lang=zh_CN"

        search_params = {
            "action": "search_biz", "token": token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": account_name, "begin": "0", "count": "5"
        }

        try:
            search_resp = requests.get(search_url, params=search_params, headers=headers, timeout=30)
            search_data = search_resp.json()

            # 检测登录失效：ret 非 0 或 base_resp 报错
            base_ret = search_data.get("base_resp", {}).get("ret", 0)
            if base_ret != 0:
                print(f"❌ 微信后台登录已失效 (ret={base_ret})，需要重新扫码")
                return "SESSION_EXPIRED"

            if not search_data.get("list"):
                print(f"⚠️ 未找到公众号: {account_name}")
                return []

            # 获取 ID 和 昵称
            target_biz = search_data["list"][0]["fakeid"]
            nickname = search_data["list"][0]["nickname"]
            print(f"✅ 匹配到: {nickname}")

            # 2. 获取文章列表步骤（模拟人类从搜索结果点击进入列表的操作）
            print("等待接口响应中...")
            time.sleep(6)

            article_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
            article_params = {
                "action": "list_ex",
                "begin": "0",
                "count": "4",
                "fakeid": target_biz,
                "type": "9",
                "query": "",
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1"
            }

            article_resp = requests.get(article_url, params=article_params, headers=headers, timeout=30)

            if "default" in article_resp.text or article_resp.status_code != 200:
                print(f"❌ {nickname} 抓取异常。状态码: {article_resp.status_code}")
                print(f"🔍 响应原始内容: {article_resp.text[:200]}")
                return []

            article_data = article_resp.json()
            if article_data.get("base_resp", {}).get("ret") == 0:
                articles = article_data.get("app_msg_list", [])
                for a in articles:
                    a['source_account'] = nickname
                    # 生成 raw_hash（基于标题 + 文章链接，稳定不变；算法不可改动）
                    article_title = a.get('title', '')
                    article_link = a.get('link', '')
                    a['raw_hash'] = hashlib.md5((article_title + article_link).encode('utf-8')).hexdigest()
                return articles
            else:
                err_msg = article_data.get('base_resp', {}).get('err_msg', 'unknown error')
                print(f"❌ {nickname} 业务错误: {err_msg}")
                return []

        except Exception as e:
            print(f"💥 {account_name} 系统异常: {str(e)}")
            return []

    # ---------- 产物写入 ----------
    def _write_output(self, articles):
        """
        跨来源去重后写入产物文件。产物字段与旧通道完全同构：
        title / link / update_time / aid / source_account / raw_hash
        （raw_key 为新增的规范身份键，仅用于去重，下游忽略）
        """
        deduped, seen = [], set()
        for a in articles:
            key = a.get("raw_key") or a.get("raw_hash")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)

        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(deduped, f, ensure_ascii=False, indent=4)
        return deduped

    # ---------- 主流程 ----------
    def run_scraper_flow(self, progress_callback=None):
        """
        巡检全部目标号并写入 data/raw/data_raw_wechat.json。

        返回：
            成功  {"success": True, "count": N, ...}
            失败  {"success": False, "error_type": "...", "message": "..."}
        失败时**绝不**再返回 success=True / count=0。
        """
        os.makedirs(os.path.dirname(self.OUTPUT_FILE), exist_ok=True)

        targets = self._targets()
        limit = self._wechat_cfg("fetch_count", 5)
        sources = self._build_sources()

        print("🔔 [微信来源编排] 开始巡检 | 目标公众号 %d 个 | 来源优先级: %s" % (
            len(targets), " → ".join(s.label for s in sources)))

        # 通道就绪检查：凭证缺失等在此暴露，不进入循环才发现
        ready, prep_error, prep_msg = [], None, ""
        for s in sources:
            ok, err, msg = s.prepare()
            if ok:
                ready.append(s)
            else:
                print("   ❌ [%s] 不可用: %s" % (s.label, msg))
                if prep_error is None:
                    prep_error, prep_msg = err, msg

        if not ready:
            self._write_output([])
            print("❌ 所有来源通道均不可用，本轮无法采集")
            return {"success": False,
                    "error_type": prep_error or "AUTH",
                    "message": prep_msg or "所有微信来源通道均不可用，请检查登录凭证"}

        collected = []
        stats_list = []
        failed_targets = []
        auth_expired = rate_limited = unavailable = not_found = empty = 0
        source_hits = {}
        # 登录态自愈每轮至多执行一次（拉起浏览器成本不低，且续期结果全局通用）
        auth_refresh_done = False

        for idx, name in enumerate(targets):
            print("\n--- 任务节点: %s ---" % name)
            got = []
            last_status, last_msg = ST_EMPTY, ""
            last_source = ""

            for src in ready:
                status, articles, message, stats = self._fetch_with_backoff(src, name, limit)

                # 登录态自愈（实测必踩）：服务端会轮换 wr_skey / wr_gid，落盘凭证会
                # 「看起来还在、实际已超时」（-2012 登录超时），而浏览器档案里是有效的新值。
                # 此时先静默续期再重试一次 —— 多数情况可自愈，不必打扰用户扫码。
                if (status == ST_AUTH_EXPIRED and not auth_refresh_done
                        and hasattr(src, "refresh_auth")):
                    auth_refresh_done = True
                    print("   🔄 [%s] 登录态超时，尝试用浏览器档案静默续期（无需扫码）..." % src.label)
                    if src.refresh_auth():
                        status, articles, message, stats = self._fetch_with_backoff(src, name, limit)
                    else:
                        print("   ⚠️ [%s] 静默续期未成功，档案内登录态亦失效，需用户扫码" % src.label)

                last_status, last_msg, last_source = status, message, src.label

                stats = dict(stats or {})
                stats["source"] = src.name
                self._last_stats.append(stats)
                stats_list.append(stats)

                if status == ST_OK and articles:
                    print("   ✅ [%s] 命中 %d 篇（翻 %s 页 / 回执 %s 条）" % (
                        src.label, len(articles), stats.get("pages", "-"), stats.get("items_total", "-")))
                    got = articles
                    source_hits[src.name] = source_hits.get(src.name, 0) + 1
                    break

                if status == ST_AUTH_EXPIRED:
                    auth_expired += 1
                    print("   ❌ [%s] 登录态失效: %s" % (src.label, message))
                elif status == ST_RATE_LIMITED:
                    rate_limited += 1
                    print("   ❌ [%s] 限流且自动重试已耗尽: %s" % (src.label, message))
                elif status == ST_SOURCE_UNAVAILABLE:
                    unavailable += 1
                    print("   ❌ [%s] 通道不可用: %s" % (src.label, message))
                elif status == ST_NOT_FOUND:
                    not_found += 1
                    print("   ⚠️ [%s] 未收录该号" % src.label)
                else:
                    empty += 1
                    print("   ⚠️ [%s] 暂无文章" % src.label)

            collected.extend(got)

            # 失败目标清单：让上层即使部分成功也能如实告知用户哪些号没抓到
            if not got and last_status not in (ST_EMPTY, ST_NOT_FOUND):
                failed_targets.append({
                    "target": name,
                    "status": last_status,
                    "source": last_source,
                    "message": (last_msg or "")[:200],
                })

            if progress_callback:
                # 回调契约与其余采集器保持一致：(current, total, message)
                try:
                    progress_callback(idx + 1, len(targets), "已抓取: %s" % name)
                except Exception:
                    pass

            # 凭证失效是**全局性**问题：继续对剩余目标发请求只会重复失败，还要白等
            # 每个目标 8~12 秒的切换间隔（9 个号就是一分多钟的无效等待）。
            # 这里直接结束本轮，把 SESSION_EXPIRED 如实上报，让上层引导用户扫码。
            if last_status == ST_AUTH_EXPIRED and not got:
                print("⏹️ 检测到登录态失效（全局性问题），提前结束本轮巡检；"
                      "剩余 %d 个目标不再发起无谓请求" % max(0, len(targets) - idx - 1))
                break

            if idx < len(targets) - 1:
                wait = self._delay()
                print("   正在切换下一个目标，等待 %.1fs ..." % wait)
                time.sleep(wait)

        deduped = self._write_output(collected)

        print("\n✨ [微信来源编排] 巡检完成 | 去重前 %d 条 → 去重后 %d 条" % (len(collected), len(deduped)))
        print("📂 数据已存入: %s" % self.OUTPUT_FILE)
        if source_hits:
            print("📊 各通道命中目标数: %s" % ", ".join(
                "%s=%d" % (k, v) for k, v in source_hits.items()))
        if failed_targets:
            print("⚠️ 本轮异常目标 %d 个: %s" % (
                len(failed_targets), ", ".join(t["target"] for t in failed_targets)))

        # ---------- 失败语义：只要有数据就成功返回（并附带异常目标清单） ----------
        if deduped:
            result = {"success": True, "count": len(deduped),
                      "total_scanned": sum(s.get("items_total", 0) for s in stats_list)}
            if failed_targets:
                result["failed_targets"] = failed_targets
                result["message"] = "已取回 %d 条，但 %d 个目标异常：%s" % (
                    len(deduped), len(failed_targets),
                    ", ".join("%s(%s)" % (t["target"], STATUS_TO_ERROR_TYPE.get(t["status"], t["status"]))
                              for t in failed_targets))
            return result

        # 无数据时按主因判定，保证「失败」与「确实没发文」可区分
        if auth_expired:
            return {"success": False, "error_type": "SESSION_EXPIRED",
                    "message": "微信登录态已失效（%d 个目标失败），自动静默续期未能恢复，"
                               "请重新扫码登录后重试" % auth_expired,
                    "failed_targets": failed_targets}
        if rate_limited:
            return {"success": False, "error_type": "RATE_LIMITED",
                    "message": "微信数据源触发限流且自动重试已耗尽，请稍后重试即可，无需重新扫码",
                    "failed_targets": failed_targets}
        if unavailable and unavailable >= len(targets):
            return {"success": False, "error_type": "SOURCE_UNAVAILABLE",
                    "message": "微信数据源当前不可用（%d 个目标请求全部失败），请稍后重试" % unavailable,
                    "failed_targets": failed_targets}
        if not_found == len(targets) and targets:
            return {"success": False, "error_type": "NOT_FOUND",
                    "message": "配置的 %d 个目标公众号均未被数据源收录，请检查公众号名称是否正确" % len(targets),
                    "failed_targets": failed_targets}
        if targets and empty == len(targets):
            # 通道全部正常、每个号都确实没有新文章 —— 这是正常结果，不是失败
            return {"success": True, "count": 0,
                    "message": "通道正常，%d 个目标公众号本轮均无文章" % len(targets)}
        if failed_targets:
            return {"success": False, "error_type": "SOURCE_UNAVAILABLE",
                    "message": "本轮未取回任何文章，异常目标 %d 个：%s" % (
                        len(failed_targets),
                        ", ".join("%s(%s)" % (t["target"], STATUS_TO_ERROR_TYPE.get(t["status"], t["status"]))
                                  for t in failed_targets)),
                    "failed_targets": failed_targets}
        return {"success": True, "count": 0,
                "message": "本轮无新增文章"}


def run_wechat_scraper_flow(extra_query=None, progress_callback=None):
    """
    供外部接口（如 main.py / tools_config / backend）直接调用的包装函数。
    extra_query: 可选，额外抓取的公众号名称
    progress_callback: 可选，进度回调函数
    """
    scraper = WechatScraper(extra_query=extra_query)
    return scraper.run_scraper_flow(progress_callback=progress_callback)


def _print_report(file_path=None):
    """把产物按公众号分组打印为「标题 / 时间 / 链接」清单，便于人工核查采集质量"""
    file_path = file_path or WechatScraper.OUTPUT_FILE
    if not os.path.exists(file_path):
        print("未找到产物文件: %s" % file_path)
        return
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("\n" + "=" * 100)
    print("采集结果明细（共 %d 篇）" % len(data))
    print("=" * 100)
    groups = {}
    for a in data:
        groups.setdefault(a.get("source_account") or "未知", []).append(a)
    for name, items in groups.items():
        print("\n【%s】%d 篇" % (name, len(items)))
        for a in items:
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(a.get("update_time") or 0))
            print("  - %s" % a.get("title"))
            print("      时间: %s | aid: %s" % (t, a.get("aid")))
            print("      链接: %s" % a.get("link"))
    print("\n" + "=" * 100)


if __name__ == "__main__":
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    result = run_wechat_scraper_flow()
    print("\n返回值: %s" % json.dumps(result, ensure_ascii=False))
    _print_report()
