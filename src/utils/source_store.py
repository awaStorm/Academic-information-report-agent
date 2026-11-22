"""信源卡片与检查清单的共享存储层。

Agent 工具（线程池）与 Web API（异步上下文）并发读写同一份数据，
因此选 SQLite（data/memory.db 内新增两张表）而非 JSON，保证原子写入与稳定排序。
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import yaml

from src.utils.card_schema import (
    CARD_TYPE_CHAOXING,
    CARD_TYPE_WECHAT,
    CARD_TYPE_WECHAT_GROUP,
    CARD_TYPE_WECHAT_SYSTEM,
    SYSTEM_CARD_TYPES,
    SourceCard,
    is_system_card,
    is_valid_card_type,
    new_card,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "memory.db")
SETTINGS_PATH = os.path.join(BASE_DIR, "configs", "settings.yaml")


@contextmanager
def _connect():
    """每次操作开短连接：工具在线程池、API 在事件循环，避免跨线程复用连接。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_tables(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_cards (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            config TEXT NOT NULL DEFAULT '{}',
            verified INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checklist (
            card_id TEXT PRIMARY KEY,
            sort_order INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(card_id) REFERENCES source_cards(id) ON DELETE CASCADE
        )
    """)


def _row_to_card(row: sqlite3.Row) -> SourceCard:
    return SourceCard(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        enabled=bool(row["enabled"]),
        config=json.loads(row["config"] or "{}"),
        verified=bool(row["verified"]),
        note=row["note"] or "",
        created_at=row["created_at"] or "",
    )


# ---- 卡片 CRUD ----

def add_card(card_type: str, name: str, config: Optional[Dict[str, Any]] = None,
             verified: bool = False, note: str = "", card_id: Optional[str] = None) -> SourceCard:
    if not is_valid_card_type(card_type):
        raise ValueError(f"未知卡片类型: {card_type}")
    if not name or not str(name).strip():
        raise ValueError("卡片名称不能为空")
    cid = card_id or str(uuid.uuid4())
    card = new_card(cid, card_type, str(name).strip(), config or {}, verified, note)
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO source_cards
            (id, type, name, enabled, config, verified, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (card["id"], card["type"], card["name"], int(card["enabled"]),
              json.dumps(card["config"], ensure_ascii=False), int(card["verified"]),
              card["note"], card["created_at"]))
    return card


def get_card(card_id: str) -> Optional[SourceCard]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM source_cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def list_cards(card_type: Optional[str] = None) -> List[SourceCard]:
    with _connect() as conn:
        if card_type:
            rows = conn.execute(
                "SELECT * FROM source_cards WHERE type = ? ORDER BY created_at, id", (card_type,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM source_cards ORDER BY created_at, id").fetchall()
    return [_row_to_card(r) for r in rows]


def update_card(card_id: str, **fields) -> Optional[SourceCard]:
    allowed = {"name", "enabled", "config", "verified", "note"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_card(card_id)
    if "config" in updates:
        updates["config"] = json.dumps(updates["config"], ensure_ascii=False)
    if "enabled" in updates:
        updates["enabled"] = int(bool(updates["enabled"]))
    if "verified" in updates:
        updates["verified"] = int(bool(updates["verified"]))
    sets = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        cur = conn.execute(f"UPDATE source_cards SET {sets} WHERE id = ?",
                           (*updates.values(), card_id))
        if cur.rowcount == 0:
            return None
    return get_card(card_id)


def remove_card(card_id: str) -> bool:
    card = get_card(card_id)
    if card and is_system_card(card):
        return False  # 系统内置卡片（超星/微信内核）不可删除
    with _connect() as conn:
        conn.execute("DELETE FROM checklist WHERE card_id = ?", (card_id,))
        # 同步清理所有微信容器 children 里的引用，避免留下指向已删除卡片的脏 id
        groups = conn.execute(
            "SELECT id, config FROM source_cards WHERE type = ?", (CARD_TYPE_WECHAT_GROUP,)
        ).fetchall()
        for row in groups:
            cfg = json.loads(row["config"] or "{}")
            children = cfg.get("children", [])
            if card_id in children:
                cfg["children"] = [cid for cid in children if cid != card_id]
                conn.execute("UPDATE source_cards SET config = ? WHERE id = ?",
                             (json.dumps(cfg, ensure_ascii=False), row["id"]))
        cur = conn.execute("DELETE FROM source_cards WHERE id = ?", (card_id,))
        return cur.rowcount > 0


# ---- 检查清单（顺序 = 扫描顺序，自上而下） ----

def add_to_checklist(card_id: str, enabled: bool = True) -> bool:
    with _connect() as conn:
        if conn.execute("SELECT 1 FROM source_cards WHERE id = ?", (card_id,)).fetchone() is None:
            return False
        row = conn.execute("SELECT MAX(sort_order) AS m FROM checklist").fetchone()
        next_order = (row["m"] or 0) + 1
        conn.execute("""
            INSERT OR REPLACE INTO checklist (card_id, sort_order, enabled) VALUES (?, ?, ?)
        """, (card_id, next_order, int(bool(enabled))))
    return True


def remove_from_checklist(card_id: str) -> bool:
    card = get_card(card_id)
    if card and is_system_card(card):
        return False  # 系统卡必须留在清单里
    with _connect() as conn:
        cur = conn.execute("DELETE FROM checklist WHERE card_id = ?", (card_id,))
        if cur.rowcount == 0:
            return False
        rows = conn.execute("SELECT card_id FROM checklist ORDER BY sort_order").fetchall()
        for idx, row in enumerate(rows, start=1):
            conn.execute("UPDATE checklist SET sort_order = ? WHERE card_id = ?", (idx, row["card_id"]))
    return True


def list_checklist() -> List[Dict[str, Any]]:
    """按扫描顺序返回 [{card, sort_order, enabled}, ...]"""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT c.*, cl.sort_order AS sort_order, cl.enabled AS list_enabled
            FROM checklist cl JOIN source_cards c ON c.id = cl.card_id
            ORDER BY cl.sort_order
        """).fetchall()
    result = []
    for row in rows:
        card = _row_to_card(row)
        result.append({"card": card, "sort_order": row["sort_order"],
                       "enabled": bool(row["list_enabled"])})
    return result


def reorder_checklist(card_ids: List[str]) -> bool:
    """整体重排：入参顺序即新的扫描顺序。未列出的卡片保持不变并置于末尾。"""
    with _connect() as conn:
        existing = [r["card_id"] for r in conn.execute(
            "SELECT card_id FROM checklist ORDER BY sort_order").fetchall()]
        ordered = [cid for cid in card_ids if cid in existing]
        ordered += [cid for cid in existing if cid not in ordered]
        for idx, cid in enumerate(ordered, start=1):
            conn.execute("UPDATE checklist SET sort_order = ? WHERE card_id = ?", (idx, cid))
    return True


def set_checklist_enabled(card_id: str, enabled: bool) -> bool:
    with _connect() as conn:
        cur = conn.execute("UPDATE checklist SET enabled = ? WHERE card_id = ?",
                           (int(bool(enabled)), card_id))
        return cur.rowcount > 0


# ---- 公众号检查注册：写回 collectors.wechat.targets ----

def sync_wechat_targets() -> List[str]:
    """把清单里启用的公众号（含微信容器内 children）写回 wechat.targets。

    复用现有微信采集内核，不重写链路。返回写回后的公众号列表。
    """
    targets: List[str] = []
    cards = {c["id"]: c for c in list_cards()}

    def _add(card: SourceCard) -> None:
        account = str((card["config"] or {}).get("account") or card["name"]).strip()
        if account and account not in targets:
            targets.append(account)

    # ① 检查清单里的独立公众号卡片（受清单启用状态约束）
    for item in list_checklist():
        if not item["enabled"] or not item["card"]["enabled"]:
            continue
        card = item["card"]
        if card["type"] == CARD_TYPE_WECHAT:
            _add(card)

    # ② 所有微信容器内的公众号：拖入容器合并本身就是「注册到公众号检查」的意图，
    #    不强求容器也必须加入扫描清单（清单顺序主要作用于网站/独立信源的抓取）。
    #    容器卡片自身停用时跳过，避免用户显式停用容器后仍被注册。
    for group in cards.values():
        if group["type"] != CARD_TYPE_WECHAT_GROUP or not group["enabled"]:
            continue
        for child_id in (group["config"] or {}).get("children", []):
            child = cards.get(child_id)
            if child and child["type"] == CARD_TYPE_WECHAT and child["enabled"]:
                _add(child)

    _persist_targets(targets)
    return targets


def ensure_system_cards() -> int:
    """确保超星/微信两张系统内置卡片存在并在检查清单最前。

    它们是项目原有采集内核的“可视化占位”，不代表新的抓取实现：
      - 超星对应 Scraper().fetch_and_save
      - 微信对应 WechatScraper().run_scraper_flow（目标来自 wechat.targets，由公众号卡片写回）
    返回本次新建的卡片数（0 表示已存在）。应用启动时调用一次即可。
    """
    created = 0
    specs = [
        (CARD_TYPE_CHAOXING, "超星通知（系统内置）",
         {"kernel": "chaoxing_scraper"}, "由超星采集内核抓取，不经过通用抓取器；不可删除"),
        (CARD_TYPE_WECHAT_SYSTEM, "微信公众号（系统内置）",
         {"kernel": "wechat_scraper"}, "监控目标由信源卡片中的公众号写回；不可删除"),
    ]
    for card_type, name, config, note in specs:
        existing = [c for c in list_cards(card_type) if c["id"].startswith("system-")]
        if existing:
            continue
        cid = f"system-{card_type}"
        add_card(card_type, name, config, verified=True, note=note, card_id=cid)
        created += 1
    # 系统卡片排到清单最前（已存在但被移出清单时也补回）
    for card_type in (CARD_TYPE_CHAOXING, CARD_TYPE_WECHAT_SYSTEM):
        cid = f"system-{card_type}"
        with _connect() as conn:
            row = conn.execute("SELECT 1 FROM checklist WHERE card_id = ?", (cid,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO checklist (card_id, sort_order, enabled) VALUES (?, ?, 1)",
                             (cid, 0))
    # 统一重排：超星 → 微信 → 其余（保证遍历顺序稳定、system 卡始终在前）
    with _connect() as conn:
        rows = conn.execute("""
            SELECT cl.card_id, c.type FROM checklist cl
            JOIN source_cards c ON c.id = cl.card_id
            ORDER BY cl.sort_order
        """).fetchall()
        priority = {f"system-{CARD_TYPE_CHAOXING}": 0, f"system-{CARD_TYPE_WECHAT_SYSTEM}": 1}
        ordered = sorted(
            [r["card_id"] for r in rows],
            key=lambda cid: priority.get(cid, 2),
        )
        for idx, cid in enumerate(ordered):
            conn.execute("UPDATE checklist SET sort_order = ? WHERE card_id = ?", (idx, cid))
    return created


def migrate_targets_to_cards() -> int:
    """把 collectors.wechat.targets 里尚无对应卡片的公众号补建为卡片（幂等）。

    背景：配置面板过去可直接编辑 targets，信源雷达上线后公众号卡片成为唯一主力入口。
    为避免历史 targets 在配置面板"看得到、雷达里没有"，这里把孤儿名字补成公众号卡片，
    放进仓库（不自动加入清单/容器，由用户决定编排）。已有匹配 account 的卡片则跳过。
    返回本次新建卡片数。
    """
    from src.utils.config_loader import CONFIG

    targets = list((CONFIG.get("collectors", {}).get("wechat", {}) or {}).get("targets") or [])
    if not targets:
        return 0
    all_cards = list_cards()
    known = {
        str((c["config"] or {}).get("account") or c["name"]).strip()
        for c in all_cards if c["type"] == CARD_TYPE_WECHAT
    }
    created = 0
    for name in targets:
        clean = str(name).strip()
        if not clean or clean in known:
            continue
        add_card(CARD_TYPE_WECHAT, clean, {"account": clean},
                 note="由配置面板历史公众号迁移而来，请在信源雷达编排")
        known.add(clean)
        created += 1
    return created


def _persist_targets(targets: List[str]) -> None:
    """同步内存 CONFIG 与 settings.yaml，使微信采集立即读到新 targets。"""
    from src.utils.config_loader import CONFIG

    collectors = CONFIG.setdefault("collectors", {})
    wechat = collectors.setdefault("wechat", {})
    wechat["targets"] = list(targets)

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    current = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}
    current.setdefault("collectors", {}).setdefault("wechat", {})["targets"] = list(targets)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.dump(current, f, allow_unicode=True, default_flow_style=False)
