"""AI 驱动的信源发现：按学生需求生成候选信源卡片。

核心设计（2026-11-18 重构）：CSS 选择器绝不交给 LLM 凭空编写。
 阶段 1：LLM 按需求推荐站点名 + URL（不写选择器）
 阶段 2：系统抓真实 HTML，用 dom_analyzer 提取有效列表候选（选择器来自真实 DOM）
 阶段 3：LLM 看候选样本做语义判断，只返回选中的 index
 阶段 4：用系统生成的选择器实际抓取验证；失败把候选反馈给 LLM 重试（最多 2 次）
 阶段 5：通过才落库为 verified；失败落库为 unverified 且阻止加入清单

相关性判定（2026-11-19 改造）：语义判断交给 LLM 裁判 _judge（pass/reason/feedback），
脚本不做关键词/泛站词表匹配；不达标时把 feedback 回灌给 LLM 聚焦重生成，
用户也可补充需求「再来一轮」；两轮仍不达标由 LLM 说明原因并降级给官方信源。

页面按钮与 Agent 工具共用本模块的服务函数，保证双入口共享同一套存储与逻辑。
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from src.collectors.scrapers.generic_scraper import _http_get, parse_card_items
from src.utils.card_schema import new_card
from src.utils.config_loader import CONFIG, get_school_name
from src.utils.dom_analyzer import build_config_from_candidate, extract_candidates
from src.utils.llm_client import build_llm_client, call_with_retry, describe_llm_error
from src.utils import source_store

load_dotenv()

# ---- 阶段 1：只推荐站点，不写选择器 ----
RECOMMEND_PROMPT = """你是情报信源发现助手。根据用户需求，推荐真实存在的、能稳定获取该主题竞赛/通知的公开网站与公众号。

只输出严格 JSON，不要解释文字。格式：
{
  "topic_keywords": ["需求主题的关键词，如 取证,电子数据,美亚杯 或 AI创作,AIGC,大赛"],
  "websites": [{"name": "站点名称", "url": "入口页完整 URL（http/https）", "note": "推荐理由（一句话）"}],
  "wechat_accounts": [{"name": "公众号全名", "note": "推荐理由（一句话）"}]
}

约束：
- topic_keywords 必须提炼需求里最核心的 2-5 个专属主题词（不要写"学校/通知/竞赛"这种泛词）。
- 推荐的站点/公众号必须与 topic_keywords 高度相关；**禁止用学校官网/教务处/研究生院等泛化站点凑数**，除非需求本身就是校内通知。
- 只推荐你确信存在的公开站点/公众号；不确定就不要输出，绝对不要编造 URL。
- URL 必须是能直接打开的通知列表页或首页（不要登录页、不要搜索结果页）。
- website 最多 6 个，公众号最多 8 个。
"""

# ---- 第二轮：带上 LLM 评审意见的聚焦提示词（不再写死失败原因） ----
REFOCUS_PROMPT = """上一轮生成的信源没有通过相关性评审，评审意见如下：

__JUDGE_FEEDBACK__

现在是第二轮，请根据上面的评审意见**严格改进**，只推荐真正针对该主题、能拿到报名/时间/事件资讯的赛事官网、主办方网站、行业垂直平台与主题相关公众号。

需求：__REQUIREMENT__
主题关键词：__KEYWORDS__
用户补充：__FOLLOWUP__

只输出严格 JSON，格式同前：
{"topic_keywords": [...], "websites": [{"name","url","note"}], "wechat_accounts": [{"name","note"}]}

约束：
- 认真对待评审意见，不要用同类站点敷衍了事。
- 禁止用学校官网/教务处/研究生院/学院首页等泛站凑数（除非需求本身是校内通知）。
- 宁可只推荐 1-2 个真正权威的专门站点，也不要用泛站填充。
- 不确定存在的不要编造 URL。
"""

# ---- 相关性裁判：语义判断交给 LLM，脚本不做关键词匹配 ----
JUDGE_PROMPT = """你是信源相关性评审助手。请判断本轮生成的这批信源卡片是否真正满足用户需求，做语义判断而非字面关键词匹配。

原始需求：__REQUIREMENT__
用户补充：__FOLLOWUP__

本轮卡片（name=名称，type=类型，url=网址，note=推荐理由）：
__CARDS__

审查要点：
- 这批卡片能否稳定拿到该主题赛事的报名、时间、事件等资讯？
- 是否用学校官网/教务处/综合门户等泛站凑数（除非用户要的本来就是校内通知）？
- 公众号是否与主题直接相关，而不是蹭名的泛号？
- 是否有至少 1-2 张真正主题专属的信源（泛站+蹭名号不算）？

