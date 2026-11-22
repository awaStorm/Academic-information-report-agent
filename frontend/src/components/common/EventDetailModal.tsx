/**
 * frontend/src/components/common/EventDetailModal.tsx - 事件详情弹窗（通用）
 * 日历 / 仪表盘 / CTF 页的事件卡片点开后，展示该事件的全部已知字段。
 * 只做展示、无需输入；字段由调用方归一化传入（文本或链接）。
 */
import React from "react";
import { X, Info, ExternalLink } from "lucide-react";

export interface DetailField {
  label: string;
  value: string;
  href?: string;
  mono?: boolean;
}

/** 把任意事件对象（CTF / 情报记录）转成详情字段；跳过空值，链接字段带 href。 */
export function eventToFields(
  event: Record<string, unknown>,
  options: { linkKeys?: string[] } = {}
): DetailField[] {
  const LABELS: Record<string, string> = {
    name: "名称", title: "标题", date: "日期", event_date: "事件日期",
    start_time: "开始", end_time: "结束", push_time: "推送时间",
    platform: "来源", category: "分类", status: "状态", format: "赛制",
    location: "地点", weight: "权重", timeline_node: "当日节点",
    ctftime_url: "CTFtime", official_url: "官网", link: "原文链接",
  };
  const LINK_KEYS = new Set(["ctftime_url", "official_url", "link", ...(options.linkKeys || [])]);
  const SKIP = new Set(["id", "brief", "notes", "timeline", "links", "name", "title"]);
  const fields: DetailField[] = [];
  for (const [k, v] of Object.entries(event)) {
    if (SKIP.has(k) || v === null || v === undefined || v === "") continue;
    let value: string;
    if (Array.isArray(v)) {
      value = v.map((n) => typeof n === "object" && n !== null
        ? `${(n as Record<string, unknown>).label || ""} ${(n as Record<string, unknown>).date || ""}`.trim()
        : String(n)).join("、");
    } else if (typeof v === "object") {
      const o = v as Record<string, unknown>;
      value = `${o.label || ""} ${o.time || ""}`.trim();
    } else {
      value = String(v);
    }
    if (!value) continue;
    fields.push({ label: LABELS[k] || k, value, href: LINK_KEYS.has(k) && /^https?:\/\//.test(value) ? value : undefined });
  }
  return fields;
}

/** 从事件对象提取正文段落（brief/notes）与附加链接（links/timeline）。 */
export function eventToParagraphs(event: Record<string, unknown>): Array<{ label: string; text: string }> {
  const out: Array<{ label: string; text: string }> = [];
  if (typeof event.brief === "string" && event.brief) out.push({ label: "情报摘要", text: event.brief });
  if (typeof event.notes === "string" && event.notes) out.push({ label: "赛事备注", text: event.notes });
  if (Array.isArray(event.links) && event.links.length) {
    out.push({ label: "关联链接", text: (event.links as unknown[]).map((l) => String(l)).join("\n") });
  }
  return out;
}

interface Props {
  title: string;
  badge?: string;
  fields: DetailField[];
  paragraphs?: Array<{ label?: string; text: string }>;
  onClose: () => void;
}

const EventDetailModal: React.FC<Props> = ({ title, badge, fields, paragraphs = [], onClose }) => {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-overlay-in" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl border border-violet-500/25 bg-[#13131F] p-5 shadow-2xl animate-modal-in"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2 min-w-0">
            <Info size={19} className="text-accent-light flex-shrink-0 mt-0.5" />
            <div className="min-w-0">
              <h3 className="text-lg font-bold text-white break-words">{title}</h3>
              {badge && <span className="inline-block mt-1 text-[11px] px-2 py-0.5 rounded bg-violet-500/15 text-violet-300">{badge}</span>}
            </div>
          </div>
          <button className="text-gray-500 hover:text-gray-300 flex-shrink-0" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </div>

        <div className="mt-4 space-y-1.5">
          {fields.map((f, i) => (
            <div key={i} className="flex gap-3 text-[13px] leading-relaxed">
              <span className="text-gray-500 w-16 flex-shrink-0">{f.label}</span>
              {f.href ? (
                <a href={f.href} target="_blank" rel="noreferrer"
                  className="text-accent-light break-all hover:underline inline-flex items-center gap-1">
                  {f.value} <ExternalLink size={12} className="flex-shrink-0" />
                </a>
              ) : (
                <span className={`text-gray-200 break-all ${f.mono ? "font-mono text-xs" : ""}`}>{f.value || "—"}</span>
              )}
            </div>
          ))}
        </div>

        {paragraphs.map((p, i) => (
          <div key={i} className="mt-4">
            {p.label && <p className="text-xs text-gray-500 mb-1">{p.label}</p>}
            <p className="text-[13px] text-gray-300 leading-relaxed whitespace-pre-wrap break-words rounded-lg border border-white/5 bg-white/[0.02] p-3">
              {p.text || "—"}
            </p>
          </div>
        ))}

        <div className="mt-5 flex justify-end">
          <button className="btn-primary text-sm px-4" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
};

export default EventDetailModal;
