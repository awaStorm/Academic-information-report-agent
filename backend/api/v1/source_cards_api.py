"""
backend/api/v1/source_cards_api.py - 信源卡片工作台 API
与 Agent 工具共享 card_discovery / source_store 服务函数，保证双入口数据一致。
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import source_store
from src.utils.card_discovery import (
    discover_source_cards, list_source_cards, add_card_to_checklist, remove_card,
)
from src.utils.card_schema import (
    CARD_TYPE_WECHAT, CARD_TYPE_WECHAT_GROUP, is_valid_card_type,
)

router = APIRouter()


class DiscoverRequest(BaseModel):
    requirement: str = Field(..., description="学生需求描述")
    followup: str = Field(default="", description="再来一轮时用户补充的需求")
    feedback: str = Field(default="", description="再来一轮时上一轮 LLM 评审意见")


class AddCardRequest(BaseModel):
    type: str
    name: str
    config: dict = Field(default_factory=dict)
    verified: bool = False
    note: str = ""


class CardIdRequest(BaseModel):
    card_id: str


class CreateGroupRequest(BaseModel):
    name: str = "微信信源组"
    note: str = ""


class MoveChildRequest(BaseModel):
    group_id: str
    child_id: str


class ReorderRequest(BaseModel):
    card_ids: List[str]


class EnableRequest(BaseModel):
    enabled: bool


@router.get("/")
async def get_cards():
    return list_source_cards()


@router.post("/discover")
async def discover(req: DiscoverRequest):
    return discover_source_cards(req.requirement, followup=req.followup, feedback=req.feedback)


@router.post("/add")
async def add_card(req: AddCardRequest):
    if not is_valid_card_type(req.type):
        raise HTTPException(status_code=400, detail=f"未知卡片类型: {req.type}")
    try:
        card = source_store.add_card(req.type, req.name, req.config, req.verified, req.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "card": card}


@router.post("/checklist/add")
async def checklist_add(req: CardIdRequest):
    return add_card_to_checklist(req.card_id)


@router.post("/checklist/remove")
async def checklist_remove(req: CardIdRequest):
    ok = source_store.remove_from_checklist(req.card_id)
    if not ok:
        return {"success": False, "error": "该卡片不在检查清单中"}
    return {"success": True, "message": "已从检查清单移除"}


@router.post("/checklist/reorder")
async def checklist_reorder(req: ReorderRequest):
    source_store.reorder_checklist(req.card_ids)
    return {"success": True, "message": "扫描顺序已更新"}


@router.post("/checklist/{card_id}/enable")
async def checklist_enable(card_id: str, req: EnableRequest):
    ok = source_store.set_checklist_enabled(card_id, req.enabled)
    if not ok:
        return {"success": False, "error": "该卡片不在检查清单中"}
    return {"success": True, "message": "启用状态已更新"}


@router.delete("/{card_id}")
async def delete_card(card_id: str):
    from src.utils.card_schema import is_system_card
    card = source_store.get_card(card_id)
    if card and is_system_card(card):
        return {"success": False, "error": "超星/微信为系统内置信源，不可删除（可在清单中停用）"}
    return remove_card(card_id)


@router.post("/wechat-group/create")
async def create_wechat_group(req: CreateGroupRequest):
    """创建微信容器卡片（用于把多个公众号小卡片拖入合并）。"""
    card = source_store.add_card(CARD_TYPE_WECHAT_GROUP, req.name or "微信信源组",
                                 {"children": []}, note=req.note)
    return {"success": True, "card": card}


@router.post("/wechat-group/move-child")
async def move_child(req: MoveChildRequest):
    """把一个公众号小卡片合并进微信容器（从其它容器移出）。"""
    group = source_store.get_card(req.group_id)
    child = source_store.get_card(req.child_id)
    if not group or group["type"] != CARD_TYPE_WECHAT_GROUP:
        return {"success": False, "error": "目标容器不存在"}
    if not child or child["type"] != CARD_TYPE_WECHAT:
        return {"success": False, "error": "只能合并公众号小卡片"}

    # 从所有容器里移除该 child，再加入目标容器（保证只属于一个容器）
    for card in source_store.list_cards(CARD_TYPE_WECHAT_GROUP):
        children = [cid for cid in (card["config"] or {}).get("children", []) if cid != req.child_id]
        if card["id"] == req.group_id:
            if req.child_id not in children:
                children.append(req.child_id)
        source_store.update_card(card["id"], config={**(card["config"] or {}), "children": children})

    source_store.sync_wechat_targets()
    return {"success": True, "message": f"「{child['name']}」已合并进「{group['name']}」"}


@router.post("/wechat-group/remove-child")
async def remove_child(req: MoveChildRequest):
    """把公众号小卡片从微信容器移出。"""
    group = source_store.get_card(req.group_id)
    if not group or group["type"] != CARD_TYPE_WECHAT_GROUP:
        return {"success": False, "error": "容器不存在"}
    cfg = group["config"] or {}
    children = [cid for cid in cfg.get("children", []) if cid != req.child_id]
    source_store.update_card(req.group_id, config={**cfg, "children": children})
    source_store.sync_wechat_targets()
    return {"success": True, "message": "已从容器移出"}


@router.post("/register-wechat")
async def register_wechat():
    """把检查清单里的公众号/容器统一注册进微信检查目标。"""
    targets = source_store.sync_wechat_targets()
    return {"success": True, "targets": targets, "message": f"公众号检查目标已更新，共 {len(targets)} 个"}


class TestConfigRequest(BaseModel):
    url: str
    list_selector: str
    fields: dict = Field(default_factory=dict)


def _run_preview(config: dict) -> dict:
    """真实抓一次配置，返回是否命中及样例（供自动验证与手动测试共用）。"""
    from src.collectors.scrapers.generic_scraper import _http_get, parse_card_items
    from bs4 import BeautifulSoup

    url = (config.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return {"success": False, "error": "URL 不是有效的 http/https 地址"}
    ok, resp = _http_get(url, timeout=25, retries=1)
    if not ok:
        return {"success": False, "error": f"站点不可达: {str(resp)[:100]}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    card = {"id": "preview", "type": "website", "name": "预览", "config": config}
    items = parse_card_items(card, soup, url)
    if not items:
        return {"success": False, "error": "选择器未命中任何条目：请检查列表选择器与标题选择器"}
    return {
        "success": True,
        "count": len(items),
        "samples": [
            {"title": i["title"][:80], "link": i["link"], "date": i.get("date", "")}
            for i in items[:5]
        ],
        "message": f"命中 {len(items)} 条，配置有效",
    }


@router.post("/test-config")
async def test_config(req: TestConfigRequest):
    """测试任意抓取配置（不落库），用于编辑卡片时实时预览。"""
    config = {
        "url": req.url,
        "list_selector": req.list_selector,
        "fields": {
            "title": str((req.fields or {}).get("title") or ""),
            "link": str((req.fields or {}).get("link") or ""),
            "date": str((req.fields or {}).get("date") or ""),
        },
        "pagination": {"type": "none"},
    }
    return _run_preview(config)


class UpdateConfigRequest(BaseModel):
    name: Optional[str] = None
    config: dict
    note: Optional[str] = None


@router.post("/{card_id}/update-config")
async def update_card_config(card_id: str, req: UpdateConfigRequest):
    """保存抓取配置：先真实抓取验证，通过后才写库并标记 verified。"""
    card = source_store.get_card(card_id)
    if not card or card["type"] != "website":
        return {"success": False, "error": "网站卡片不存在"}
    preview = _run_preview(req.config)
    if not preview["success"]:
        return {"success": False, "error": preview["error"], "verified": False}
    fields = req.config.get("fields") or {}
    saved_config = {
        "url": (req.config.get("url") or "").strip(),
        "list_selector": req.config.get("list_selector", ""),
        "fields": {"title": str(fields.get("title") or ""),
                   "link": str(fields.get("link") or ""),
                   "date": str(fields.get("date") or "")},
        "pagination": {"type": "none"},
    }
    # 保留发现阶段保存的 DOM 候选，用户手动编辑后仍可切回候选重选
    for k in ("_candidates", "_selected"):
        if k in (card["config"] or {}):
            saved_config[k] = card["config"][k]
    note = (req.note if req.note is not None else card.get("note", ""))
    note = (note + " | 手动验证通过：" + preview["message"]).strip(" |")
    source_store.update_card(card_id, name=req.name or card["name"], config=saved_config,
                             verified=True, note=note)
    return {"success": True, "verified": True, "preview": preview, "message": "配置已验证并保存，现在可以加入检查清单"}


class ReselectRequest(BaseModel):
    index: int
    name: Optional[str] = None


@router.post("/{card_id}/reselect-candidate")
async def reselect_candidate(card_id: str, req: ReselectRequest):
    """从保存的 DOM 候选中重选一个结构，重建配置并真实验证后写库。"""
    from src.utils.dom_analyzer import build_config_from_candidate

    card = source_store.get_card(card_id)
    if not card or card["type"] != "website":
        return {"success": False, "error": "网站卡片不存在"}
    candidates = (card["config"] or {}).get("_candidates") or []
    if not candidates:
        return {"success": False, "error": "该卡片没有保存 DOM 候选（可能是手动创建的），请直接编辑选择器"}
    idx = req.index
    if idx < 0 or idx >= len(candidates):
        return {"success": False, "error": f"候选序号 {idx} 超出范围（共 {len(candidates)} 个）"}

    picked = candidates[idx]
    url = (card["config"] or {}).get("url", "")
    # 重新抓 HTML，因为候选里的 samples 是发现时的快照；用当前页面重验更可靠
    config = build_config_from_candidate(picked, url)
    preview = _run_preview(config)
    if not preview["success"]:
        return {"success": False, "error": f"候选 {idx} 当前不可用：{preview['error']}", "verified": False}
    saved = {**config, "_candidates": candidates, "_selected": idx}
    note = (card.get("note", "") + f" | 人工重选候选 {idx} 验证通过：{preview['message']}").strip(" |")
    source_store.update_card(card_id, name=req.name or card["name"], config=saved,
                             verified=True, note=note)
    return {"success": True, "verified": True, "preview": preview, "selected": idx,
            "message": f"已切换到候选 {idx}（{picked.get('item_count')} 条），验证通过"}


class EditCardRequest(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    url: Optional[str] = None
    account: Optional[str] = None
    enabled: Optional[bool] = None


@router.post("/{card_id}/edit")
async def edit_card(card_id: str, req: EditCardRequest):
    """编辑卡片元数据（名字/备注/URL/公众号名/启用状态），不做抓取验证。

    网站卡片的 URL/选择器因其影响抓取，请走 update-config 或 reselect-candidate 验证后保存；
    这里仅用于改显示名/备注/公众号名等不影响抓取结构的字段。
    """
    card = source_store.get_card(card_id)
    if not card:
        return {"success": False, "error": "卡片不存在"}
    fields: Dict[str, Any] = {}
    if req.name is not None:
        clean = str(req.name).strip()
        if not clean:
            return {"success": False, "error": "卡片名称不能为空"}
        fields["name"] = clean
    if req.note is not None:
        fields["note"] = str(req.note)
    if req.enabled is not None:
        fields["enabled"] = bool(req.enabled)

    cfg = dict(card["config"] or {})
    if req.url is not None:
        clean_url = str(req.url).strip()
        if card["type"] == "website":
            if not clean_url.lower().startswith(("http://", "https://")):
                return {"success": False, "error": "URL 必须是 http/https"}
            if clean_url != cfg.get("url"):
                # URL 变了，旧的选择器/验证结果可能失效，标为未验证让用户重新测试
                cfg["url"] = clean_url
                fields["config"] = cfg
                fields["verified"] = False
        else:
            cfg["url"] = clean_url
            fields["config"] = cfg
    if req.account is not None and card["type"] == "wechat":
        cfg["account"] = str(req.account).strip()
        fields["config"] = cfg
        from src.utils.source_store import sync_wechat_targets
        sync_wechat_targets()

    if not fields:
        return {"success": False, "error": "没有需要更新的字段"}
    source_store.update_card(card_id, **fields)
    return {"success": True, "message": "卡片信息已更新"}
