/**
 * frontend/src/components/common/SourceCard.tsx - 信源卡片 UI 公共组件
 * 大卡片（网站）/ 小卡片（公众号）/ 微信容器 / 清单项，统一暗色视觉。
 */
import React, { useState } from "react";
import { Globe2, MessageCircle, Layers3, GripVertical, ShieldCheck, ShieldAlert, Trash2, Plus, Minus, Settings2, AlertTriangle, BookOpen, GraduationCap, ChevronDown, ChevronRight } from "lucide-react";
import type { CardType, SourceCard as Card, ChecklistEntry } from "../../api/sourceCards";
import { isSystemCard } from "../../api/sourceCards";

export const cardTypeIcon = (type: CardType) => {
  if (type === "website") return <Globe2 size={16} className="text-accent-light" />;
  if (type === "wechat_group") return <Layers3 size={16} className="text-sky-400" />;
  if (type === "chaoxing") return <GraduationCap size={16} className="text-orange-400" />;
  if (type === "wechat_system") return <BookOpen size={16} className="text-emerald-400" />;
  return <MessageCircle size={16} className="text-green-400" />;
};

interface CandidateCardProps {
  card: Card;
  onAddToChecklist?: () => void;
  onDelete?: () => void;
  onEditConfig?: () => void;
  dragging?: boolean;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({ card, onAddToChecklist, onDelete, onEditConfig, dragging }) => {
  const blocked = card.type === "website" && !card.verified;
  return (
    <div
      className={`relative rounded-xl border bg-[#1E1E2E]/80 p-3.5 transition-all duration-200
        ${dragging ? "opacity-40 scale-[.98]" : "hover:border-accent-primary/40 hover:shadow-lg hover:shadow-accent-primary/5"}
        ${card.type === "website" ? "border-violet-500/20" : "border-green-500/20"}`}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5">{cardTypeIcon(card.type)}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-gray-100 truncate">{card.name}</h4>
            {card.type === "website" && (
              card.verified
                ? <ShieldCheck size={13} className="text-green-400 flex-shrink-0" aria-label="已验证可达" />
                : <ShieldAlert size={13} className="text-amber-400 flex-shrink-0" aria-label="未验证" />
            )}
          </div>
          <p className="text-[11px] text-gray-500 mt-1 line-clamp-2 leading-relaxed">{card.config_summary || card.note || "—"}</p>
          <div className="flex items-center gap-2 mt-2.5">
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-gray-500">
              {card.type === "website" ? "网站大卡片" : card.type === "wechat_group" ? "微信容器" : "公众号小卡片"}
            </span>
            {!card.enabled && <span className="text-[10px] text-gray-600">已停用</span>}
          </div>
        </div>
        <GripVertical size={15} className="text-gray-600 flex-shrink-0 cursor-grab" />
      </div>
      {blocked && (
        <p className="mt-2 text-[10px] text-amber-400/90 flex items-start gap-1">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          <span>未验证可抓取，需先编辑配置并测试通过后才能加入清单</span>
        </p>
      )}
      <div className="flex gap-2 mt-3 pt-2.5 border-t border-white/5">
        {onEditConfig && (
          <button className="btn-secondary text-[11px] px-2.5 py-1 flex items-center gap-1" onClick={onEditConfig}>
            <Settings2 size={12} /> {card.type === "website" ? "编辑配置" : "编辑"}
          </button>
        )}
        {onAddToChecklist && (
          <button
            className={`text-[11px] px-2.5 py-1 flex items-center gap-1 ${blocked
              ? "bg-white/5 border border-white/10 text-gray-600 cursor-not-allowed rounded-lg"
              : "btn-primary"}`}
            onClick={blocked ? undefined : onAddToChecklist}
            disabled={blocked}
          >
            <Plus size={12} /> 加入清单
          </button>
        )}
        {onDelete && (
          <button className="btn-secondary text-[11px] px-2.5 py-1 flex items-center gap-1 hover:!text-red-400" onClick={onDelete}>
            <Trash2 size={12} /> 删除
          </button>
        )}
      </div>
    </div>
  );
};

interface WechatGroupCardProps {
  card: Card;
  children: Card[];
  childCount: number;
  onRegister?: () => void;
  onRemoveChild?: (childId: string) => void;
  onDelete?: () => void;
  childrenDropped?: boolean;
}

export const WechatGroupCard: React.FC<WechatGroupCardProps> = ({
  card, children, childCount, onRegister, onRemoveChild, onDelete, childrenDropped,
}) => {
  return (
    <div className={`rounded-xl border-2 border-dashed p-3.5 transition-all duration-200 min-h-[120px]
      ${childrenDropped ? "border-sky-400/70 bg-sky-500/5" : "border-sky-500/25 bg-sky-500/[0.03]"}`}>
      <div className="flex items-center gap-2 mb-2.5">
        <Layers3 size={16} className="text-sky-400" />
        <h4 className="text-sm font-semibold text-gray-200 flex-1 truncate">{card.name}</h4>
        {onDelete && (
          <button aria-label="删除容器" title="删除容器（里面的公众号返回仓库，不会删除公众号卡片）"
            className="text-gray-600 hover:text-red-400 transition-colors" onClick={onDelete}>
            <Trash2 size={14} />
          </button>
        )}
      </div>
      <div className="mb-2.5">
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400">微信容器 · {childCount} 个公众号</span>
      </div>
      {children.length === 0 ? (
        <p className="text-[11px] text-gray-600 py-3 text-center">把公众号小卡片拖到这里合并</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {children.map((c) => (
            <span key={c.id} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-white/5 border border-white/10 text-gray-300">
              <MessageCircle size={11} className="text-green-400" />
              {c.name}
              {onRemoveChild && (
                <button aria-label="移出容器" className="text-gray-600 hover:text-red-400" onClick={() => onRemoveChild(c.id)}>
                  <Minus size={11} />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {onRegister && (
        <button className="btn-primary text-[11px] px-2.5 py-1 mt-3" onClick={onRegister}>
          注册到公众号检查
        </button>
      )}
    </div>
  );
};

interface ChecklistRowProps {
  entry: ChecklistEntry;
  card?: Card;
  onToggle?: (enabled: boolean) => void;
  onRemove?: () => void;
  dragging?: boolean;
}

export const ChecklistRow: React.FC<ChecklistRowProps> = ({ entry, card, onToggle, onRemove, dragging }) => {
  const [expanded, setExpanded] = useState(false);
  const cfg = card?.config || {};
  return (
    <div className={`rounded-lg border transition-all
      ${dragging ? "opacity-40" : "bg-white/[0.03] border-white/5 hover:border-accent-primary/30"}`}>
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <GripVertical size={15} className="text-gray-600 flex-shrink-0 cursor-grab" />
        <span className="text-[11px] w-5 text-gray-500 font-mono">{entry.sort_order}</span>
        {cardTypeIcon(entry.type)}
        <span className="text-sm text-gray-200 flex-1 truncate">{entry.name}</span>
        {isSystemCard(entry.type) && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 flex-shrink-0">系统内置</span>
        )}
        <button aria-label={expanded ? "收起详情" : "展开详情"} title={expanded ? "收起详情" : "展开详情"}
          className="text-gray-600 hover:text-accent-light transition-colors flex-shrink-0" onClick={() => setExpanded(v => !v)}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <input
          type="checkbox"
          checked={entry.enabled}
          onChange={(e) => onToggle?.(e.target.checked)}
          className="accent-violet-500 cursor-pointer"
          title="启用/停用该信源"
        />
        {!isSystemCard(entry.type) && (
          <button aria-label="撤下到仓库" title="撤下到仓库（卡片保留在候选卡片库，可再次加入）"
            className="text-gray-600 hover:text-amber-400 transition-colors" onClick={onRemove}>
            <Minus size={13} />
          </button>
        )}
      </div>
      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-white/5 space-y-1.5 text-[11px] leading-relaxed">
          <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">类型</span>
            <span className="text-gray-300">{entry.type === "website" ? "网站" : entry.type === "chaoxing" ? "超星内核" : entry.type === "wechat_system" ? "微信内核" : "公众号"}</span></div>
          {card?.note && <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">备注</span>
            <span className="text-gray-300 break-all">{card.note}</span></div>}
          {cfg.url && <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">地址</span>
            <a className="text-accent-light break-all hover:underline" href={cfg.url} target="_blank" rel="noreferrer">{cfg.url}</a></div>}
          {entry.type === "website" && (
            <>
              <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">列表</span>
                <code className="text-gray-300 break-all">{cfg.list_selector || "未配置"}</code></div>
              {cfg.fields && (
                <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">字段</span>
                  <span className="text-gray-300 break-all">
                    标题 {cfg.fields.title || "—"} · 链接 {cfg.fields.link || "—"} · 日期 {cfg.fields.date || "—"}
                  </span></div>
              )}
            </>
          )}
          {entry.type === "wechat" && cfg.account && (
            <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">公众号</span>
              <span className="text-gray-300">{cfg.account}</span></div>
          )}
          <div className="flex gap-2"><span className="text-gray-500 w-12 flex-shrink-0">状态</span>
            <span className={card?.verified ? "text-green-400" : "text-gray-400"}>
              {card?.verified ? "已验证可达" : "未验证/内核信源"}
            </span></div>
        </div>
      )}
    </div>
  );
};
