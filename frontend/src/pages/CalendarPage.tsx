/**
 * frontend/src/pages/CalendarPage.tsx - 事件日历
 * 月份网格视图：CTF 赛事（青色）+ 情报推送（琥珀色）
 * 单击某天 → 右侧面板显示当天事件详情
 */
import React, { useState, useEffect, useMemo } from "react";
import { ChevronLeft, ChevronRight, Trophy, Newspaper, ExternalLink } from "lucide-react";
import { calendarApi, CalendarResponse, CalendarDayData } from "../api/calendar";
import EventDetailModal, { DetailField, eventToFields, eventToParagraphs } from "../components/common/EventDetailModal";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

const ctfStatusBadge: Record<string, string> = {
  running: "text-green-400 bg-green-400/10",
  upcoming: "text-cyan-400 bg-cyan-400/10",
  recently_ended: "text-gray-400 bg-gray-400/10",
  expired: "text-gray-500 bg-gray-500/10",
};
const ctfStatusLabel: Record<string, string> = {
  running: "进行中",
  upcoming: "即将开始",
  recently_ended: "近期结束",
  expired: "已结束",
};

// CTFtime 时刻本身是 UTC，日历侧标签也标注（UTC），因此统一按 UTC 渲染，
// 否则 23:59 UTC 会被本地时区（+8）推到次日的 07:59，出现"跨日"的假象。
// 始终输出 HH:MM：解析层已保证每条赛事都带真实时刻，不能用"时刻恰好为 00:00"
// 去反推"没有时刻"（SUNCTF 2026 就是 00:00 UTC 开赛，会被误隐藏）。
function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${hh}:${mi}`;
}

const CalendarPage: React.FC = () => {
  const now = new Date();
  const [viewYear, setViewYear] = useState(now.getFullYear());
  const [viewMonth, setViewMonth] = useState(now.getMonth()); // 0-based
  const [selectedDate, setSelectedDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<{ title: string; badge: string; fields: DetailField[]; paragraphs: Array<{ label?: string; text: string }> } | null>(null);
  // 图例筛选：被隐藏的事件类型（ctf/intel），同时影响日历打点与右侧详情卡片
  // 持久化到 localStorage：刷新/重开页面后仍保持用户的隐藏选择
  const HIDDEN_KEY = "calendar_hidden_types";
  const [hiddenTypes, setHiddenTypes] = useState<Set<"ctf" | "intel">>(() => {
    try {
      const raw = localStorage.getItem(HIDDEN_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(arr) ? arr.filter((x) => x === "ctf" || x === "intel") : []);
    } catch { return new Set(); }
  });
  const toggleType = (t: "ctf" | "intel") => setHiddenTypes((prev) => {
    const next = new Set(prev);
    next.has(t) ? next.delete(t) : next.add(t);
    try { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
    return next;
  });

  const monthStr = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}`;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    calendarApi.getCalendar(monthStr)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((e) => console.error(e))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [monthStr]);

  // 当月日期网格（周一开头）
  const cells = useMemo(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const offset = (first.getDay() + 6) % 7; // 周一=0
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const list: (number | null)[] = [];
    for (let i = 0; i < offset; i++) list.push(null);
    for (let d = 1; d <= daysInMonth; d++) list.push(d);
    while (list.length % 7 !== 0) list.push(null);
    return list;
  }, [viewYear, viewMonth]);

  const dayKey = (d: number) => `${monthStr}-${String(d).padStart(2, "0")}`;
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  };
  const backToToday = () => {
    setViewYear(now.getFullYear());
    setViewMonth(now.getMonth());
    setSelectedDate(todayStr);
  };

  // 跳转到指定日期（可跨月：切换月份后 monthStr 变化，useEffect 自动加载该月数据）
  const goToDate = (dateStr: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
    if (!m) return;
    setViewYear(Number(m[1]));
    setViewMonth(Number(m[2]) - 1);
    setSelectedDate(dateStr);
  };

  const selected: CalendarDayData | undefined = data?.days?.[selectedDate];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">事件日历</h2>

      <div className="flex gap-6 items-start">
        {/* 月历网格 */}
        <div className="card flex-shrink-0 w-[460px]">
          {/* 月份导航 */}
          <div className="flex items-center justify-between mb-4">
            <button className="btn-secondary !px-2 !py-1" onClick={prevMonth} aria-label="上一月">
              <ChevronLeft size={16} />
            </button>
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{viewYear} 年 {viewMonth + 1} 月</span>
              <button className="text-xs text-gray-500 hover:text-accent-light transition-colors" onClick={backToToday}>
                回到今天
              </button>
            </div>
            <button className="btn-secondary !px-2 !py-1" onClick={nextMonth} aria-label="下一月">
              <ChevronRight size={16} />
            </button>
          </div>

          {/* 星期表头 */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {WEEKDAYS.map((w) => (
              <div key={w} className="text-center text-xs text-gray-500 py-1">{w}</div>
            ))}
          </div>

          {/* 日期网格 */}
          <div className="grid grid-cols-7 gap-1">
            {cells.map((d, i) => {
              if (d === null) return <div key={i} className="h-14" />;
              const key = dayKey(d);
              const dayData = data?.days?.[key];
              const hasCtf = !hiddenTypes.has("ctf") && (dayData?.ctf?.length ?? 0) > 0;
              const hasIntel = !hiddenTypes.has("intel") && (dayData?.intel?.length ?? 0) > 0;
              const isToday = key === todayStr;
              const isSelected = key === selectedDate;
              return (
                <button key={i} onClick={() => setSelectedDate(key)}
                  className={`h-14 rounded-lg border text-left px-1.5 py-1 transition-all duration-150
                    ${isSelected
                      ? "border-accent-primary/60 bg-accent-primary/10"
                      : "border-white/5 hover:border-white/15 hover:bg-white/5"}`}
                >
                  <div className={`text-xs ${isToday ? "text-accent-light font-bold" : "text-gray-300"}`}>
                    {d}
                    {isToday && <span className="ml-0.5 text-[10px]">今</span>}
                  </div>
                  <div className="flex gap-1 mt-1.5 items-center">
                    {hasCtf && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_4px_rgba(34,211,238,0.6)]" />}
                    {hasIntel && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shadow-[0_0_4px_rgba(245,158,11,0.6)]" />}
                    {dayData && ((hiddenTypes.has("ctf") ? 0 : dayData.ctf.length) + (hiddenTypes.has("intel") ? 0 : dayData.intel.length)) > 2 && (
                      <span className="text-[10px] text-gray-500">
                        {(hiddenTypes.has("ctf") ? 0 : dayData.ctf.length) + (hiddenTypes.has("intel") ? 0 : dayData.intel.length)}
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* 图例（可点击隐藏对应类型：hover 变红+缩放，隐藏时删除线） */}
          <div className="flex gap-4 mt-4 text-xs text-gray-500">
            <button type="button" onClick={() => toggleType("ctf")}
              className={`flex items-center gap-1.5 transition-all duration-150 hover:text-red-400 hover:scale-105 ${
                hiddenTypes.has("ctf") ? "text-gray-600" : ""}`}>
              <span className={`w-1.5 h-1.5 rounded-full bg-cyan-400 ${hiddenTypes.has("ctf") ? "opacity-30" : ""}`} />
              <span className={hiddenTypes.has("ctf") ? "line-through" : ""}>CTF 赛事</span>
            </button>
            <button type="button" onClick={() => toggleType("intel")}
              className={`flex items-center gap-1.5 transition-all duration-150 hover:text-red-400 hover:scale-105 ${
                hiddenTypes.has("intel") ? "text-gray-600" : ""}`}>
              <span className={`w-1.5 h-1.5 rounded-full bg-amber-400 ${hiddenTypes.has("intel") ? "opacity-30" : ""}`} />
              <span className={hiddenTypes.has("intel") ? "line-through" : ""}>情报推送</span>
            </button>
          </div>
        </div>

        {/* 右侧：当天事件详情 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">
              {selectedDate} 事件详情
              {selectedDate === todayStr && <span className="ml-2 text-xs text-accent-light">今天</span>}
            </h3>
            {loading && <span className="text-xs text-gray-500">加载中...</span>}
          </div>

          {loading ? (
            <div className="card text-center text-gray-600 py-12 text-sm">
              加载中...
            </div>
          ) : !selected ? (
            <div className="card text-center text-gray-600 py-12 text-sm">
              当天暂无事件
            </div>
          ) : hiddenTypes.has("ctf") && hiddenTypes.has("intel") ? (
            <div className="card text-center text-gray-600 py-12 text-sm">
              两类事件均已隐藏，点击上方图例恢复显示
            </div>
          ) : (
            <div className="space-y-4 max-h-[560px] overflow-y-auto pr-2">
              {/* CTF 赛事 */}
              {!hiddenTypes.has("ctf") && selected.ctf.length > 0 && (
                <div className="space-y-2">
                  {selected.ctf.map((e) => (
                    <div key={e.id}
                      onClick={() => setDetail({
                        title: e.name,
                        badge: ctfStatusLabel[e.status] || e.status,
                        fields: eventToFields(e as unknown as Record<string, unknown>),
                        paragraphs: eventToParagraphs(e as unknown as Record<string, unknown>),
                      })}
                      className="card !p-4 cursor-pointer hover:border-cyan-400/40 hover:bg-cyan-400/[0.03] transition-colors">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="flex items-center gap-1.5 text-sm font-semibold text-white">
                          <Trophy size={14} className="text-cyan-400" />{e.name}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded ${ctfStatusBadge[e.status] || "text-gray-400 bg-gray-400/10"}`}>
                          {ctfStatusLabel[e.status] || e.status}
                        </span>
                      </div>
                      <div className="text-xs text-gray-500 space-y-0.5">
                        <div>⏱ {fmtDate(e.start_time)}{e.end_time ? ` — ${fmtDate(e.end_time)}` : ""}（UTC）</div>
                        {e.format && <div>赛制：{e.format} ｜ 权重：{e.weight ?? 0}</div>}
                        {e.location && <div>📍 {e.location}</div>}
                      </div>
                      <div className="flex gap-2 mt-2">
                        {e.official_url && (
                          <a href={e.official_url} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}
                            className="inline-flex items-center gap-1 text-xs text-accent-light hover:underline">
                            官网 <ExternalLink size={11} />
                          </a>
                        )}
                        {e.ctftime_url && (
                          <a href={e.ctftime_url} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}
                            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-accent-light transition-colors">
                            CTFtime <ExternalLink size={11} />
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 情报推送 */}
              {!hiddenTypes.has("intel") && selected.intel.length > 0 && (
                <div className="space-y-2">
                  {selected.intel.map((item, idx) => (
                    <div key={idx}
                      onClick={() => setDetail({
                        title: item.title,
                        badge: item.category,
                        fields: eventToFields(item as unknown as Record<string, unknown>),
                        paragraphs: eventToParagraphs(item as unknown as Record<string, unknown>),
                      })}
                      className="card !p-4 cursor-pointer hover:border-amber-400/40 hover:bg-amber-400/[0.03] transition-colors">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="flex items-center gap-1.5 text-sm font-semibold text-white">
                          <Newspaper size={14} className="text-amber-400" />{item.title}
                        </span>
                        <span className="text-xs text-gray-500">{item.push_time?.slice(11, 16)}</span>
                      </div>
                      <div className="flex gap-2 mb-1.5">
                        <span className={`text-xs px-2 py-0.5 rounded ${item.platform === "wechat" ? "text-green-400 bg-green-400/10" : "text-blue-400 bg-blue-400/10"}`}>
                          {item.platform === "wechat" ? "WeChat" : "ChaoXing"}
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded text-gray-400 bg-gray-400/10">{item.category}</span>
                      </div>
                      <p className="text-xs text-gray-500 line-clamp-2">{item.brief}</p>
                      {/* timeline 节点打点：该卡片因某个时间点（报名/初赛/决赛）出现在当天 */}
                      {item.timeline_node && (
                        <div className="mt-1.5">
                          <span className="text-xs px-2 py-0.5 rounded bg-amber-400/15 text-amber-300 border border-amber-400/40 font-medium">
                            📌 此日节点：{item.timeline_node.label || "事件"}
                            {item.timeline_node.time ? ` ${item.timeline_node.time}` : ""}
                          </span>
                        </div>
                      )}
                      {/* 事件时间轴（节点可点击跳转对应日期，支持跨月） */}
                      {item.timeline && item.timeline.length > 0 && (
                        <div className="mt-2">
                          <div className="text-[10px] text-gray-600 mb-1">📅 事件时间轴</div>
                          <div className="flex flex-wrap items-center gap-1">
                            {item.timeline.filter((n) => n && typeof n === "object").map((node, ni, arr) => {
                              const nodeDate = node.date?.slice(0, 10) || "";
                              const canJump = /^\d{4}-\d{2}-\d{2}$/.test(nodeDate);
                              const chipCls = "text-xs px-2 py-0.5 rounded bg-amber-400/10 text-amber-300 border border-amber-400/30";
                              const chipText = `${node.label} ${node.date?.slice(5) ?? ""}${node.time ? ` ${node.time}` : ""}`;
                              return (
                                <React.Fragment key={ni}>
                                  {canJump ? (
                                    <button type="button" onClick={(ev) => { ev.stopPropagation(); goToDate(nodeDate); }}
                                      className={`${chipCls} hover:bg-amber-400/25 hover:border-amber-400/60 cursor-pointer transition-colors`}>
                                      {chipText}
                                    </button>
                                  ) : (
                                    <span className={chipCls}>
                                      {chipText}
                                    </span>
                                  )}
                                  {ni < arr.length - 1 && (
                                    <span className="text-gray-600 text-xs">→</span>
                                  )}
                                </React.Fragment>
                              );
                            })}
                          </div>
                        </div>
                      )}
                      {item.links && item.links.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {item.links.slice(0, 5).map((l, li) => (
                            <a key={li} href={l} target="_blank" rel="noreferrer" title={l} onClick={(ev) => ev.stopPropagation()}
                              className="text-xs px-2 py-0.5 rounded text-accent-light bg-accent-primary/10 border border-accent-primary/30 hover:bg-accent-primary/20 transition-colors max-w-[220px] truncate">
                              🔗 {li === 0 ? "原文" : `引用${li}`}
                            </a>
                          ))}
                          {item.links.length > 5 && (
                            <span className="text-xs px-2 py-0.5 text-gray-500">+{item.links.length - 5}</span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {detail && (
        <EventDetailModal title={detail.title} badge={detail.badge}
          fields={detail.fields} paragraphs={detail.paragraphs} onClose={() => setDetail(null)} />
      )}
    </div>
  );
};

export default CalendarPage;
