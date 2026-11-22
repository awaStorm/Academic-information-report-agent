/**
 * frontend/src/pages/SourceCardsPage.tsx - 信源卡片工作台
 * AI 生成 → 拖拽编排 → 检查清单顺序扫描。
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  DndContext, DragEndEvent, DragOverlay, DragStartEvent, CollisionDetection,
  PointerSensor, useSensor, useSensors, useDroppable, useDraggable,
  pointerWithin,
} from "@dnd-kit/core";
import { Radar, Sparkles, Loader2, Plus, ListOrdered, Info, Layers3, SquarePlus } from "lucide-react";
import { sourceCardsApi, CardsData, SourceCard as Card, Verdict, DiscoverResult } from "../api/sourceCards";
import { CandidateCard, WechatGroupCard, ChecklistRow } from "../components/common/SourceCard";
import { toast } from "../components/common/Toast";
import ConfigEditor from "../components/common/ConfigEditor";
import NewCardModal from "../components/common/NewCardModal";
import DegradeNotice from "../components/common/DegradeNotice";
import ReviewBar from "../components/common/ReviewBar";

const SourceCardsPage: React.FC = () => {
  const [data, setData] = useState<CardsData>({ cards: [], checklist: [], message: "" });
  const [requirement, setRequirement] = useState("");
  const [generating, setGenerating] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editingCard, setEditingCard] = useState<Card | null>(null);
  const [creating, setCreating] = useState(false);
  const [degrade, setDegrade] = useState<{ note: string; keywords?: string[]; rounds?: Array<{ round: number; count: number; pass: boolean; detail: string }> } | null>(null);
  const [review, setReview] = useState<{ verdict: Verdict; rounds?: DiscoverResult["rounds"] } | null>(null);
  const [loading, setLoading] = useState(true);
  // 放下时的"吸入"飞行体：接管 DragOverlay 消失后的视觉，飞向目标容器并缩小淡出
  const [absorb, setAbsorb] = useState<{
    key: number; from: { left: number; top: number; width: number; height: number };
    to: { left: number; top: number; width: number; height: number }; name: string;
    groupId: string; cardId: string;
  } | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  // 碰撞检测：只认指针真实进入目标矩形（pointerWithin），绝不按"中心最近"兜底。
  // 这样拖公众号时只有指针确实落进容器/清单行才会命中，避免"仅 y 轴重合就塞进容器"。
  // 清单排序同理：指针移到目标行上才排序，符合直觉。
  const collisionDetection: CollisionDetection = useCallback((args) => pointerWithin(args), []);

  const load = useCallback(async () => {
    try {
      const res = await sourceCardsApi.list();
      setData({ cards: res.cards || [], checklist: res.checklist || [], message: res.message || "" });
    } catch (e) {
      toast.error(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const cardsById = useMemo(() => Object.fromEntries(data.cards.map((c) => [c.id, c])), [data.cards]);
  const wechatGroups = data.cards.filter((c) => c.type === "wechat_group");
  const inChecklist = new Set(data.checklist.map((e) => e.card_id));
  // 已进入某个微信容器的公众号：视为"容器的一部分"，不在仓库单独出现；
  // 从容器移出（或删除容器）后，child 引用消失，卡片自动回到仓库。
  const groupedChildIds = new Set(
    wechatGroups.flatMap((g) => g.config?.children || [])
  );
  const candidates = data.cards.filter((c) =>
    !inChecklist.has(c.id) && c.type !== "wechat_group" && !groupedChildIds.has(c.id)
  );

  const runDiscover = async (followup = "", feedback = "") => {
    setGenerating(true);
    try {
      const res = await sourceCardsApi.discover(requirement.trim(), followup, feedback);
      if (res.success) {
        await load();
        // LLM 评审理由一律展示，让用户看到「为什么达标/不达标」
        if (res.verdict) setReview({ verdict: res.verdict, rounds: res.rounds });
        if (res.degraded && res.degrade_note) {
          // 降级结果：弹说明对话框如实告知用户，不用普通 toast（内容长）
          setDegrade({ note: res.degrade_note, keywords: res.keywords, rounds: res.rounds });
        } else {
          const rounds = res.rounds?.length || 0;
          toast.success((rounds > 1 ? `第 ${rounds} 轮聚焦后：` : "") + (res.message || `已生成 ${res.created_count} 张候选卡片`));
        }
      } else {
        toast.error(res.error || "生成失败，请换个说法重试");
      }
    } catch (e) {
      toast.error(`生成失败: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerate = async () => {
    if (!requirement.trim()) {
      toast.warning("请先描述你的需求，例如关注的学校、专业或竞赛类型");
      return;
    }
    setReview(null);
    setDegrade(null);
    await runDiscover();
  };

  // 「再来一轮」：把用户补充需求与上一轮 LLM 评审意见一起交给 Agent 改进
  const handleRetry = async (followup: string) => {
    await runDiscover(followup, review?.verdict?.feedback || "");
  };

  const handleAddToChecklist = async (id: string, name: string) => {
    try {
      const res = await sourceCardsApi.addToChecklist(id);
      if (res.success) { toast.success(`「${name}」已加入检查清单`); await load(); }
      else toast.error(res.error || "加入失败");
    } catch (e) { toast.error(`加入失败: ${(e as Error).message}`); }
  };

  const handleRemove = async (id: string, name: string) => {
    try {
      const res = await sourceCardsApi.remove(id);
      if (res.success) { toast.success(`已删除「${name}」`); await load(); }
      else toast.error(res.error || "删除失败");
    } catch (e) { toast.error(`删除失败: ${(e as Error).message}`); }
  };

  const handleRemoveFromChecklist = async (id: string, name: string) => {
    try {
      const res = await sourceCardsApi.removeFromChecklist(id);
      if (res.success) { toast.info(`「${name}」已撤下到仓库（卡片保留，可再次拖入清单）`); await load(); }
      else toast.error(res.error || "撤下失败");
    } catch (e) { toast.error(`撤下失败: ${(e as Error).message}`); }
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await sourceCardsApi.setEnabled(id, enabled);
      await load();
    } catch (e) { toast.error(`更新失败: ${(e as Error).message}`); }
  };

  const handleRegister = async () => {
    try {
      const res = await sourceCardsApi.registerWechat();
      toast.success(`公众号检查目标已更新（${res.targets?.length || 0} 个）`);
    } catch (e) { toast.error(`注册失败: ${(e as Error).message}`); }
  };

  const handleCreateGroup = async () => {
    try {
      const res = await sourceCardsApi.createWechatGroup("微信信源组");
      if (res.success) { toast.success("已创建微信容器，把公众号小卡片拖进去吧"); await load(); }
    } catch (e) { toast.error(`创建失败: ${(e as Error).message}`); }
  };

  const handleDeleteGroup = async (id: string) => {
    try {
      const res = await sourceCardsApi.remove(id);
      if (!res.success) toast.error(res.error || "删除失败");
      await load();
    } catch (e) { toast.error(`删除失败: ${(e as Error).message}`); }
  };

  const handleRemoveChild = async (groupId: string, childId: string) => {
    try {
      const res = await sourceCardsApi.removeChild(groupId, childId);
      if (res.success) { toast.info("公众号已移出容器，返回仓库"); await load(); }
      else toast.error(res.error || "移出失败");
    } catch (e) { toast.error(`移出失败: ${(e as Error).message}`); }
  };

  const handleDragStart = (e: DragStartEvent) => setActiveId(String(e.active.id));

  const commitMoveChild = async (groupId: string, id: string) => {
    try {
      const res = await sourceCardsApi.moveChild(groupId, id);
      if (res.success) { toast.success(res.message || "已合并"); await load(); }
      else toast.error(res.error || "合并失败");
    } catch (err) { toast.error(`操作失败: ${(err as Error).message}`); }
  };

  const handleDragEnd = async (e: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = e;
    if (!over) return;
    const id = String(active.id);
    const overId = String(over.id);
    try {
      if (overId === "drop-checklist") {
        if (!inChecklist.has(id)) {
          const res = await sourceCardsApi.addToChecklist(id);
          if (res.success) { toast.success(`「${cardsById[id]?.name}」已加入检查清单`); await load(); }
        }
      } else if (overId.startsWith("group:")) {
        const groupId = overId.slice(6);
        const card = cardsById[id];
        if (card?.type === "wechat") {
          // 先播"吸入"动画，再落库刷新：避免先回弹、卡片再突然消失
          const from = active.rect.current.translated;
          const to = over.rect;
          if (from && to) {
            setAbsorb({
              key: Date.now(),
              from: { left: from.left, top: from.top, width: from.width, height: from.height },
              to: { left: to.left, top: to.top, width: to.width, height: to.height },
              name: card.name, groupId, cardId: id,
            });
          } else {
            await commitMoveChild(groupId, id);
          }
        } else {
          toast.warning("只有公众号小卡片可以合并进微信容器");
        }
      } else if (overId.startsWith("checklist:")) {
        const targetId = overId.slice(10);
        const ids = data.checklist.map((x) => x.card_id);
        const from = ids.indexOf(id);
        if (from >= 0 && from !== ids.indexOf(targetId)) {
          ids.splice(from, 1);
          ids.splice(ids.indexOf(targetId), 0, id);
          await sourceCardsApi.reorder(ids);
          await load();
        }
      }
    } catch (err) { toast.error(`操作失败: ${(err as Error).message}`); }
  };

  if (loading) return <div className="text-gray-500">加载中...</div>;

  const activeCard = activeId ? cardsById[activeId] : null;
  const orderedChecklist = [...data.checklist].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2"><Radar size={20} className="text-accent-light" />信源雷达</h2>
        <p className="text-sm text-gray-500 mt-1">让 AI 按你的需求发现信源，拖拽编排后由 Agent 按清单自上而下扫描</p>
      </div>

      <div className="rounded-xl border border-violet-500/20 bg-gradient-to-r from-violet-500/[0.07] to-transparent p-4">
        <div className="flex gap-2">
          <textarea
            rows={2}
            className="input-field flex-1 resize-y"
            placeholder="描述你的需求，例如：我是计算机专业学生，想盯住本校所有程序设计竞赛报名和保研通知"
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleGenerate(); }}
          />
          <button className="btn-primary px-4 whitespace-nowrap flex items-center gap-2" onClick={handleGenerate} disabled={generating}>
            {generating ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {generating ? "生成中..." : "AI 生成卡片"}
          </button>
          <button className="btn-secondary px-4 whitespace-nowrap flex items-center gap-2" onClick={() => setCreating(true)}>
            <SquarePlus size={16} /> 手动新建
          </button>
        </div>
        <p className="text-[11px] text-gray-600 mt-2 flex items-center gap-1"><Info size={11} />网站卡片会抓取真实页面、自动提取列表结构并实际抓取验证，通过才可加入清单；失败的卡片可用「编辑配置」手动修复。</p>
      </div>

      {review && (
        <ReviewBar verdict={review.verdict} rounds={review.rounds}
          onRetry={handleRetry} retrying={generating} />
      )}

      <DndContext sensors={sensors} collisionDetection={collisionDetection} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="grid grid-cols-3 gap-4">
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2"><Sparkles size={15} className="text-accent-light" />信源仓库（候选卡片） <span className="text-gray-600">{candidates.length}</span></h3>
            <div className="space-y-2.5 max-h-[70vh] overflow-y-auto pr-1">
              {candidates.length === 0 ? (
                <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-xs text-gray-600">暂无候选卡片，先让 AI 生成一批</div>
              ) : candidates.map((card, i) => (
                <div key={card.id} className="animate-rise-in" style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}>
                  <DraggableCard id={card.id}>
                    <CandidateCard card={card}
                      onAddToChecklist={() => handleAddToChecklist(card.id, card.name)}
                      onDelete={() => handleRemove(card.id, card.name)}
                      onEditConfig={() => setEditingCard(card)} />
                  </DraggableCard>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2"><Layers3Icon />微信容器编排</h3>
              <button className="btn-secondary text-[11px] px-2 py-1 flex items-center gap-1" onClick={handleCreateGroup}><Plus size={12} />新建容器</button>
            </div>
            <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
              {wechatGroups.length === 0 ? (
                <div className="rounded-xl border border-dashed border-sky-500/20 p-6 text-center text-xs text-gray-600">点「新建容器」创建微信信源组，再把公众号小卡片拖进来</div>
              ) : wechatGroups.map((grp) => {
                const children = (grp.config?.children || []).map((cid) => cardsById[cid]).filter(Boolean);
                return (
                  <DroppableArea key={grp.id} id={`group:${grp.id}`}>
                    <WechatGroupCard card={grp} children={children} childCount={children.length}
                      onRegister={handleRegister}
                      onRemoveChild={(cid) => handleRemoveChild(grp.id, cid)}
                      onDelete={() => handleDeleteGroup(grp.id)} />
                  </DroppableArea>
                );
              })}
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2"><ListOrdered size={15} className="text-accent-light" />检查清单 <span className="text-gray-600">{orderedChecklist.length}</span></h3>
            <p className="text-[11px] text-gray-600">扫描顺序自上而下，拖动可排序</p>
            <DroppableArea id="drop-checklist">
              <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-1 min-h-[120px] rounded-xl border border-dashed border-white/10 p-2">
                {orderedChecklist.length === 0 ? (
                  <div className="text-center text-xs text-gray-600 py-8">把卡片拖到这里，或点候选卡片的「加入清单」</div>
                ) : orderedChecklist.map((entry) => (
                  <SortableChecklistRow
                    key={entry.card_id}
                    id={entry.card_id}
                    entry={entry}
                    card={cardsById[entry.card_id]}
                    onToggle={(v) => handleToggle(entry.card_id, v)}
                    onRemove={() => handleRemoveFromChecklist(entry.card_id, entry.name)}
                  />
                ))}
              </div>
            </DroppableArea>
          </section>
        </div>
        <DragOverlay dropAnimation={null}>
          {activeCard && !absorb ? <div className="opacity-80 rotate-2 shadow-2xl shadow-black/40"><CandidateCard card={activeCard} /></div> : null}
        </DragOverlay>
      </DndContext>
      {absorb && (
        <AbsorbFly key={absorb.key} absorb={absorb}
          onDone={() => {
            const { groupId, cardId } = absorb;
            setAbsorb(null);
            void commitMoveChild(groupId, cardId);
          }} />
      )}
      {editingCard && (
        <ConfigEditor card={editingCard} onClose={() => setEditingCard(null)} onSaved={load} />
      )}
      {creating && (
        <NewCardModal onClose={() => setCreating(false)} onCreated={load} />
      )}
      {degrade && (
        <DegradeNotice note={degrade.note} keywords={degrade.keywords} rounds={degrade.rounds}
          onClose={() => setDegrade(null)} />
      )}
    </div>
  );
};

function Layers3Icon() { return <Layers3 size={15} className="text-sky-400" />; }

// 放下时从指针位置飞向目标容器中心并缩小淡出，落库在数据刷新前完成，视觉上"被吸进去"
function AbsorbFly({ absorb, onDone }: {
  absorb: { from: { left: number; top: number; width: number; height: number };
    to: { left: number; top: number; width: number; height: number }; name: string };
  onDone: () => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const doneRef = React.useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    const el = ref.current;
    if (!el) { doneRef.current(); return; }
    const { from, to } = absorb;
    const dx = (to.left + to.width / 2) - (from.left + from.width / 2);
    const dy = (to.top + to.height / 2) - (from.top + from.height / 2);
    const anim = el.animate([
      { transform: "translate(0, 0) scale(1) rotate(2deg)", opacity: 0.9 },
      { transform: `translate(${dx}px, ${dy}px) scale(0.15) rotate(0deg)`, opacity: 0 },
    ], { duration: 340, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "forwards" });
    anim.onfinish = () => doneRef.current();
    return () => anim.cancel();
    // 挂载时播放一次即可；absorb 内容在 key 变化时随组件重建
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { from } = absorb;
  return (
    <div ref={ref} className="pointer-events-none fixed z-[90] flex items-center gap-2 rounded-xl border border-sky-400/60 bg-[#1b2433]/95 px-3 py-2 shadow-2xl shadow-sky-500/20"
      style={{ left: from.left, top: from.top, width: from.width, height: Math.min(from.height, 56) }}>
      <span className="w-2 h-2 rounded-full bg-sky-400 flex-shrink-0" />
      <span className="text-sm text-sky-100 truncate">{absorb.name}</span>
    </div>
  );
}

function DraggableCard({ id, children }: { id: string; children: React.ReactNode }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id });
  return <div ref={setNodeRef} {...listeners} {...attributes}>{children}</div>;
}

function SortableChecklistRow({ id, entry, card, onToggle, onRemove }: {
  id: string; entry: import("../api/sourceCards").ChecklistEntry; card?: Card;
  onToggle: (v: boolean) => void; onRemove: () => void;
}) {
  const drag = useDraggable({ id });
  const drop = useDroppable({ id: `checklist:${id}` });
  return (
    <div ref={(node) => { drag.setNodeRef(node); drop.setNodeRef(node); }} {...drag.listeners} {...drag.attributes}
      className={drop.isOver ? "ring-1 ring-accent-primary/60 rounded-lg" : ""}>
      <ChecklistRow entry={entry} card={card} onToggle={onToggle} onRemove={onRemove} />
    </div>
  );
}

function DroppableArea({ id, children }: { id: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div ref={setNodeRef}
      className={`rounded-xl transition-all duration-200 ${isOver ? "ring-2 ring-accent-primary/60 scale-[1.015] shadow-lg shadow-accent-primary/10" : ""}`}>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<{ childrenDropped?: boolean }>, { childrenDropped: isOver })
        : children}
    </div>
  );
}

export default SourceCardsPage;
