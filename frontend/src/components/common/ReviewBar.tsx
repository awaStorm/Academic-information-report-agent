/**
 * frontend/src/components/common/ReviewBar.tsx - LLM 相关性评审条
 * 生成后展示 LLM 的达标判定与理由（理由由 LLM 语义给出，非脚本关键词匹配），
 * 并提供「补充说明再来一轮」入口，把用户补充与上一轮评审意见一起交给 Agent 改进。
 */
import React, { useState } from "react";
import { Sparkles, CheckCircle2, AlertTriangle, RotateCcw, Info } from "lucide-react";
import type { Verdict } from "../../api/sourceCards";

interface Props {
  verdict: Verdict;
  rounds?: Array<{ round: number; count: number; pass: boolean; detail: string }>;
  onRetry: (followup: string) => void;
  retrying?: boolean;
}

const ReviewBar: React.FC<Props> = ({ verdict, rounds = [], onRetry, retrying = false }) => {
  const [followup, setFollowup] = useState("");

  const submit = () => {
    const text = followup.trim();
    if (!text || retrying) return;
    onRetry(text);
    setFollowup("");
  };

  return (
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.04] p-3.5 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-accent-light" />
          <span className="text-sm font-semibold text-gray-200">AI 相关性评审</span>
          {rounds.length > 1 && (
            <span className="text-[11px] text-gray-500">第 {rounds.length} 轮聚焦后</span>
          )}
        </div>
        <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${
          verdict.pass
            ? "text-green-400 border-green-500/30 bg-green-500/[0.07]"
            : "text-amber-400 border-amber-500/30 bg-amber-500/[0.07]"
        }`}>
          {verdict.pass ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
          {verdict.pass ? "达标" : "未达标"}
        </span>
      </div>

      <p className="text-[13px] text-gray-300 leading-relaxed flex items-start gap-1.5">
        <Info size={13} className="text-gray-500 flex-shrink-0 mt-0.5" />
        {verdict.reason}
      </p>

      {!verdict.pass && verdict.feedback && (
        <p className="text-[12px] text-amber-300/80 leading-relaxed pl-5">
          改进方向：{verdict.feedback}
        </p>
      )}

      <div className="flex gap-2 pt-0.5">
        <input
          className="input-field flex-1 text-[13px]"
          placeholder="不满意？补充需求（如：再聚焦美亚杯官方通知页），让 Agent 下一轮做得更好"
          value={followup}
          onChange={(e) => setFollowup(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !retrying) submit(); }}
          disabled={retrying}
        />
        <button
          className="btn-secondary px-3 whitespace-nowrap flex items-center gap-1.5 text-[13px]"
          onClick={submit}
          disabled={retrying || !followup.trim()}
        >
          <RotateCcw size={14} className={retrying ? "animate-spin" : ""} />
          {retrying ? "重试中..." : "再来一轮"}
        </button>
      </div>
    </div>
  );
};

export default ReviewBar;