只输出严格 JSON：
{
  "pass": true 或 false,
  "reason": "2-3 句话向用户说明是否达标及原因，语气自然、面向用户",
  "feedback": "若 pass=false，具体指出下一轮应如何改进（不要空泛）；若 pass=true 可为空字符串"
}

不要输出解释文字。"""


# ---- 阶段 3：基于真实 DOM 候选做语义选择 ----
SELECT_PROMPT = """你是网页结构分析助手。下面是某个真实网站的若干「通知列表候选」，每个候选都有 CSS 选择器、条目数和前几条样本文本。

请判断哪个候选最可能是「该校的通知/竞赛/讲座列表」（要求：每条是一个独立通知，含标题，通常有日期）。

只输出严格 JSON，格式为一个对象，含键 choice，值为候选 index 的数字，或 -1 表示都不合适。不要输出解释。

候选列表：
__CANDIDATES__

注意：只看样本内容做语义判断，不要修改选择器，不要输出解释。
"""


# ---- 降级：两轮都不达标时，让 LLM 说明原因并给兜底信源 ----
DEGRADE_PROMPT = """你是情报信源发现助手。用户想监控这个主题：
需求：__REQUIREMENT__
主题关键词：__KEYWORDS__

经过两轮检索，只找到少量与该主题直接相关的公开信源。请如实向用户说明情况，并给出你确认存在的、能获取该主题赛事报名/时间/事件资讯的官方信源（宁缺勿滥）。

只输出严格 JSON：
{
  "reason": "向用户说明为什么专门监测站很少/是否确实存在（2-3句话，诚实、简洁）",
  "fallback_websites": [{"name","url","note"}],
  "fallback_wechat": [{"name","note"}]
}

