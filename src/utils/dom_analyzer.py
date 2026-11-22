"""从真实 HTML 中提取「列表状结构」候选，供 LLM 语义选择。

设计原则：CSS 选择器必须由真实 DOM 生成，不能让 LLM 凭空写。
本模块扫描页面里所有「包含多个相似子元素、且子元素含标题/链接」的容器，
为每个容器生成：
  - 稳定的容器 CSS 选择器（系统生成，保证能命中当前 DOM）
  - 每个字段（title/link/date）的候选相对选择器及样本文本
LLM 只需看候选样本做语义判断（哪个是通知列表），不写选择器。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

# 明显是布局/装饰用途的 class，不作为稳定选择器依据
NOISE_CLASS = re.compile(
    r"(^|_)(clearfix|fr|fl|pull|text|bg|col|row|hidden|active|hover|on|selected|"
    r"mt|mb|ml|mr|pt|pb|pl|pr|p\d|m\d|w\d|h\d|flex|grid|inline|block|pointer)($|_)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}|\d{1,2}[-/月]\d{1,2}|\d{4}-\d{2}-\d{2})")
MAX_CANDIDATES = 12
SAMPLE_COUNT = 3


def _visible_text(node: Tag) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else ""


def _stable_selector(node: Tag, soup: BeautifulSoup) -> Optional[str]:
    """为节点生成能唯一命中当前 DOM 的 CSS 选择器。"""
    if not isinstance(node, Tag):
        return None
    # 1) id 最稳
    node_id = node.get("id")
    if node_id and re.match(r"^[A-Za-z][\w-]*$", node_id):
        sel = f"#{node_id}"
        try:
            found = soup.select(sel)
            if len(found) == 1 and found[0] is node:
                return sel
        except Exception:
            pass
    # 2) tag + 有效 class（逐步加深父级直到唯一）
    classes = [c for c in (node.get("class") or []) if c and not NOISE_CLASS.search(c)]
    parts: List[str] = []
    cur: Optional[Tag] = node
    for depth in range(5):
        if not isinstance(cur, Tag) or cur.name in ("body", "html", "[document]"):
            break
        seg = cur.name
        c = [x for x in (cur.get("class") or []) if x and not NOISE_CLASS.search(x)]
        if c:
            seg += "." + ".".join(c[:2])
        parts.insert(0, seg)
        sel = " > ".join(parts)
        try:
            found = soup.select(sel)
            if found and any(f is node for f in found) and len(found) <= 3:
                return sel
        except Exception:
            pass
        cur = cur.parent
    # 3) 兜底：用 nth-of-type 路径
    parts = []
    cur = node
    while isinstance(cur, Tag) and cur.name not in ("body", "html", "[document]") and len(parts) < 6:
        siblings = [s for s in cur.parent.children if isinstance(s, Tag) and s.name == cur.name] if cur.parent else []
        idx = siblings.index(cur) + 1 if cur in siblings else 1
        parts.insert(0, f"{cur.name}:nth-of-type({idx})")
        cur = cur.parent
    return " > ".join(parts) if parts else None


def _relative_selector(item: Tag, target: Tag) -> Optional[str]:
    """生成 target 相对 item 的选择器（供 fields 使用）。"""
    if target is item or not isinstance(target, Tag):
        return None
    classes = [c for c in (target.get("class") or []) if c and not NOISE_CLASS.search(c)]
    simple = target.name + ("." + ".".join(classes[:2]) if classes else "")
    # 先看简单选择器在 item 内是否唯一命中 target
    try:
        found = item.select(simple)
        if found and any(f is target for f in found):
            if len(found) == 1:
                return simple
    except Exception:
        pass
    # 不唯一则加 nth-of-type
    siblings = [s for s in target.parent.children if isinstance(s, Tag) and s.name == target.name] if target.parent else []
    if target in siblings and len(siblings) > 1:
        idx = siblings.index(target) + 1
        nth = f"{target.name}:nth-of-type({idx})"
        try:
            found = item.select(nth)
            if found and any(f is target for f in found):
                return nth
        except Exception:
            pass
    return simple


def _analyze_item(item: Tag) -> Dict[str, Any]:
    """分析单个列表项，推断 title/link/date 的候选。"""
    title_node, link_node, date_node = None, None, None
    best_len = 0
    # 链接优先：有 href 且文本够长的 a
    for a in item.find_all("a", href=True):
        txt = _visible_text(a)
        if len(txt) > best_len:
            best_len, title_node, link_node = len(txt), a, a
    # 没链接时取文本最长的子元素
    if title_node is None:
        for child in item.find_all(["span", "div", "p", "li", "h3", "h4", "td"], recursive=True):
            txt = _visible_text(child)
            if 4 <= len(txt) > best_len:
                best_len, title_node = len(txt), child
    # 日期：匹配日期正则的最小文本节点
    for node in item.find_all(string=DATE_RE):
        parent = node.parent
        if isinstance(parent, Tag):
            date_node = parent
            break

    return {
        "title_selector": _relative_selector(item, title_node) if title_node else "",
        "link_selector": _relative_selector(item, link_node) if link_node else "",
        "date_selector": _relative_selector(item, date_node) if date_node else "",
        "sample_title": _visible_text(title_node)[:60] if title_node else _visible_text(item)[:60],
        "sample_link": (link_node.get("href", "") if link_node else "")[:120],
        "sample_date": _visible_text(date_node)[:30] if date_node else "",
    }


def extract_candidates(html: str, base_url: str = "") -> List[Dict[str, Any]]:
    """从 HTML 提取列表候选，按质量评分降序返回（最多 MAX_CANDIDATES 个）。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    candidates: List[Dict[str, Any]] = []
    seen_selectors = set()
    for container in soup.find_all(["ul", "ol", "div", "section", "table", "dl"]):
        children = [
            c for c in container.find_all(recursive=False)
            if isinstance(c, Tag) and c.name not in ("script", "style", "nav", "header", "footer")
        ]
        if not (3 <= len(children) <= 200):
            continue
        # 子元素需相似（同 tag 或共享 class 模式）
        tags = [c.name for c in children]
        dominant = max(set(tags), key=tags.count)
        if tags.count(dominant) < len(children) * 0.6:
            continue
        # 至少一半子元素含链接，且文本够长（排除纯导航/图标列表）
        with_link = sum(1 for c in children if c.find("a", href=True))
        if with_link < len(children) * 0.5:
            continue
        sel = _stable_selector(container, soup)
        if not sel or sel in seen_selectors:
            continue
        seen_selectors.add(sel)

        # 生成「列表项选择器」：解析器要对每一项逐条处理，不能用容器选择器
        dominant_classes = [
            c for c in (children[0].get("class") or [])
            if c and not NOISE_CLASS.search(c)
        ]
        item_seg = dominant + ("." + ".".join(dominant_classes[:2]) if dominant_classes else "")
        item_selector = f"{sel} > {item_seg}" if sel else item_seg
        try:
            matched = soup.select(item_selector)
            if len(matched) < 2:
                # 退化：用 nth-child 不适用时，退回通用子元素 tag
                item_selector = f"{sel} > {dominant}" if sel else dominant
        except Exception:
            item_selector = f"{sel} > {dominant}" if sel else dominant

        analyses = [_analyze_item(c) for c in children[:SAMPLE_COUNT]]
        titled = [a for a in analyses if a["sample_title"]]
        if len(titled) < 2:
            continue
        # 字段选择器取样本中出现频率最高的非空值
        def _major(key: str) -> str:
            vals = [a[key] for a in analyses if a.get(key)]
            return max(set(vals), key=vals.count) if vals else ""

        score = len(children) * 0.3 + with_link * 0.5 + sum(len(a["sample_title"]) for a in titled) / max(len(titled), 1) * 0.1
        candidates.append({
            "index": len(candidates),
            "selector": item_selector,
            "container_selector": sel,
            "item_count": len(children),
            "fields": {
                "title": _major("title_selector"),
                "link": _major("link_selector"),
                "date": _major("date_selector"),
            },
            "samples": [
                {"title": a["sample_title"], "link": a["sample_link"], "date": a["sample_date"]}
                for a in analyses
            ],
            "score": round(score, 2),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(candidates[:MAX_CANDIDATES]):
        c["index"] = i
    return candidates[:MAX_CANDIDATES]


def build_config_from_candidate(candidate: Dict[str, Any], url: str) -> Dict[str, Any]:
    """从选中的候选生成抓取配置（选择器全部来自真实 DOM）。"""
    fields = candidate["fields"] or {}
    return {
        "url": url,
        "list_selector": candidate["selector"],
        "fields": {
            "title": fields.get("title", ""),
            "link": fields.get("link", ""),
            "date": fields.get("date", ""),
        },
        "pagination": {"type": "none"},
    }
