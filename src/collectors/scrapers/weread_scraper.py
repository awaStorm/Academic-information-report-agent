# -*- coding: utf-8 -*-
"""
微信读书通道采集器（当前主数据源，纯通道层）

背景：
    原微信公众号后台通道（searchbiz + appmsg/list_ex）已对「查询他号」精准软拒绝，
    抓取结果恒为空列表。改为复用微信读书 Web 端「搜一搜」数据源
    POST https://weread.qq.com/web/wx_search_broker_proxy，
    该接口已由探针实测确认：9/9 目标公众号可精确命中，返回条目含
    标题 / 正文链接 / 公众号名 / 发布时间戳。

职责边界（重要）：
    本模块**只负责「按号取文章」**：检索 → 分页 → 精确过滤该号 → 归一化为
    与旧后台通道同构的原始文章结构。
    「遍历目标号 / 来源优先级 / 限流退避 / 写产物」由编排层
    src/collectors/scrapers/wechat_scraper.py 统一负责（单一写入口，避免两处写同一文件）。

接口契约（实测确认）：
    POST https://weread.qq.com/web/wx_search_broker_proxy
    body: {"query": <公众号名>, "offset": 0, "searchcookies": "", "searchid": ""}
    回执: {"ret": -1, "msg": "", "content": {"ret": 0, "data": [ {items: [...]}, ... ]}}
    注意：顶层 ret 恒为 -1，成功判定必须看 content 是否存在及其 data 列表。

翻页契约（实测确认）：
    把上一页回执的 content.offset / content.cookies / content.searchID 原样回传为
    请求侧 offset / searchcookies / searchid（请求侧字段名为小写 searchid，仅传 offset 无效），
    即可取到下一页全新内容。单页固定 15 条，15 条并非硬上限。

状态语义（编排层复用同一套常量，避免两套字符串各自漂移）：
    ok / not_found / empty / auth_expired / rate_limited /
    source_unavailable / error
"""
import hashlib
import json
import os
import random
import re
import time

import requests

from src.utils.config_loader import CONFIG

# ---------- 统一状态语义 ----------
ST_OK = "ok"                              # 成功拿到文章
ST_NOT_FOUND = "not_found"                # 目标公众号不存在 / 未被收录
ST_EMPTY = "empty"                        # 通道正常但该号确实暂无文章
ST_AUTH_EXPIRED = "auth_expired"          # 登录态失效，需重新扫码
ST_RATE_LIMITED = "rate_limited"          # 触发限流，token 仍有效，稍后重试即可
ST_SOURCE_UNAVAILABLE = "source_unavailable"  # 通道不可用（接口关闭 / 被反爬拦截）
ST_ERROR = "error"                        # 未知错误，需记录完整原始回执

# 分页抓取默认参数（可由 configs/settings.yaml 的 collectors.weread 覆盖）
DEFAULT_MAX_PAGES = 2                     # 单号最多翻几页；页码越深相关度越低，2 页足以覆盖该号近几天
DEFAULT_PAGE_INTERVAL = (3, 5)            # 同号翻页之间的等待区间（秒）
DEFAULT_TIMEOUT = 30                      # 单次请求超时（秒）
DEFAULT_RETRIES = 3                       # 网络层重试次数

# 回执无法正常解析时，按回执**可读文本**区分「登录失效」与「限流」。
# 踩坑记录（2026-09-13 实测）：微信读书在登录态失效时返回
#     {"errCode":-2012,"errMsg":"登录超时","errLog":"C8NI2To","info":""}
# 早期词表只含「未登录 / 登录失效 / 请先登录」，漏掉「登录超时」，于是这条
# **明确的登录失效**被误判成「数据源不可用」，进而让 Agent 理直气壮地拒绝引导扫码。
# 另外注意：字段名是 errMsg（不是 msg），早期只读 errCode/msg 会把最有价值的原文丢掉。
AUTH_EXPIRED_HINTS = ("未登录", "登录失效", "请先登录", "登录超时", "登录过期",
                      "重新登录", "登录凭证", "凭证失效", "未授权", "授权失效",
                      "login required", "not login", "invalid session",
                      "login timeout", "unauthorized", "session expired")
