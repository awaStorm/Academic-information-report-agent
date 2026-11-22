/**
 * frontend/src/api/sourceCards.ts - 信源卡片工作台 API 封装
 */
import client from "./client";

export type CardType = "website" | "wechat" | "wechat_group" | "chaoxing" | "wechat_system";

export const SYSTEM_CARD_TYPES: CardType[] = ["chaoxing", "wechat_system"];
export const isSystemCard = (t: CardType) => SYSTEM_CARD_TYPES.includes(t);

export interface DomCandidate {
  index: number;
  selector: string;
  item_count: number;
  fields: { title?: string; link?: string; date?: string };
  samples: string[];
}

export interface SourceCard {
  id: string;
  type: CardType;
  name: string;
  enabled: boolean;
  verified: boolean;
  note: string;
  config_summary: string;
  config?: {
    children?: string[]; account?: string; url?: string; list_selector?: string;
    fields?: { title?: string; link?: string; date?: string };
    _candidates?: DomCandidate[];
    _selected?: number;
  };
}

export interface ChecklistEntry {
  card_id: string;
  name: string;
  type: CardType;
  sort_order: number;
  enabled: boolean;
}

export interface CardsData {
  cards: SourceCard[];
  checklist: ChecklistEntry[];
  message: string;
}

export interface ActionResult {
  success: boolean;
  message?: string;
  error?: string;
  targets?: string[];
}

export interface Verdict {
  pass: boolean;
  reason: string;
  feedback: string;
}

export interface DiscoverResult extends ActionResult {
  created_count?: number;
  cards?: Array<{ id: string; type: CardType; name: string; verified: boolean; note: string }>;
  rounds?: Array<{ round: number; count: number; pass: boolean; detail: string; feedback?: string }>;
  keywords?: string[];
  verdict?: Verdict;
  degraded?: boolean;
  degrade_note?: string | null;
}

const BASE = "/api/v1/source-cards";

export const sourceCardsApi = {
  list: () => client.get<{ success: boolean } & CardsData>(BASE),
  discover: (requirement: string, followup = "", feedback = "") =>
    // AI 生成 = LLM 推理 + 逐站可达性验证（含重试退避），远超默认 30s；
    // 这里单独放宽到 300s，避免后端已成功写库、前端却误报超时导致用户重复生成。
    client.post<DiscoverResult>(`${BASE}/discover`, { requirement, followup, feedback }, { timeout: 300000 }),
  add: (data: { type: CardType; name: string; config?: Record<string, unknown>; note?: string; verified?: boolean }) =>
    client.post<ActionResult>(`${BASE}/add`, data),
  addToChecklist: (card_id: string) => client.post<ActionResult>(`${BASE}/checklist/add`, { card_id }),
  removeFromChecklist: (card_id: string) => client.post<ActionResult>(`${BASE}/checklist/remove`, { card_id }),
  reorder: (card_ids: string[]) => client.post<ActionResult>(`${BASE}/checklist/reorder`, { card_ids }),
  setEnabled: (card_id: string, enabled: boolean) =>
    client.post<ActionResult>(`${BASE}/checklist/${card_id}/enable`, { enabled }),
  remove: (card_id: string) => client.delete<ActionResult>(`${BASE}/${card_id}`),
  createWechatGroup: (name: string) => client.post<ActionResult>(`${BASE}/wechat-group/create`, { name }),
  moveChild: (group_id: string, child_id: string) =>
    client.post<ActionResult>(`${BASE}/wechat-group/move-child`, { group_id, child_id }),
  removeChild: (group_id: string, child_id: string) =>
    client.post<ActionResult>(`${BASE}/wechat-group/remove-child`, { group_id, child_id }),
  registerWechat: () => client.post<ActionResult>(`${BASE}/register-wechat`),
  testConfig: (config: { url: string; list_selector: string; fields: Record<string, string> }) =>
    client.post<{
      success: boolean; count?: number; samples?: Array<{ title: string; link: string; date: string }>;
      message?: string; error?: string;
    }>(`${BASE}/test-config`, config),
  updateConfig: (cardId: string, data: {
    name?: string; config: Record<string, unknown>; note?: string;
  }) => client.post<ActionResult & { verified?: boolean }>(`${BASE}/${cardId}/update-config`, data),
  reselect: (cardId: string, index: number, name?: string) =>
    client.post<ActionResult & { preview?: { count?: number; samples?: Array<{ title: string }> } }>(
      `${BASE}/${cardId}/reselect-candidate`, { index, name }),
  edit: (cardId: string, data: {
    name?: string; note?: string; url?: string; account?: string; enabled?: boolean;
  }) => client.post<ActionResult>(`${BASE}/${cardId}/edit`, data),
};
