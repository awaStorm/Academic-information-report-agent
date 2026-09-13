/**
 * frontend/src/pages/CtfPage.tsx - CTF 赛事时间表 (v4)
 * + 自定义暗色下拉排序 + 绿/黄/红状态灯 + 大头钉置顶 + Official URL
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  RefreshCw,
  Globe,
  MapPin,
  Trophy,
  Clock,
  Pin,
  PinOff,
  ExternalLink,
  ArrowUpDown,
  ChevronDown,
} from "lucide-react";
import { ctfApi, type CtfEvent, type SortOption, type CtfStatus } from "../api/ctf";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const formatColors: Record<string, string> = {
  Jeopardy: "text-amber-400 bg-amber-400/10",
  "Attack-Defense": "text-red-400 bg-red-400/10",
  "Hack quest": "text-cyan-400 bg-cyan-400/10",
};

const SORT_LABELS: Record<SortOption, string> = {
  default: "默认排序",
  weight_desc: "高权重优先",
  weight_asc: "低权重优先",
  format_jeopardy: "赛制优先: Jeopardy",
  format_ad: "赛制优先: Attack-Defense",
  format_hackquest: "赛制优先: Hack quest",
};

const SORT_OPTIONS: SortOption[] = [
  "default",
  "weight_desc",
  "weight_asc",
  "format_jeopardy",
  "format_ad",
  "format_hackquest",
];

const STATUS_FALLBACK = { dot: "bg-gray-500", label: "未知" };
const STATUS_CONFIG: Record<string, { dot: string; label: string }> = {
  upcoming: {
    dot: "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]",
    label: "即将开始",
  },
  running: {
    dot: "bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.5)] animate-pulse",
    label: "进行中",
  },
  recently_ended: {
    dot: "bg-red-500/70 shadow-[0_0_4px_rgba(239,68,68,0.35)]",
    label: "近期结束",
  },
};

const FORMAT_OPTIONS = ["Jeopardy", "Attack-Defense", "Hack quest"] as const;

const HIGH_WEIGHT_THRESHOLD = 25;

// ---------------------------------------------------------------------------
// 自定义下拉组件（暗色主题）
// ---------------------------------------------------------------------------

const SortDropdown: React.FC<{
  value: SortOption;
  onChange: (v: SortOption) => void;
}> = ({ value, onChange }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs
                   bg-white/5 border border-white/10 text-gray-300
                   hover:border-white/20 hover:bg-white/[0.07]
                   transition-colors outline-none"
      >
        <ArrowUpDown size={13} className="text-gray-500" />
        <span className="max-w-[140px] truncate">{SORT_LABELS[value]}</span>
        <ChevronDown
          size={12}
          className={`text-gray-500 transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div
          className="absolute top-full left-0 mt-1 w-52 rounded-lg border border-white/10
                     bg-dark-card shadow-xl shadow-black/40 z-50 py-1 overflow-hidden"
        >
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                opt === value
                  ? "text-accent-light bg-accent-primary/10"
                  : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
              }`}
            >
              {SORT_LABELS[opt]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

const CtfPage: React.FC = () => {
  // ---- 数据 ----
  const [events, setEvents] = useState<CtfEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  // ---- 刷新状态（v5 异步刷新）----
  const [refreshing, setRefreshing] = useState(false);
  const [refreshPhase, setRefreshPhase] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- 筛选 ----
  const [sort, setSort] = useState<SortOption>("default");
  const [onlyHighWeight, setOnlyHighWeight] = useState(false);
  const [formatFilters, setFormatFilters] = useState<Set<string>>(new Set());

  // ---- 大头钉 ----
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(new Set());
  const [pinLoading, setPinLoading] = useState<Set<string>>(new Set());

  // ---- 加载 ----
  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const formatParam =
        formatFilters.size > 0 ? Array.from(formatFilters).join(",") : undefined;
      const minWeight = onlyHighWeight ? HIGH_WEIGHT_THRESHOLD : undefined;

      const res = await ctfApi.getEvents({
        sort,
        format_filter: formatParam,
        min_weight: minWeight,
      });

      if (res.success) {
        setEvents(res.data);
        setLastRefresh(res.last_refresh);
      } else {
        setError(res.message || "加载失败");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [sort, onlyHighWeight, formatFilters]);

  const loadPins = useCallback(async () => {
    try {
      const res = await ctfApi.getPins();
      if (res.success) setPinnedIds(new Set(res.pinned_ids));
    } catch { /* 静默 */ }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadPins().then(() => loadEvents()); }, []);
  useEffect(() => { loadEvents(); }, [loadEvents]);

  // ---- 刷新 (v5: 异步模式，轮询进度) ----
  // 清理定时器
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleRefresh = async () => {
    setError("");
    setRefreshing(true);
    setRefreshPhase("正在启动刷新...");
    try {
      // 1) 触发异步刷新
      const res = await ctfApi.refresh();
      if (!res.success) {
        setError(res.message || "刷新启动失败");
        setRefreshing(false);
        setRefreshPhase("");
        return;
      }
      if (!res.refreshing) {
        // 已在运行中
        setRefreshPhase(res.message || "刷新进行中...");
      }

      // 2) 轮询进度
      pollRef.current = setInterval(async () => {
        try {
          const status = await ctfApi.refreshStatus();
          if (!status.refreshing) {
            // 完成
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setRefreshing(false);
            setRefreshPhase("");
            setError(status.message || "刷新完成");
            // 重新加载数据
            await loadPins();
            await loadEvents();
          } else {
            setRefreshPhase(status.phase || status.message || "刷新中...");
          }
        } catch {
          // 轮询失败不中断
        }
      }, 2000);
    } catch (e) {
      setError((e as Error).message);
      setRefreshing(false);
      setRefreshPhase("");
    }
  };

  // ---- 大头钉 ----
  const handleTogglePin = async (eventId: string) => {
    setPinLoading((prev) => new Set(prev).add(eventId));
    try {
      const res = await ctfApi.togglePin(eventId);
      if (res.success) setPinnedIds(new Set(res.pinned_ids));
    } catch { /* 静默 */ }
    finally {
      setPinLoading((prev) => {
        const next = new Set(prev);
        next.delete(eventId);
        return next;
      });
    }
  };

  // ---- 赛制过滤 ----
  const toggleFormatFilter = (fmt: string) => {
    setFormatFilters((prev) => {
      const next = new Set(prev);
      if (next.has(fmt)) next.delete(fmt);
      else next.add(fmt);
      return next;
    });
  };

  // ---- 时间格式化 ----
  const formatRefreshTime = () => {
    if (!lastRefresh) return null;
    try {
      const d = new Date(lastRefresh);
      return d.toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return lastRefresh;
    }
  };

  const refreshLabel = formatRefreshTime();
  const upcomingCount = events.filter((e) => e.status === "upcoming").length;
  const runningCount = events.filter((e) => e.status === "running").length;
  const endedCount = events.filter((e) => e.status === "recently_ended").length;

  // ======================== 渲染 ========================

  return (
    <div className="space-y-5">
      {/* ========== 头部 ========== */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">CTF 时间表</h2>
          <p className="text-xs text-gray-500 mt-1">
            数据来源: CTFtime.org
            {refreshLabel && (
              <span className="ml-2 text-gray-600">缓存于 {refreshLabel}</span>
            )}
          </p>
        </div>
        <button
          className="btn-primary text-sm"
          onClick={handleRefresh}
          disabled={loading || refreshing}
        >
          <RefreshCw size={14} className={`inline mr-1 ${loading || refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "刷新中..." : "刷新缓存"}
        </button>
      </div>

      {/* ========== 筛选栏 ========== */}
      <div className="card !p-3 !border-white/8">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {/* 自定义下拉排序 */}
          <SortDropdown value={sort} onChange={setSort} />

          <div className="w-px h-5 bg-white/10" />

          {/* 权重过滤 */}
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              className="accent-amber-500"
              checked={onlyHighWeight}
              onChange={() => setOnlyHighWeight((v) => !v)}
            />
            <Trophy size={13} className="text-amber-400" />
            <span className="text-xs text-gray-400">仅高权重 (≥{HIGH_WEIGHT_THRESHOLD})</span>
          </label>

          <div className="w-px h-5 bg-white/10" />

          {/* 赛制过滤 */}
          <span className="text-xs text-gray-500">赛制:</span>
          {FORMAT_OPTIONS.map((fmt) => {
            const active = formatFilters.has(fmt);
            const color = formatColors[fmt] || "text-gray-400 bg-gray-400/10";
            return (
              <button
                key={fmt}
                onClick={() => toggleFormatFilter(fmt)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  active
                    ? `${color} border-current/30`
                    : "text-gray-500 border-white/10 hover:text-gray-300"
                }`}
              >
                {fmt}
              </button>
            );
          })}

          {(onlyHighWeight || formatFilters.size > 0) && (
            <button
              className="text-xs text-gray-500 hover:text-gray-300 underline underline-offset-2"
              onClick={() => {
                setOnlyHighWeight(false);
                setFormatFilters(new Set());
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      </div>

      {/* ========== 状态统计条 ========== */}
      {events.length > 0 && (
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.4)]" />
            即将开始 {upcomingCount}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.4)] animate-pulse" />
            进行中 {runningCount}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-500/70 shadow-[0_0_4px_rgba(239,68,68,0.35)]" />
            近期结束 {endedCount}
          </span>
        </div>
      )}

      {/* ========== 刷新进度提示 ========== */}
      {refreshing && (
        <div className="card !p-3 !border-amber-500/30 text-amber-400 text-sm">
          <RefreshCw size={14} className="inline animate-spin mr-2" />
          {refreshPhase || "刷新中..."}
        </div>
      )}

      {/* ========== 错误 / 提示 ========== */}
      {error && (
        <div
          className={`card !p-3 text-sm ${
            error.startsWith("刷新完成")
              ? "!border-green-500/30 text-green-400"
              : "!border-red-500/30 text-red-400"
          }`}
        >
          {error}
        </div>
      )}

      {/* ========== 加载中 ========== */}
      {loading && events.length === 0 && (
        <div className="text-center text-gray-600 py-16">
          <RefreshCw size={24} className="animate-spin mx-auto mb-3" />
          正在加载赛事数据...
        </div>
      )}

      {/* ========== 空状态 ========== */}
      {!loading && events.length === 0 && !error && (
        <div className="text-center text-gray-600 py-16">
          暂无赛事数据，点击右上角"刷新缓存"获取最新列表
        </div>
      )}

      {/* ========== 赛事卡片 ========== */}
      {events.length > 0 && (
        <div className="space-y-2">
          {events.map((event) => {
            const isPinned = pinnedIds.has(event.id);
            const isPinBusy = pinLoading.has(event.id);
            const url = event.official_url || event.ctftime_url;
            const cfg = STATUS_CONFIG[event.status] || STATUS_FALLBACK;

            return (
              <div
                key={event.id}
                className={`card !p-3.5 hover:border-accent-primary/20 transition-colors group ${
                  isPinned ? "!border-amber-500/25 ring-1 ring-amber-500/10" : ""
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* ---- 大头钉 ---- */}
                  <button
                    className={`flex-shrink-0 mt-0.5 p-0.5 rounded transition-colors ${
                      isPinned
                        ? "text-amber-400 hover:text-amber-300"
                        : "text-gray-700 hover:text-amber-400 opacity-0 group-hover:opacity-100"
                    }`}
                    onClick={() => handleTogglePin(event.id)}
                    disabled={isPinBusy}
                    title={isPinned ? "取消关注" : "关注（置顶）"}
                  >
                    {isPinned ? <Pin size={15} /> : <PinOff size={15} />}
                  </button>

                  {/* ---- 主体 ---- */}
                  <div className="flex-1 min-w-0">
                    {/* 名称行: 状态灯 + 名称 + 链接 + 权重 + 奖杯 */}
                    <div className="flex items-center gap-2 mb-1.5">
                      {/* 状态灯 */}
                      <span
                        className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`}
                        title={cfg.label}
                      />

                      {url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-semibold text-white hover:text-accent-light transition-colors truncate flex items-center gap-1"
                          title={url}
                        >
                          {event.name}
                          <ExternalLink size={11} className="text-gray-600 flex-shrink-0" />
                        </a>
                      ) : (
                        <span className="text-sm font-semibold text-white truncate">
                          {event.name}
                        </span>
                      )}

                      {event.weight >= HIGH_WEIGHT_THRESHOLD && (
                        <Trophy size={13} className="text-amber-400 flex-shrink-0" title="高权重赛事" />
                      )}

                      {event.weight > 0 && (
                        <span className="text-xs text-amber-400 font-mono flex-shrink-0 ml-auto">
                          {event.weight.toFixed(2)}
                        </span>
                      )}
                    </div>

                    {/* 日期 */}
                    <div className="flex items-center gap-1 text-xs text-gray-500 mb-2">
                      <Clock size={11} />
                      <span>{event.date}</span>
                      <span className="text-gray-600 ml-1">· {cfg.label}</span>
                    </div>

                    {/* 标签行 */}
                    <div className="flex flex-wrap gap-1.5">
                      <span
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          formatColors[event.format] || "text-gray-400 bg-gray-400/10"
                        }`}
                      >
                        {event.format}
                      </span>

                      <span
                        className={`text-xs px-1.5 py-0.5 rounded flex items-center gap-1 ${
                          event.location === "On-line"
                            ? "text-green-400 bg-green-400/10"
                            : "text-blue-400 bg-blue-400/10"
                        }`}
                      >
                        {event.location === "On-line" ? <Globe size={10} /> : <MapPin size={10} />}
                        {event.location}
                      </span>

                      {event.notes && (
                        <span className="text-xs px-1.5 py-0.5 rounded text-gray-500 bg-gray-400/10 truncate max-w-[200px]">
                          {event.notes}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ========== 底部 ========== */}
      {events.length > 0 && (
        <div className="text-center text-xs text-gray-600 pt-2 space-x-3">
          <a
            href="https://ctftime.org/event/list/"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-accent-light transition-colors underline underline-offset-2"
          >
            在 CTFtime.org 查看完整列表
          </a>
          <span>·</span>
          <span>共 {events.length} 个赛事</span>
        </div>
      )}
    </div>
  );
};

export default CtfPage;