RATE_LIMIT_HINTS = ("frequency", "too many", "rate limit", "ratelimit",
                    "频繁", "限流", "请求过快", "操作过快", "稍后再试")

# 已实测确认语义的 errCode（未确认的数值一律不作为判定依据，宁可归入 error 上报原文）
AUTH_EXPIRED_CODES = (-2012,)  # -2012 = 登录超时（需刷新凭证或重新扫码）


def _match_any(text, hints):
    low = (text or "").lower()
    return any(h.lower() in low for h in hints)


def clean_html(text):
    """去掉搜一搜回执中标红用的 <em class="highlight"> 等标签"""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def build_raw_key(link, source_account, title):
    """
    文章规范身份键（跨来源去重用，非破坏式新增，不影响旧 raw_hash 算法）。
    优先使用文章真实身份（__biz + mid + idx），缺失时退化为「来源公众号 + 标题」。
    """
    link = link or ""
    biz = re.search(r"[?&]__biz=([^&#]+)", link)
    mid = re.search(r"[?&]mid=(\d+)", link)
    if biz and mid:
        idx = re.search(r"[?&]idx=(\d+)", link)
        return "mpx:%s:%s:%s" % (biz.group(1), mid.group(1), idx.group(1) if idx else "1")
    return "mpt:%s:%s" % (source_account or "", (title or "").strip())


