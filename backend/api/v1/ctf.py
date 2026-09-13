"""
backend/api/v1/ctf.py - CTFtime 赛事抓取 API (v5)
- 修复日期解析：纯文本日期（如 "May 1-7, 2026"）正确解析为 ISO 时间戳
- 修复 compute_status：时间不可解析时返回 "unknown" 而非 "upcoming"
- 修复翻页逻辑：去重后无新增即停，不再误判
- 异步刷新：/refresh 立即返回，后台线程执行，/refresh/status 轮询进度
- JSON 缓存 + 每天中午 12:00 自动刷新
- 大头钉（关注/置顶）功能
"""
import sys
import json
import logging
import re
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, List, Tuple

from fastapi import APIRouter, Query
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter()
logger = logging.getLogger("ctf_api")

# ---- 缓存路径 ----
DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "ctf_cache.json"
PINS_FILE = DATA_DIR / "ctf_pins.json"

CTFTIME_BASE = "https://ctftime.org"
CTFTIME_UPCOMING = f"{CTFTIME_BASE}/event/list/upcoming/"
CTFTIME_LIST = f"{CTFTIME_BASE}/event/list/"
RECENTLY_ENDED_DAYS = 14       # 近两周内结束的保留
OFFICIAL_URL_BATCH = 20        # 每轮刷新最多补抓 Official URL
REQUEST_DELAY = 0.6            # 请求间隔（秒）

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ---- 月份名称映射 (用于解析纯文本日期) ----
_MONTH_MAP: dict = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ---- 异步刷新状态 ----
_refresh_lock = threading.Lock()
_refresh_state: dict = {
    "running": False,
    "phase": "",        # 当前阶段描述
    "message": "",      # 完成/失败信息
}

# ============ 工具函数 ============

def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_refresh": None, "events": []}

def save_cache(data: dict):
    ensure_data_dir()
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_pins() -> dict:
    if PINS_FILE.exists():
        try:
            return json.loads(PINS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"pinned_ids": []}

def save_pins(data: dict):
    ensure_data_dir()
    PINS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def should_refresh() -> bool:
    """判断是否需要刷新：上次刷新时间 < 今天中午12点 <= 当前时间"""
    cache = load_cache()
    last = cache.get("last_refresh")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return True
    now = datetime.now()
    noon_today = datetime.combine(now.date(), dt_time(12, 0))
    return last_dt < noon_today <= now


# ============ 日期解析（核心修复）============

