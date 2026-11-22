"""通用配置化抓取器。

按检查清单顺序读取 website 卡片，用 AI 生成的 CSS 选择器抓取列表与字段，
输出与 ContentExtractor 精炼后一致的情报结构，供 FinalMerger 合入统一时间轴。
不做 LLM 实时抽取、不做混合兜底：配置抓不到就如实返回失败，由用户决策。
"""
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.utils.card_schema import CARD_TYPE_WEBSITE
from src.utils.config_loader import CONFIG
from src.utils.source_store import list_checklist

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "processed", "data_generic_ready.json")

DEFAULT_TIMEOUT = 25
DEFAULT_RETRIES = 2
MAX_PAGES = 5
MAX_ITEMS_PER_CARD = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _http_get(url: str, timeout: int, retries: int, headers: Optional[dict] = None) -> Tuple[bool, Any]:
    """宽容超时 + 指数退避重试，返回 (是否成功, response 或错误信息)。"""
    merged_headers = dict(_HEADERS)
    if headers:
        merged_headers.update(headers)
    last_err = ""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=merged_headers, timeout=timeout)
            resp.raise_for_status()
            # 很多中文站点未在响应头声明 charset，requests 会默认按 ISO-8859-1
            # 解码，导致中文乱码（"2026å¹´..."）。若响应头没明确编码，用内容探测修正。
            if "charset=" not in (resp.headers.get("Content-Type") or "").lower():
                apparent = resp.apparent_encoding
                if apparent and apparent.lower() not in ("iso-8859-1", "ascii"):
                    resp.encoding = apparent
            return True, resp
        except requests.RequestException as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(2 ** attempt)
    return False, last_err


def _abs_url(href: str, base: str) -> str:
    """把相对链接补全为绝对 URL；空或非 http 链接返回空串。"""
    if not href:
        return ""
    full = urljoin(base, href.strip())
    return full if full.lower().startswith(("http://", "https://")) else ""


def _text_of(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _pick(node, selector: str):
    """在选择器命中失败时返回 None，由调用方决定跳过而非崩整站。"""
    if not selector:
        return None
    try:
        return node.select_one(selector)
    except Exception:
        return None


def parse_card_items(card: Dict[str, Any], soup: BeautifulSoup, page_url: str) -> List[dict]:
    """从单页 HTML 中按卡片选择器抽取条目。"""
    cfg = card.get("config") or {}
    list_selector = cfg.get("list_selector") or ""
    fields = cfg.get("fields") or {}
    if not list_selector:
        return []

    try:
        nodes = soup.select(list_selector)
    except Exception:
        return []

    items = []
    for node in nodes:
        title_node = _pick(node, fields.get("title", ""))
        title = _text_of(title_node)
        if not title:
            continue
        link_node = _pick(node, fields.get("link", ""))
        href = ""
        if link_node is not None:
            href = link_node.get("href", "")
        elif node.name == "a":
            href = node.get("href", "")
        link = _abs_url(href, page_url)
        date = _text_of(_pick(node, fields.get("date", "")))
        body = _text_of(node)
        content_id = hashlib.md5((card["id"] + title + link).encode("utf-8")).hexdigest()
        items.append({
            "id": content_id,
            "platform": f"generic:{card['id']}",
            "author": card.get("name", "通用信源"),
            "title": title,
            "date": date,
            "body": body,
            "link": link,
            "links": [link] if link else [],
        })
    return items


def _page_urls(card: Dict[str, Any]) -> List[str]:
    """按 pagination 配置生成待抓页面 URL 列表。"""
    cfg = card.get("config") or {}
    url = (cfg.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return []
    pagination = cfg.get("pagination") or {}
    ptype = pagination.get("type", "none")
    if ptype == "url_template":
        template = pagination.get("template") or ""
        if not template or "{page}" not in template:
            return [url]
        return [template.replace("{page}", str(p)) for p in range(1, MAX_PAGES + 1)]
    return [url]


def validate_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """AI 生成阶段的可达性 + 选择器命中验证（一次性网络成本）。"""
    if card.get("type") != CARD_TYPE_WEBSITE:
        return {"valid": False, "reason": "仅 website 卡片需要站点验证"}
    cfg = card.get("config") or {}
    pages = _page_urls(card)
    if not pages:
        return {"valid": False, "reason": "URL 缺失或不是 http/https"}
    timeout = int(cfg.get("timeout") or DEFAULT_TIMEOUT)
    retries = int(cfg.get("retries") or DEFAULT_RETRIES)
    ok, resp = _http_get(pages[0], timeout, retries, cfg.get("request_headers"))
    if not ok:
        return {"valid": False, "reason": f"站点不可达: {str(resp)[:120]}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    items = parse_card_items(card, soup, pages[0])
    if not items:
        return {"valid": False, "reason": "站点可访问，但列表选择器未命中任何条目"}
    return {"valid": True, "sample_count": len(items), "sample_title": items[0]["title"][:80]}


def fetch_card(card: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
    """抓取单张 website 卡片，返回 (成功, 条目数, 条目列表)。"""
    cfg = card.get("config") or {}
    timeout = int(cfg.get("timeout") or DEFAULT_TIMEOUT)
    retries = int(cfg.get("retries") or DEFAULT_RETRIES)
    headers = cfg.get("request_headers") or {}
    all_items: List[dict] = []
    seen = set()

    for page_url in _page_urls(card):
        ok, resp = _http_get(page_url, timeout, retries, headers)
        if not ok:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in parse_card_items(card, soup, page_url):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            all_items.append(item)
        if progress_callback:
            try:
                progress_callback(len(all_items), MAX_ITEMS_PER_CARD, f"已抓取 {card['name']}")
            except Exception:
                pass
        if len(all_items) >= MAX_ITEMS_PER_CARD:
            break

    all_items = all_items[:MAX_ITEMS_PER_CARD]
    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"success": bool(all_items), "count": len(all_items), "items": all_items}


def run_generic_scraper(progress_callback=None) -> Dict[str, Any]:
    """按检查清单顺序抓取所有启用的 website 卡片，写入统一输出文件。"""
    checklist = list_checklist()
    website_cards = [
        item["card"] for item in checklist
        if item["enabled"] and item["card"].get("enabled")
        and item["card"].get("type") == CARD_TYPE_WEBSITE
    ]
    if not website_cards:
        # 清单为空或无网站卡片：静默跳过，不阻塞原有超星/微信流程
        if os.path.exists(OUTPUT_FILE):
            os.remove(OUTPUT_FILE)
        return {"success": True, "count": 0, "skipped": True, "message": "检查清单无网站信源，跳过"}

    all_items: List[dict] = []
    results = []
    total = len(website_cards)
    for idx, card in enumerate(website_cards, start=1):
        result = fetch_card(card)
        results.append({"card_id": card["id"], "name": card["name"],
                        "success": result["success"], "count": result["count"]})
        all_items.extend(result["items"])
        if progress_callback:
            try:
                progress_callback(idx, total, f"已扫描信源 {idx}/{total}: {card['name']}")
            except Exception:
                pass

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=4)

    return {
        "success": bool(all_items),
        "count": len(all_items),
        "cards": results,
        "failed_cards": [r["name"] for r in results if not r["success"]],
        "message": f"通用信源抓取完成，共 {len(all_items)} 条，来自 {total} 张卡片",
    }


if __name__ == "__main__":
    print(json.dumps(run_generic_scraper(), ensure_ascii=False, indent=2))