约束：
- fallback 必须是你确信存在的官方/权威站点或公众号，且能拿到该主题的报名时间、赛事事件等资讯。
- 若确实没有专门监测网站，就说明这一点并给出最接近的官方渠道（如赛事主办方官网/公众号）。
- 不要编造 URL。
"""

def _extract_json(text: str) -> Any:
    """从 LLM 回复里稳健抽取 JSON（容忍 ```json 代码块与前后缀）。"""
    if not text:
        return None
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _llm() -> tuple:
    """返回 (client, model)；未配置时返回 (None, 原因)。"""
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    if not api_key:
        return None, "LLM_API_KEY 未配置，无法生成信源卡片"
    model = CONFIG.get("analysis", {}).get("model_name", "")
    if not model:
        return None, "模型名称未配置"
    return build_llm_client(api_key, base_url), model


def _ask_llm(client, model: str, system: str, user: str) -> Any:
    resp = call_with_retry(
        client.chat.completions.create,
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=4000,
    )
    content = resp.choices[0].message.content if resp.choices else ""
    return _extract_json(content)


def _judge(client, model: str, requirement: str, followup: str,
           created: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    """让 LLM 语义判定本轮卡片是否达标，返回 pass/reason/feedback。

    脚本只负责把需求与卡片列表拼成 prompt、解析 JSON，不做任何关键词匹配。
    LLM 调用失败时保守判为不达标，如实标注原因，交由下一轮或降级流程处理。
    """
    if not created:
        return {"pass": False, "reason": "本轮没有生成任何可落地卡片", "feedback": "放宽站点范围，优先保证至少拿到 1-2 个真实可用的信源"}
    card_lines = []
    for c in created:
        text = f"- {c.get('type', '')} | {c.get('name', '')} | {c.get('note', '')}"
        card_lines.append(text[:300])
    prompt = (JUDGE_PROMPT
              .replace("__REQUIREMENT__", requirement)
              .replace("__FOLLOWUP__", followup or "（无）")
              .replace("__CARDS__", "\n".join(card_lines)))
    result = _ask_llm(client, model, JUDGE_PROMPT.split("\n")[0], prompt)
    if not isinstance(result, dict) or "pass" not in result:
        return {"pass": False, "reason": "AI 评审未返回有效结果，无法确认相关性", "feedback": "请重新聚焦主题，给出更具体的赛事专属站点"}
    return {
        "pass": bool(result.get("pass")),
        "reason": str(result.get("reason") or "").strip() or "AI 未给出理由",
        "feedback": str(result.get("feedback") or "").strip(),
    }


def _trim_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给 LLM 看的候选摘要：去掉冗余字段，控制体积。"""
    return [
        {
            "index": c["index"],
            "selector": c["selector"],
            "item_count": c["item_count"],
            "samples": [{"title": s["title"], "date": s.get("date", "")} for s in c["samples"]],
        }
        for c in candidates
    ]


def _apply_choice(client, model: str, candidates: List[Dict[str, Any]],
                  url: str, feedback: str = "") -> Optional[Dict[str, Any]]:
    """让 LLM 从候选中选一个，返回生成好的抓取配置；失败返回 None。"""
    prompt = SELECT_PROMPT.replace("__CANDIDATES__", json.dumps(_trim_candidates(candidates), ensure_ascii=False))
    if feedback:
        prompt += f"\n\n上一次选择失败，原因：{feedback}。请重新判断并只返回 JSON。"
    picked = _ask_llm(client, model, SELECT_PROMPT.split("\n")[0], prompt)
    if not isinstance(picked, dict) or "choice" not in picked:
        return None
    try:
        idx = int(picked["choice"])
    except (ValueError, TypeError):
        return None
    if idx < 0 or idx >= len(candidates):
        return None
    return build_config_from_candidate(candidates[idx], url)


def _verify_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """用生成的配置真实抓一次，验证选择器确实能取到数据。"""
    url = config.get("url", "")
    ok, resp = _http_get(url, timeout=25, retries=1)
    if not ok:
        return {"valid": False, "reason": f"站点不可达: {str(resp)[:100]}"}
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    card = {"id": "verify", "type": "website", "name": "验证", "config": config}
    items = parse_card_items(card, soup, url)
    if not items:
        return {"valid": False, "reason": "选择器未命中任何有效条目（可能页面由 JS 渲染或结构已变化）"}
    return {"valid": True, "count": len(items), "sample": items[0]["title"][:60]}


def _discover_website(client, model: str, site: Dict[str, Any],
                      retry_note: str = "") -> Dict[str, Any]:
    """完整的单站点发现：抓 HTML → 提取候选 → LLM 选 → 验证 → 失败重试。"""
    url = str(site.get("url") or "").strip()
    name = str(site.get("name") or url)[:80]
    note = str(site.get("note") or "")
    if not url.lower().startswith(("http://", "https://")):
        return {"ok": False, "name": name, "reason": "URL 不是 http/https"}

    ok, resp = _http_get(url, timeout=25, retries=1)
    if not ok:
        return {"ok": False, "name": name, "reason": f"站点不可达: {str(resp)[:100]}"}
    html = resp.text
    candidates = extract_candidates(html, url)
    if not candidates:
        return {"ok": False, "name": name,
                "reason": "页面中未找到可用的通知列表结构（可能是 JS 动态渲染或需要登录）"}

    feedback = retry_note
    last_reason = ""
    for attempt in range(3):  # 首次 + 最多 2 次重试
        config = _apply_choice(client, model, candidates, url, feedback)
        if not config:
            # LLM 选择失败时的兜底：候选是系统从真实 DOM 提取的，评分最高者最像通知列表，
            # 直接拿去验证比放弃更有机会成功；验证不过仍会如实记为失败。
            config = build_config_from_candidate(candidates[0], url)
            last_reason = "AI 选择无效，已用评分最高候选兜底"
        verification = _verify_config(config)
        if verification["valid"]:
            detail = (f"验证通过：抓到 {verification['count']} 条，样例「{verification['sample']}」")
            # 把 DOM 候选精简后随配置保存，供用户在卡片工作台人工核对样例/重选结构
            config["_candidates"] = [
                {
                    "index": c["index"],
                    "selector": c["selector"],
                    "item_count": c["item_count"],
                    "fields": c["fields"],
                    "samples": [s["title"] for s in c["samples"] if s.get("title")][:3],
                }
                for c in candidates
            ]
            return {"ok": True, "name": name, "url": url, "config": config,
                    "verified": True, "note": (note + " | " + detail).strip(" |")}
        last_reason = verification["reason"]
        feedback = last_reason
    return {"ok": False, "name": name, "reason": f"重试 3 次仍失败：{last_reason}"}


def _materialize(parsed: Dict[str, Any], client, model: str) -> tuple:
    """把 LLM 推荐的站点/公众号落地为卡片（网站需真实验证）。返回 (created, failures)。"""
    created: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for site in (parsed.get("websites") or [])[:6]:
        if not isinstance(site, dict):
            continue
        result = _discover_website(client, model, site)
        if result["ok"]:
            stored = source_store.add_card("website", result["name"], result["config"],
                                           verified=True, note=result["note"])
            created.append({"id": stored["id"], "type": "website", "name": stored["name"],
                            "verified": True, "note": stored["note"]})
        else:
            failures.append({"name": result["name"], "reason": result["reason"]})
    for account in (parsed.get("wechat_accounts") or [])[:8]:
        if not isinstance(account, dict):
            continue
        name = str(account.get("name") or "").strip()
        if not name:
            continue
        stored = source_store.add_card("wechat", name, {"account": name},
                                       note=str(account.get("note") or ""))
        created.append({"id": stored["id"], "type": "wechat", "name": stored["name"],
                        "verified": False, "note": stored["note"]})
    return created, failures


def _drop_cards(cards: List[Dict[str, Any]]) -> None:
    """删除一组刚生成但不达标的卡片（第二轮重来前清场）。"""
    for c in cards:
        try:
            source_store.remove_card(c["id"])
        except Exception:
            pass


def _focus_prompt(requirement: str, keywords: List[str], followup: str, feedback: str) -> str:
    """构造聚焦提示词：把上一轮评审意见与用户补充一起交给 LLM，由它改进而非脚本拦截。"""
    return (REFOCUS_PROMPT
            .replace("__REQUIREMENT__", requirement)
            .replace("__KEYWORDS__", "、".join(keywords) if keywords else "需求核心主题")
            .replace("__FOLLOWUP__", followup or "（无）")
            .replace("__JUDGE_FEEDBACK__", feedback or "上一轮整体不够切题，请严格围绕需求核心主题"))


def discover_source_cards(requirement: str, followup: str = "", feedback: str = "") -> Dict[str, Any]:
    """按需求生成候选卡片：相关性完全由 LLM 语义评审，不达标时带评审意见聚焦重生成。

    - 达标与否由 LLM 裁判 `_judge` 判定（pass/reason/feedback），脚本不做关键词匹配。
    - 首轮不达标 → 把 LLM 的 feedback 回灌 REFOCUS_PROMPT 再生成一轮。
    - 两轮仍不达标 → LLM 说明原因 + 兜底官方卡片，degrade_note 返回前端弹说明框。
    - followup/feedback 支持「再来一轮」：用户补充需求 + 上一轮理由一起带进来重新生成。
    """
    requirement = (requirement or "").strip()
    followup = (followup or "").strip()
    feedback = (feedback or "").strip()
    if not requirement:
        return {"success": False, "error": "请先描述你的需求（如关注的学校、专业、竞赛类型）"}

    client, model_or_err = _llm()
    if not client:
        return {"success": False, "error": model_or_err}
    model = model_or_err

    school = get_school_name()
    req_text = f"目标学校：{school}\n学生需求：{requirement}" if school else f"学生需求：{requirement}"
    if followup:
        req_text += f"\n用户补充说明：{followup}"

    keywords: List[str] = []
    created: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    rounds: List[Dict[str, Any]] = []
    final_verdict: Dict[str, Any] = {"pass": False, "reason": "尚未评审", "feedback": ""}
    carry_feedback = feedback  # 再来一轮时，上一轮理由作为第一轮的输入

    for round_no in (1, 2):
        # 首轮：若有外部 feedback（用户再来一轮），直接按聚焦模式生成
        if round_no == 1 and not carry_feedback:
            parsed = _ask_llm(client, model, RECOMMEND_PROMPT, req_text)
        else:
            parsed = _ask_llm(client, model, RECOMMEND_PROMPT,
                              _focus_prompt(requirement, keywords, followup, carry_feedback))
        if not isinstance(parsed, dict):
            if round_no == 1:
                return {"success": False, "error": "AI 返回结果无法解析，请换个说法重试"}
            break
        if parsed.get("topic_keywords"):
            keywords = [str(k) for k in parsed["topic_keywords"] if str(k).strip()]

        round_cards, round_failures = _materialize(parsed, client, model)
        final_verdict = _judge(client, model, requirement, followup, round_cards, keywords)
        rounds.append({"round": round_no, "count": len(round_cards),
                       "pass": final_verdict["pass"], "detail": final_verdict["reason"],
                       "feedback": final_verdict["feedback"]})
        created, failures = round_cards, round_failures
        if final_verdict["pass"]:
            break
        # 不达标且还有第二轮：清掉本轮卡片，把评审意见交给 LLM 改进
        carry_feedback = final_verdict["feedback"] or final_verdict["reason"]
        if round_no == 1:
            _drop_cards(round_cards)
            created, failures = [], []

    degrade_note: Optional[str] = None
    # 两轮都不达标 → 降级：LLM 说明原因 + 兜底官方信源
    if not final_verdict["pass"]:
        degrade_prompt = (DEGRADE_PROMPT
                          .replace("__REQUIREMENT__", requirement)
                          .replace("__KEYWORDS__", "、".join(keywords) if keywords else "需求核心主题"))
        if final_verdict.get("feedback"):
            degrade_prompt += f"\n\n上一轮评审意见：{final_verdict['feedback']}"
        degraded = _ask_llm(client, model, RECOMMEND_PROMPT, degrade_prompt)
        if isinstance(degraded, dict):
            degrade_note = str(degraded.get("reason") or "未找到与该主题高度匹配的专门信源，已尽力提供最接近的官方渠道。")
            fallback_cards, fallback_failures = _materialize({
                "websites": degraded.get("fallback_websites") or [],
                "wechat_accounts": degraded.get("fallback_wechat") or [],
            }, client, model)
            created, failures = fallback_cards, fallback_failures
        else:
            degrade_note = "两轮生成均未通过相关性评审，且降级说明获取失败。请手动添加信源卡片。"

    website_ok = sum(1 for c in created if c["type"] == "website")
    wechat_ok = sum(1 for c in created if c["type"] == "wechat")
    msg = f"已生成 {len(created)} 张卡片（网站 {website_ok} 张经抓取验证，公众号 {wechat_ok} 张）。"
    if failures:
        msg += f" {len(failures)} 个站点因无法提取有效结构被跳过。"
    if degrade_note:
        msg += " 注意：本次为降级结果，详见说明。"

    return {
        "success": bool(created), "created_count": len(created), "cards": created,
        "failures": failures, "rounds": rounds, "keywords": keywords,
        "verdict": final_verdict,
        "degraded": bool(degrade_note), "degrade_note": degrade_note, "message": msg,
    }


def list_source_cards() -> Dict[str, Any]:
    """列出全部候选卡片与当前检查清单（顺序即扫描顺序）。"""
    cards = source_store.list_cards()
    checklist = source_store.list_checklist()
    return {
        "success": True,
        "cards": [
            {"id": c["id"], "type": c["type"], "name": c["name"],
             "enabled": c["enabled"], "verified": c["verified"],
             "note": c["note"], "config_summary": _config_summary(c),
             "config": c.get("config", {})}
            for c in cards
        ],
        "checklist": [
            {"card_id": i["card"]["id"], "name": i["card"]["name"],
             "type": i["card"]["type"], "sort_order": i["sort_order"],
             "enabled": i["enabled"]}
            for i in checklist
        ],
        "message": f"候选卡片 {len(cards)} 张，检查清单 {len(checklist)} 项",
    }


def _config_summary(card: Dict[str, Any]) -> str:
    cfg = card.get("config") or {}
    if card["type"] == "website":
        return f"{cfg.get('url', '')} | 列表: {cfg.get('list_selector', '') or '未配置'}"
    if card["type"] == "wechat":
        return f"公众号: {cfg.get('account', card['name'])}"
    if card["type"] == "wechat_group":
        return f"含 {len(cfg.get('children', []))} 个公众号"
    return ""


def add_card_to_checklist(card_id: str) -> Dict[str, Any]:
    """把卡片加入检查清单。未验证的网站卡片会被拒绝（避免加入后永远抓不到数据）。"""
    card = source_store.get_card(card_id)
    if not card:
        return {"success": False, "error": f"未找到卡片 {card_id}"}
    if card["type"] == "website" and not card.get("verified"):
        return {"success": False, "error": "该网站卡片尚未验证可抓取，请先编辑抓取配置并测试通过后重试"}
    if not source_store.add_to_checklist(card_id):
        return {"success": False, "error": "加入清单失败"}
    if card["type"] in ("wechat", "wechat_group"):
        targets = source_store.sync_wechat_targets()
        return {"success": True, "message": f"「{card['name']}」已加入检查清单，公众号目标已更新：{targets}"}
    return {"success": True, "message": f"「{card['name']}」已加入检查清单"}


def remove_card(card_id: str) -> Dict[str, Any]:
    """删除卡片（同时从清单与微信容器引用中清理）。"""
    card = source_store.get_card(card_id)
    if not card:
        return {"success": False, "error": f"未找到卡片 {card_id}"}
    name, card_type = card["name"], card["type"]
    source_store.remove_card(card_id)
    if card_type in ("wechat", "wechat_group"):
        source_store.sync_wechat_targets()
    return {"success": True, "message": f"已删除卡片「{name}」"}