class WereadScraper:
    """微信读书通道采集器（纯通道层：按号取文章，不写文件）"""

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    AUTH_PATH = os.path.join(base_dir, "configs", "weread_auth.json")

    PROXY_URL = "https://weread.qq.com/web/wx_search_broker_proxy"

    def __init__(self, extra_query=None, fetch_count=None, targets=None):
        self.extra_query = extra_query
        self.fetch_count = fetch_count
        self.targets = targets

    # ---------- 配置 ----------
    @staticmethod
    def _cfg(key, default=None):
        return CONFIG.get("collectors", {}).get("weread", {}).get(key, default)

    def _page_interval(self):
        rng = self._cfg("page_interval", list(DEFAULT_PAGE_INTERVAL))
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except Exception:
            lo, hi = DEFAULT_PAGE_INTERVAL
        return random.uniform(lo, hi)

    def _timeout(self):
        try:
            return float(self._cfg("timeout", DEFAULT_TIMEOUT))
        except Exception:
            return float(DEFAULT_TIMEOUT)

    def _retries(self):
        try:
            return int(self._cfg("retries", DEFAULT_RETRIES))
        except Exception:
            return DEFAULT_RETRIES

    # ---------- 凭证 ----------
    def load_auth(self):
        if not os.path.exists(self.AUTH_PATH):
            print("❌ 找不到微信读书凭证，请先运行 weread_harvester.py 扫码登录")
            return None
        try:
            with open(self.AUTH_PATH, "r", encoding="utf-8") as f:
                auth = json.load(f)
        except Exception as e:
            print("❌ 微信读书凭证解析失败: %s" % e)
            return None
        if not (auth.get("cookies") or auth.get("user_agent")):
            print("❌ 微信读书凭证内容不完整（缺少 cookies / user_agent）")
            return None
        return auth

    def build_session(self, auth):
        s = requests.Session()
        # 本机代理会让 127.0.0.1 与部分域名异常，这里显式忽略环境代理
        s.trust_env = False
        s.headers.update({
            "User-Agent": auth.get("user_agent") or "Mozilla/5.0",
            "Referer": "https://search.weixin.qq.com/",
            "Origin": "https://search.weixin.qq.com",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
        })
        for k, v in (auth.get("cookies") or {}).items():
            s.cookies.set(k, v, domain="weread.qq.com")
        return s

    # ---------- 凭证续期 ----------
    def refresh_auth(self):
        """
        用持久化浏览器档案静默续期，刷新被服务端轮换的 cookie 并落盘。

        为什么需要（实测依据）：
            服务端会轮换 wr_skey / wr_gid，于是落盘凭证「看起来还在、实际已超时」——
            同一时刻用两套 cookie 请求同一接口：
                落盘值   -> {"errCode":-2012,"errMsg":"登录超时"}   （被拒）
                档案新值 -> {"content":{...}}                       （正常）
            也就是说，这种情况**根本不需要用户重新扫码**，刷新一次即可自愈。
            早期没有这一步，导致「抓取失败 → 提示扫码 → 用户白扫一次 → 依旧失败」。

        返回 True 表示已拿到一份经业务接口验证有效的新凭证。
        """
        try:
            from src.collectors.sessions.weread_harvester import WereadHarvester
        except Exception as e:
            print("   ⚠️ 无法加载凭证续期器（可能缺少 playwright）: %s" % e)
            return False
        return bool(WereadHarvester().refresh_cookies())

    # ---------- 检索 ----------
    def _post_proxy(self, session, payload, timeout=None, attempts=None):
        """带宽容重试的检索请求；返回 (status, data_or_none, raw_text)"""
        timeout = timeout or self._timeout()
        attempts = attempts or self._retries()
        last_err = None
        for i in range(attempts):
            try:
                r = session.post(self.PROXY_URL, data=json.dumps(payload), timeout=timeout)
            except Exception as e:
                last_err = "网络异常: %s" % e
                print("   ⏳ 检索请求异常（第 %d/%d 次）: %s" % (i + 1, attempts, e))
                time.sleep(2 * (i + 1))
                continue
            if r.status_code != 200:
                last_err = "HTTP %s" % r.status_code
                print("   ⏳ 检索请求返回 HTTP %s（第 %d/%d 次）" % (r.status_code, i + 1, attempts))
                time.sleep(2 * (i + 1))
                continue
            try:
                return r.status_code, r.json(), r.text
            except Exception:
                last_err = "回执非 JSON"
                print("   ⏳ 回执无法解析为 JSON（第 %d/%d 次）" % (i + 1, attempts))
                time.sleep(2 * (i + 1))
        return -1, None, last_err or "未知错误"

    def search_articles(self, session, query, offset=0, searchcookies="", searchid="", timeout=None):
        """
        按关键词检索单页，返回 {"status": ..., "articles": [...], "message": ..., "cursor": {...}}
        articles 每项为归一化后的原始文章结构（已含 raw_hash / raw_key）。
        """
        payload = {"query": query, "offset": offset, "searchcookies": searchcookies, "searchid": searchid}
        status_code, data, raw = self._post_proxy(session, payload, timeout=timeout)

        def _fail(st, msg):
            return {"status": st, "articles": [], "message": msg, "cursor": {"continue": False}}

        if status_code in (401, 403):
            return _fail(ST_AUTH_EXPIRED, "登录态失效 (HTTP %s)" % status_code)
        if status_code in (429, 503):
            return _fail(ST_RATE_LIMITED, "触发限流 (HTTP %s)" % status_code)
        if status_code == -1 or not isinstance(data, dict):
            return _fail(ST_SOURCE_UNAVAILABLE, "通道不可用: %s" % str(raw)[:200])
        if status_code != 200:
            return _fail(ST_SOURCE_UNAVAILABLE, "通道返回 HTTP %s" % status_code)

        content = data.get("content")

        # 偶发空回执：实测出现 {"content": null, "msg": "", "ret": 0} —— HTTP 通、ret=0，
        # 但没给 content。同一目标号在其它轮次可正常返回，属于服务端抖动，
        # 因此先原地重试一次；不要直接当作故障上报（那会误导用户以为数据源挂了）。
        if content is None and data.get("ret") == 0 and not data.get("errCode"):
            time.sleep(1.5)
            retry_code, retry_data, retry_raw = self._post_proxy(
                session, payload, timeout=timeout, attempts=1)
            if retry_code == 200 and isinstance(retry_data, dict):
                status_code, data, raw = retry_code, retry_data, retry_raw
                content = data.get("content")

        if not isinstance(content, dict):
            # 无 content 段：实测微信读书在登录态失效时返回
            #   {"errCode":-2012,"errMsg":"登录超时","errLog":"...","info":""}
            # 判定顺序：先看可读原文（字段名是 errMsg，不是 msg），再看已实测确认的 errCode。
            # 注意不要改回「只匹配 errCode」：errMsg 才是能自解释、可维护的判据。
            snippet = json.dumps(data, ensure_ascii=False)[:300]
            code = data.get("errCode")
            notice = str(data.get("errMsg") or data.get("msg") or "").strip()
            if code in AUTH_EXPIRED_CODES or _match_any(notice, AUTH_EXPIRED_HINTS):
                return _fail(ST_AUTH_EXPIRED, "登录态失效（%s）: %s" % (notice or code, snippet))
            if _match_any(notice, RATE_LIMIT_HINTS):
                return _fail(ST_RATE_LIMITED, "触发限流（%s）: %s" % (notice or code, snippet))
            # ret=0 且无 content：接口调用成功但本次没有结果，属于「该号未收录/暂无内容」语义。
            # 绝不能报成 SOURCE_UNAVAILABLE —— 那会让用户误以为数据源故障而去等恢复或白扫一次码。
            if code is None and data.get("ret") == 0:
                return _fail(ST_NOT_FOUND, "检索回执为空（ret=0 且无 content，重试后依然为空）")
            hint = str(notice or code or "")
            return _fail(ST_SOURCE_UNAVAILABLE,
                         "回执缺少 content 段%s: %s" % ("(" + hint + ")" if hint else "", snippet))

        inner_ret = content.get("ret")
        if inner_ret not in (0, None):
            return _fail(ST_SOURCE_UNAVAILABLE, "content.ret=%s，回执: %s" % (
                inner_ret, json.dumps(data, ensure_ascii=False)[:200]))

        articles = self._extract_articles(content.get("data") or [])
        next_offset = content.get("offset")
        cursor = {
            "offset": next_offset if next_offset is not None else offset,
            "searchcookies": content.get("cookies") or "",
            "searchid": str(content.get("searchID") or ""),
            "continue": bool(content.get("continueFlag")) and bool(articles),
        }
        return {"status": ST_OK if articles else ST_EMPTY,
                "articles": articles, "message": "", "cursor": cursor}

    @staticmethod
    def _extract_articles(boxes):
        """遍历 content.data 的盒子结构，归一化为与旧后台通道同构的文章对象"""
        out = []
        for box in boxes:
            for it in (box.get("items") or []):
                title = clean_html(it.get("title"))
                link = (it.get("doc_url") or "").split("#")[0].replace("http://", "https://")
                source = (it.get("source") or {}).get("title") or ""
                update_time = it.get("timestamp") or it.get("date") or 0
                if not title or not link:
                    continue
                out.append({
                    # ↓ 与旧后台通道同构的字段（下游依赖）
                    "title": title,
                    "link": link,
                    "update_time": int(update_time),
                    "aid": str(it.get("docID") or ""),
                    "source_account": source,
                    "raw_hash": hashlib.md5((title + link).encode("utf-8")).hexdigest(),
                    "raw_key": build_raw_key(link, source, title),
                    # ↓ 仅用于人工核查与排查的附加字段，下游忽略
                    "publish_text": (it.get("source") or {}).get("dateTime") or "",
                    "desc": clean_html(str(it.get("desc") or ""))[:200],
                    "thumb": it.get("thumbUrl") or "",
                    "matched_query": "",
                })
        return out

    def fetch_account_articles(self, session, account_name, limit=None, max_pages=None):
        """
        拉取单个公众号的文章（按名称检索 + 分页 + 精确过滤该号）。
        返回 {"status": ..., "articles": [...], "message": ..., "stats": {...}}

        单页回执固定 15 条且按相关度（近似倒序时间）排列，深页码相关度递减。
        因此策略为：能翻则翻，直到「已够 limit 篇」或「达到 max_pages」
        或「回执无下一页」或「本页无新内容」为止，避免无意义地打深页码。
        """
        if max_pages is None:
            max_pages = self._cfg("max_pages", DEFAULT_MAX_PAGES)

        stats = {"query": account_name, "items_total": 0, "exact": 0, "pages": 0, "other_sources": []}

        exact, seen_keys = [], set()
        other_sources = set()
        offset, searchcookies, searchid = 0, "", ""
        last_status = ST_EMPTY

        for page in range(1, max(1, int(max_pages)) + 1):
            res = self.search_articles(session, account_name, offset=offset,
                                       searchcookies=searchcookies, searchid=searchid)
            stats["pages"] = page
            last_status = res["status"]

            if res["status"] in (ST_AUTH_EXPIRED, ST_SOURCE_UNAVAILABLE, ST_RATE_LIMITED):
                stats["message"] = res["message"]
                if not exact:  # 完全拿不到数据才判定失败，已有部分数据则尽力返回
                    return {**res, "stats": stats}
                break

            items = res["articles"]
            stats["items_total"] += len(items)
            fresh = 0
            for a in items:
                if a["source_account"] == account_name:
                    a["matched_query"] = account_name
                    if a["raw_key"] not in seen_keys:
                        seen_keys.add(a["raw_key"])
                        exact.append(a)
                        fresh += 1
                elif a["source_account"]:
                    other_sources.add(a["source_account"])

            cursor = res.get("cursor") or {}
            # 注意：**不因「已够 limit 篇」而提前停止翻页**。
            # 实测依据（单页回执内同一公众号条目的时间序列非单调递减）：
            #   西小电星球第 1 页: 09-07 / 09-09 / 09-11 / 08-31 / 07-13 ...
            #   西电青年   第 1 页: 08-14 / 08-24 / 09-10 / 09-09 / 2025-04 / 2023-03
            # 即回执为「相关度序」而非「时间序」，更新的文章可能排在更靠后的位置，
            # 甚至落在下一页。一旦提前停止，就会出现「该号最新 N 篇」静默漏掉更新文章。
            # 因此这里翻满 max_pages，最后再统一按发布时间降序截断。
            if not cursor.get("continue") or not items:
                break
            if page == 1 and fresh == 0:
                # 首页就没有任何该号文章，继续翻页收益极低，直接停手
                break

            offset = cursor.get("offset", offset)
            searchcookies = cursor.get("searchcookies", "")
            searchid = cursor.get("searchid", "")
            time.sleep(self._page_interval())

        stats["exact"] = len(exact)
        stats["other_sources"] = sorted(other_sources)

        exact.sort(key=lambda x: x.get("update_time", 0), reverse=True)
        if limit:
            exact = exact[:int(limit)]

        if not exact:
            # 语义必须精确区分，否则编排层会把「确实没文章」误判为「抓取失败」：
            #   回执里有条目、但都不是该号 → 通道正常、该号暂无文章（empty）
            #   回执里完全没有条目      → 该号未被收录（not_found）
            # （此前这里沿用循环末尾的接口状态，可能是 ok，导致 empty 被错记成失败目标）
            return {"status": ST_NOT_FOUND if stats["items_total"] == 0 else ST_EMPTY,
                    "articles": [],
                    "message": "检索回执中无该号文章（通道状态=%s）" % last_status,
                    "stats": stats}
        return {"status": ST_OK, "articles": exact, "message": "", "stats": stats}


if __name__ == "__main__":
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 本模块只是通道层：「跑一轮 + 写产物」由编排层负责（单一写入口，避免两处写同一文件）
    from src.collectors.scrapers.wechat_scraper import run_wechat_scraper_flow, _print_report

    result = run_wechat_scraper_flow()
    print("\n返回值: %s" % json.dumps(result, ensure_ascii=False))
    if result.get("success"):
        _print_report()