def _parse_ctftime_date(date_text: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    解析 CTFtime 纯文本日期为 (start_dt, end_dt)。
    支持格式：
      - "July 01, 2026" / "01 July, 2026"
      - "July 01-07, 2026" (同月区间)
      - "July 01, 2026 — July 07, 2026" (跨格式)
      - "July 01, 2026, 12:00 UTC — July 03, 2026, 12:00 UTC"
    返回 (None, None) 表示无法解析。
    """
    if not date_text or not date_text.strip():
        return None, None

    text = date_text.strip()

    # 去除时间信息（如 "12:00 UTC", "21:00 UTC"）以简化匹配
    text_clean = re.sub(r',?\s*\d{1,2}:\d{2}\s*(?:UTC|utc)', '', text).strip()
    # 去除前导星期几
    text_clean = re.sub(r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+', '', text_clean, flags=re.IGNORECASE).strip()
    # 清理残留的孤逗号和多余空白
    text_clean = re.sub(r'\s*,\s*—', ' —', text_clean)
    text_clean = re.sub(r'\s{2,}', ' ', text_clean).strip()

    month_names = '|'.join(_MONTH_MAP.keys())

    # --- 尝试 1: 跨月区间 "Month DD, YYYY — Month DD, YYYY" ---
    full_range = re.match(
        rf'({month_names})\s+(\d{{1,2}}),?\s*(\d{{4}})\s*[-–—]+\s*({month_names})\s+(\d{{1,2}}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if full_range:
        m1, d1, y1, m2, d2, y2 = full_range.groups()
        m1n = _MONTH_MAP.get(m1.lower(), 0)
        m2n = _MONTH_MAP.get(m2.lower(), 0)
        if m1n and m2n:
            start = datetime(int(y1), m1n, int(d1))
            end = datetime(int(y2), m2n, int(d2), 23, 59, 59)
            return start, end

    # --- 尝试 2: 跨月区间（前半缺年份）"DD Month — DD Month YYYY" ---
    # upcoming 页面常见格式: "03 July, 21:00 UTC — 04 July 2026, 06:00 UTC"
    # 去除时间后: "03 July — 04 July 2026"
    asym_range_dm = re.match(
        rf'(\d{{1,2}})\s+({month_names})\s*[-–—]+\s*(\d{{1,2}})\s+({month_names}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if asym_range_dm:
        d1, m1, d2, m2, y2 = asym_range_dm.groups()
        m1n = _MONTH_MAP.get(m1.lower(), 0)
        m2n = _MONTH_MAP.get(m2.lower(), 0)
        if m1n and m2n:
            start = datetime(int(y2), m1n, int(d1))  # 年份从后半推断
            end = datetime(int(y2), m2n, int(d2), 23, 59, 59)
            return start, end

    # --- 尝试 3: 跨月区间（前半缺年份）"Month DD — Month DD YYYY" ---
    asym_range_md = re.match(
        rf'({month_names})\s+(\d{{1,2}})\s*[-–—]+\s*({month_names})\s+(\d{{1,2}}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if asym_range_md:
        m1, d1, m2, d2, y2 = asym_range_md.groups()
        m1n = _MONTH_MAP.get(m1.lower(), 0)
        m2n = _MONTH_MAP.get(m2.lower(), 0)
        if m1n and m2n:
            start = datetime(int(y2), m1n, int(d1))
            end = datetime(int(y2), m2n, int(d2), 23, 59, 59)
            return start, end

    # --- 尝试 4: 同月区间（前半缺年份）"DD-DD Month YYYY" ---
    asym_same_month = re.match(
        rf'(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({month_names}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if asym_same_month:
        d1, d2, m, y = asym_same_month.groups()
        mn = _MONTH_MAP.get(m.lower(), 0)
        if mn:
            start = datetime(int(y), mn, int(d1))
            end = datetime(int(y), mn, int(d2), 23, 59, 59)
            return start, end

    # --- 尝试 5: 同月区间 "Month DD-DD, YYYY" ---
    same_month_range = re.match(
        rf'({month_names})\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if same_month_range:
        m, d1, d2, y = same_month_range.groups()
        mn = _MONTH_MAP.get(m.lower(), 0)
        if mn:
            start = datetime(int(y), mn, int(d1))
            end = datetime(int(y), mn, int(d2), 23, 59, 59)
            return start, end

    # --- 尝试 6: 单日 "Month DD, YYYY" ---
    single_md = re.match(
        rf'({month_names})\s+(\d{{1,2}}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if single_md:
        mn = _MONTH_MAP.get(single_md.group(1).lower(), 0)
        if mn:
            start = datetime(int(single_md.group(3)), mn, int(single_md.group(2)))
            return start, None

    # --- 尝试 7: 单日 "DD Month, YYYY" ---
    single_dm = re.match(
        rf'(\d{{1,2}})\s+({month_names}),?\s*(\d{{4}})',
        text_clean, re.IGNORECASE,
    )
    if single_dm:
        mn = _MONTH_MAP.get(single_dm.group(2).lower(), 0)
        if mn:
            start = datetime(int(single_dm.group(3)), mn, int(single_dm.group(1)))
            return start, None

    return None, None


def _try_parse_event_time(event: dict, key: str) -> Optional[datetime]:
    """尝试从 event[key] 解析 ISO 时间，失败则返回 None"""
    val = event.get(key)
    if not val or not isinstance(val, str):
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def _try_parse_date_text(date_text: str, *, as_end: bool = False) -> Optional[datetime]:
    """从 date_text 纯文本解析出时间"""
    start_dt, end_dt = _parse_ctftime_date(date_text)
    if as_end:
        return end_dt or start_dt  # 如果没有 end 就 fallback 到 start
    return start_dt


def compute_status(event: dict) -> str:
    """
    根据 start_time / end_time 计算赛事状态。
    当时间完全不可解析时返回 "unknown"（会被过滤掉）。
    """
    now = datetime.now()

    # 1) 优先从 ISO 字段解析
    start_dt = _try_parse_event_time(event, "start_time")
    end_dt = _try_parse_event_time(event, "end_time")

    # 2) start_time 失败 → 尝试从 date_text 解析
    if start_dt is None:
        start_dt = _try_parse_date_text(event.get("date", ""), as_end=False)

    # 3) end_time 失败 → 尝试从 date_text 解析 end
    if end_dt is None:
        end_dt = _try_parse_date_text(event.get("date", ""), as_end=True)

    # 4) 仍然无法确定时间 → unknown（会被下游过滤）
    if start_dt is None:
        return "unknown"

    # 5) 已结束
    if end_dt and end_dt < now:
        cutoff = now - timedelta(days=RECENTLY_ENDED_DAYS)
        return "recently_ended" if end_dt >= cutoff else "expired"

    # 6) 已开始但未结束 → 进行中
    if start_dt <= now:
        return "running"

    # 7) 未开始 → 即将到来
    return "upcoming"


# ============ 页面抓取 ============

def parse_event_row(cols) -> Optional[dict]:
    """解析表格单行 -> 事件 dict (v5: 修复日期解析)"""
    if len(cols) < 5:
        return None

    name_el = cols[0].find("a")
    name = name_el.text.strip() if name_el else cols[0].text.strip()

    eid = ""
    ctftime_url = ""
    if name_el and name_el.get("href"):
        href = name_el["href"]
        ctftime_url = f"{CTFTIME_BASE}{href}" if href.startswith("/") else href
        parts = href.strip("/").split("/")
        for i, p in enumerate(parts):
            if p == "event" and i + 1 < len(parts):
                eid = parts[i + 1]
                break
    if not eid:
        eid = name

    date_text = cols[1].text.strip()

    # ---- 策略 1: 从 <span data-utc> 提取 ISO 时间戳 ----
    start_time = None
    end_time = None
    for span in cols[1].find_all("span"):
        utc = span.get("data-utc") or span.get("title", "")
        if utc:
            try:
                dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
                if start_time is None:
                    start_time = dt.isoformat()
                else:
                    end_time = dt.isoformat()
            except (ValueError, TypeError):
                pass

    # ---- 策略 2 (v5 新增): 纯文本日期解析 ----
    if start_time is None and date_text:
        parsed_start, parsed_end = _parse_ctftime_date(date_text)
        if parsed_start:
            start_time = parsed_start.isoformat()
        if parsed_end:
            end_time = parsed_end.isoformat()

    # ---- 兜底: 保留原始文本供调试 ----
    if start_time is None:
        start_time = date_text

    fmt = cols[2].text.strip()
    loc = cols[3].text.strip()
    wt_text = cols[4].text.strip() if len(cols) > 4 else "0.00"
    notes = cols[5].text.strip() if len(cols) > 5 else ""

    try:
        weight = float(wt_text)
    except ValueError:
        weight = 0.0

    return {
        "id": eid,
        "name": name,
        "ctftime_url": ctftime_url,
        "official_url": "",
        "date": date_text,
        "start_time": start_time,
        "end_time": end_time,
        "format": fmt,
        "location": loc,
        "weight": weight,
        "notes": notes,
        "status": "",  # 稍后由 compute_status 填充
    }


def scrape_page(url: str, session: requests.Session = None, max_retries: int = 3) -> List[dict]:
    """抓取单个页面（含指数退避重试），返回事件列表"""
    _session = session or requests.Session()
    for attempt in range(max_retries):
        try:
            resp = _session.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            break  # 成功 → 跳出重试循环
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}, {wait}s 后重试): {url}")
                time.sleep(wait)
            else:
                logger.warning(f"请求失败 ({url}，已重试 {max_retries} 次): {e}")
                return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # 定位表格
    table = None
    for t in soup.find_all("table"):
        cls = " ".join(t.get("class", [])).lower()
        tid = (t.get("id", "") or "").lower()
        if "event" in cls or "event" in tid:
            table = t
            break
    if table is None:
        table = soup.find("table", {"class": lambda c: c and "table" in c})

    if table is None:
        return []

    rows = table.find_all("tr")[1:]
    events = []
    for row in rows:
        cols = row.find_all("td")
        evt = parse_event_row(cols)
        if evt:
            events.append(evt)

    return events


def scrape_official_url(ctftime_url: str) -> str:
    """从赛事详情页抓取 Official URL"""
    try:
        resp = requests.get(ctftime_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 策略1: 含 "Official" 的相邻 <a>
        for tag in soup.find_all(["h3", "h4", "dt", "th", "span", "strong", "p"]):
            if "official" in tag.get_text().lower():
                parent = tag.parent
                if parent:
                    a = parent.find("a", href=True)
                    if a and "ctftime.org" not in a["href"]:
                        href = a["href"].strip()
                        if href.startswith("http"):
                            return href

        # 策略2: rel="nofollow" 外链
        for a in soup.find_all("a", rel=lambda r: r and "nofollow" in " ".join(r) if isinstance(r, list) else r):
            href = (a.get("href") or "").strip()
            if href.startswith("http") and "ctftime.org" not in href:
                txt = a.get_text().strip()
                if len(txt) > 3:
                    return href

        # 策略3: 兜底
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            txt = a.get_text().strip()
            if not href.startswith("http") or "ctftime.org" in href:
                continue
            skip = ["facebook", "twitter", "discord", "irc", "github", "linkedin"]
            if any(s in href.lower() for s in skip):
                continue
            if len(txt) > 3 and "/event/" not in href:
                return href

    except Exception as e:
        logger.debug(f"抓取 Official URL 失败 ({ctftime_url}): {e}")

    return ""


# ============ 缓存刷新流程 ============

def refresh_cache() -> dict:
    """
    v5 重构刷新流程:
    1. 抓取 upcoming 页面（含 upcoming + running）
    2. 抓取主列表页补 recently_ended（逐页检查，无新增即停）
    3. 合并去重 + 计算 status，过滤 unknown
    4. 继承已有 official_url，为新赛事补抓
    """
    logger.info("开始刷新 CTF 缓存...")
    old_cache = load_cache()
    old_map = {e["id"]: e for e in old_cache.get("events", [])}
    session = requests.Session()
    seen_ids: set = set()
    all_events: List[dict] = []

    # ---- 更新刷新状态 ----
    with _refresh_lock:
        _refresh_state["phase"] = "抓取即将开始赛事..."

    # ---- 1. 抓取 upcoming 页面（含 upcoming + running）----
    logger.info("抓取 upcoming 页面...")
    upcoming_events = scrape_page(CTFTIME_UPCOMING, session)
    upcoming_unknown = 0
    for e in upcoming_events:
        e["status"] = compute_status(e)
        # v5.1: upcoming 页面的 unknown → 宽容为 upcoming（该页面本应是未来赛事）
        if e["status"] == "unknown":
            e["status"] = "upcoming"
            upcoming_unknown += 1
        if e["status"] != "expired":
            seen_ids.add(e["id"])
            all_events.append(e)

    valid_upcoming = sum(1 for e in upcoming_events if e["status"] != "expired")
    logger.info(
        f"upcoming 页面: {len(upcoming_events)} 条，"
        f"有效 {valid_upcoming} 条"
        + (f" (含 {upcoming_unknown} 条日期不可解析→upcoming)" if upcoming_unknown else "")
        + (f" (过滤 {len(upcoming_events) - valid_upcoming} 条 expired)" if valid_upcoming < len(upcoming_events) else "")
    )

    # ---- 2. 抓取主列表补 recently_ended ----
    with _refresh_lock:
        _refresh_state["phase"] = "抓取近期结束赛事..."

    logger.info("抓取主列表页补近期结束赛事...")
    max_pages = 5
    for page in range(1, max_pages + 1):
        url = f"{CTFTIME_LIST}?page={page}" if page > 1 else CTFTIME_LIST
        page_events = scrape_page(url, session)
        if not page_events:
            break

        added = 0
        for e in page_events:
            if e["id"] in seen_ids:
                continue
            e["status"] = compute_status(e)
            if e["status"] in ("expired", "unknown"):
                continue
            seen_ids.add(e["id"])
            all_events.append(e)
            added += 1

        logger.info(f"主列表第 {page} 页: 抓取 {len(page_events)}，新增 {added}")

        # v5 修复: 去重后无新增即停（不限判断为"全部过期"）
        if added == 0:
            logger.info("本页无新增有效赛事，停止翻页")
            break

        time.sleep(REQUEST_DELAY)

    unknown_count = sum(1 for e in all_events if e["status"] == "unknown")
    if unknown_count:
        logger.warning(f"仍有 {unknown_count} 条状态 unknown 的赛事（已过滤不展示）")

    logger.info(f"合并后共 {len(all_events)} 个有效赛事")

    # ---- 3. 继承已有 official_url ----
    for e in all_events:
        if not e["official_url"] and e["id"] in old_map:
            old_o = old_map[e["id"]].get("official_url", "")
            if old_o:
                e["official_url"] = old_o

    # ---- 4. 批量补抓 official_url ----
    with _refresh_lock:
        _refresh_state["phase"] = "补抓赛事官网链接..."

    need_official = [e for e in all_events if not e["official_url"]]
    batch = need_official[:OFFICIAL_URL_BATCH]
    if batch:
        logger.info(f"补抓 Official URL: {len(batch)} / {len(need_official)} 条待补")
        for e in batch:
            if e["ctftime_url"]:
                e["official_url"] = scrape_official_url(e["ctftime_url"])
                time.sleep(REQUEST_DELAY)

    cache = {
        "last_refresh": datetime.now().isoformat(),
        "events": all_events,
    }
    save_cache(cache)

    upcoming = sum(1 for e in all_events if e["status"] == "upcoming")
    running = sum(1 for e in all_events if e["status"] == "running")
    ended = sum(1 for e in all_events if e["status"] == "recently_ended")
    logger.info(f"缓存刷新完成: 即将 {upcoming} / 进行中 {running} / 近期结束 {ended}")
    return cache


# ============ 异步刷新（后台线程）============

def _do_async_refresh():
    """后台执行刷新，完成后更新全局状态"""
    global _refresh_state
    try:
        logger.info("后台异步刷新开始...")
        cache = refresh_cache()
        upcoming = sum(1 for e in cache["events"] if e["status"] == "upcoming")
        running = sum(1 for e in cache["events"] if e["status"] == "running")
        ended = sum(1 for e in cache["events"] if e["status"] == "recently_ended")
        with _refresh_lock:
            _refresh_state["phase"] = ""
            _refresh_state["message"] = (
                f"刷新完成：即将开始 {upcoming} / 进行中 {running} / 近期结束 {ended}"
            )
    except Exception as e:
        logger.error(f"后台异步刷新失败: {e}", exc_info=True)
        with _refresh_lock:
            _refresh_state["phase"] = ""
            _refresh_state["message"] = f"刷新失败: {e}"
    finally:
        with _refresh_lock:
            _refresh_state["running"] = False


# ============ API 端点 ============

@router.get("/events")
async def get_events(
    sort: str = Query("default",
        description="排序: default | weight_desc | weight_asc | format_jeopardy | format_ad | format_hackquest"),
    format_filter: Optional[str] = Query(None, description="赛制过滤，逗号分隔"),
    min_weight: float = Query(0.0, description="最低权重过滤"),
    status_filter: Optional[str] = Query(None, description="状态过滤: upcoming | running | recently_ended"),
):
    """获取 CTF 赛事列表（优先读缓存，必要时自动刷新）"""
    if should_refresh():
        logger.info("缓存已过期（超过今日 12:00），触发自动刷新")
        # 同步刷新（get_events 自动刷新仍为同步，避免前端等待过久的问题交由 /refresh 解决）
        refresh_cache()

    cache_data = load_cache()
    events: List[dict] = cache_data.get("events", [])
    last_refresh = cache_data.get("last_refresh")

    # ---- 兜底：旧缓存可能缺少 status 字段，补算 ----
    recomputed = 0
    for e in events:
        if not e.get("status") or e["status"] not in ("upcoming", "running", "recently_ended", "expired", "unknown"):
            e["status"] = compute_status(e)
            recomputed += 1
    if recomputed:
        logger.info(f"补算 {recomputed} 条缺失/无效 status 的事件")

    # ---- v5 新增：过滤掉 unknown 状态（时间完全不可解析的脏数据）----
    unknown_filtered = sum(1 for e in events if e["status"] == "unknown")
    events = [e for e in events if e["status"] != "unknown"]
    if unknown_filtered:
        logger.info(f"过滤 {unknown_filtered} 条 unknown 状态的事件")

    # ---- 置顶分离 ----
    pins = load_pins()
    pinned_ids = set(pins.get("pinned_ids", []))
    pinned = [e for e in events if e["id"] in pinned_ids]
    unpinned = [e for e in events if e["id"] not in pinned_ids]

    # ---- 过滤 ----
    if status_filter:
        allowed_statuses = set(s.strip() for s in status_filter.split(","))
        unpinned = [e for e in unpinned if e.get("status", "") in allowed_statuses]
        pinned = [e for e in pinned if e.get("status", "") in allowed_statuses]

    if format_filter:
        allowed = set(f.strip() for f in format_filter.split(","))
        unpinned = [e for e in unpinned if e["format"] in allowed]
        pinned = [e for e in pinned if e["format"] in allowed]

    if min_weight > 0:
        unpinned = [e for e in unpinned if e["weight"] >= min_weight]
        pinned = [e for e in pinned if e["weight"] >= min_weight]

    # ---- 排序 ----
    def _sortable_time(event: dict, key: str) -> str:
        """提取可排序的时间字符串，确保 ISO 格式可比，兜底放末尾"""
        val = event.get(key, "")
        if not val:
            return "z"
        # ISO 格式字符串天然可比较（如 "2026-07-03T00:00:00"）
        if isinstance(val, str) and val[:4].isdigit():
            return val
        # 纯文本日期再次尝试解析
        parsed_start, parsed_end = _parse_ctftime_date(str(val))
        result = parsed_start or parsed_end
        return result.isoformat() if result else "z"

    def sort_key(event: dict):
        s = event.get("status", "")
        status_prio = {"upcoming": 0, "running": 1, "recently_ended": 2}

        if sort == "weight_desc":
            return (-event["weight"], _sortable_time(event, "start_time"))
        elif sort == "weight_asc":
            return (event["weight"], _sortable_time(event, "start_time"))
        elif sort == "format_jeopardy":
            fmt_order = 0 if event["format"] == "Jeopardy" else 1
            return (fmt_order, -event["weight"], _sortable_time(event, "start_time"))
        elif sort == "format_ad":
            fmt_order = 0 if event["format"] == "Attack-Defense" else 1
            return (fmt_order, -event["weight"], _sortable_time(event, "start_time"))
        elif sort == "format_hackquest":
            fmt_order = 0 if event["format"] == "Hack quest" else 1
            return (fmt_order, -event["weight"], _sortable_time(event, "start_time"))
        else:
            # default: upcoming 从近到远 → running → recently_ended 最近结束在前
            if s == "recently_ended":
                end_dt = _try_parse_event_time(event, "end_time")
                if end_dt is None:
                    end_dt = _try_parse_date_text(event.get("date", ""), as_end=True)
                # 负时间戳：越近的结束时间 → 越大的负数 → 排序靠前
                inverted = -(end_dt.timestamp()) if end_dt else 0
                return (status_prio[s], inverted, -event["weight"])
            # upcoming / running: 开始时间升序（近的在前）
            return (status_prio.get(s, 9), _sortable_time(event, "start_time"), -event["weight"])

    pinned.sort(key=sort_key)
    unpinned.sort(key=sort_key)
    sorted_events = pinned + unpinned

    return {
        "success": True,
        "data": sorted_events,
        "total": len(sorted_events),
        "pinned_count": len(pinned),
        "last_refresh": last_refresh,
    }


@router.post("/refresh")
async def force_refresh():
    """
    v5 异步刷新：立即返回 "刷新已启动"，后台线程执行实际抓取。
    前端通过 GET /refresh/status 轮询进度。
    """
    with _refresh_lock:
        if _refresh_state["running"]:
            return {
                "success": True,
                "refreshing": True,
                "message": "刷新正在进行中，请稍候...",
            }
        _refresh_state["running"] = True
        _refresh_state["phase"] = "正在启动刷新..."
        _refresh_state["message"] = ""

    thread = threading.Thread(target=_do_async_refresh, daemon=True)
    thread.start()

    return {
        "success": True,
        "refreshing": True,
        "message": "刷新已启动",
    }


@router.get("/refresh/status")
async def get_refresh_status():
    """v5 新增：查询异步刷新进度"""
    with _refresh_lock:
        return {
            "success": True,
            "refreshing": _refresh_state["running"],
            "phase": _refresh_state["phase"],
            "message": _refresh_state["message"],
        }


@router.post("/pin/{event_id}")
async def toggle_pin(event_id: str):
    """切换大头钉状态"""
    pins = load_pins()
    pinned = pins.get("pinned_ids", [])
    if event_id in pinned:
        pinned.remove(event_id)
        action = "unpinned"
    else:
        pinned.append(event_id)
        action = "pinned"
    pins["pinned_ids"] = pinned
    save_pins(pins)
    return {"success": True, "action": action, "pinned_ids": pinned}


@router.get("/pins")
async def get_pins():
    """获取当前所有大头钉 ID"""
    return {"success": True, "pinned_ids": load_pins().get("pinned_ids", [])}
