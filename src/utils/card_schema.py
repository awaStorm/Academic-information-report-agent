"""信源卡片数据契约。

生成、校验、抓取、合流、前端 API 共用同一套字段定义，避免各处自由拼字段导致断层。
"""
from typing import Any, Dict, List, TypedDict

CARD_TYPE_WEBSITE = "website"
CARD_TYPE_WECHAT = "wechat"
CARD_TYPE_WECHAT_GROUP = "wechat_group"
# 系统内置信源：对应项目原有的两条采集内核，只作清单展示/顺序占位，不可删除
CARD_TYPE_CHAOXING = "chaoxing"
CARD_TYPE_WECHAT_SYSTEM = "wechat_system"
SYSTEM_CARD_TYPES = (CARD_TYPE_CHAOXING, CARD_TYPE_WECHAT_SYSTEM)


class WebsiteCardConfig(TypedDict, total=False):
    url: str
    list_selector: str
    fields: Dict[str, str]          # title / link / date -> CSS 选择器
    pagination: Dict[str, Any]      # {"type": "none"|"url_template", "template": "..."}
    request_headers: Dict[str, str]


class WechatCardConfig(TypedDict, total=False):
    account: str                    # 公众号全名


class WechatGroupConfig(TypedDict, total=False):
    children: List[str]             # wechat 卡片 id 列表（拖入合并后写入）


class SourceCard(TypedDict):
    id: str
    type: str                       # website / wechat / wechat_group
    name: str
    enabled: bool
    config: Dict[str, Any]
    verified: bool
    note: str
    created_at: str


class ChecklistItem(TypedDict):
    card_id: str
    sort_order: int
    enabled: bool


def new_card(card_id: str, card_type: str, name: str, config: Dict[str, Any],
             verified: bool = False, note: str = "") -> SourceCard:
    """构造符合契约的卡片对象，补齐默认值。"""
    from datetime import datetime

    return SourceCard(
        id=card_id,
        type=card_type,
        name=name,
        enabled=True,
        config=config or {},
        verified=bool(verified),
        note=note or "",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def is_valid_card_type(card_type: str) -> bool:
    return card_type in (
        CARD_TYPE_WEBSITE, CARD_TYPE_WECHAT, CARD_TYPE_WECHAT_GROUP,
        CARD_TYPE_CHAOXING, CARD_TYPE_WECHAT_SYSTEM,
    )


def is_system_card(card: Dict[str, Any]) -> bool:
    """系统内置卡片（超星/微信采集内核）不能被删除或改抓取配置。"""
    return str(card.get("type", "")) in SYSTEM_CARD_TYPES
