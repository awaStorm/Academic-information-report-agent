/**
 * frontend/src/components/common/DegradeNotice.tsx - 信源降级说明对话框
 * 两轮生成均未命中主题时，如实向用户说明原因与兜底信源，仅供说明、无需填写。
 */
import React from "react";
import { X, Info, SearchX, Sparkles } from "lucide-react";

interface Props {
  note: string;
  keywords?: string[];
  rounds?: Array<{ round: number; count: number; pass: boolean; detail: string }>;
  onClose: () => void;
}

const DegradeNotice: React.FC<Props> = ({ note, keywords = [], rounds = [], onClose }) => {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-overlay-in" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-amber-500/25 bg-[#13131F] p-5 shadow-2xl animate-modal-in"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <SearchX size={20} className="text-amber-400" />
            <h3 className="text-lg font-bold text-white">信源发现说明</h3>
          </div>
          <button className="text-gray-500 hover:text-gray-300" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </div>

        <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/[0.05] p-3.5">
          <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">{note}</p>
        </div>

        {keywords.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-gray-500 mb-1.5">已按以下主题关键词检索：</p>
            <div className="flex flex-wrap gap-1.5">
              {keywords.map((k, i) => (
                <span key={i} className="text-[11px] px-2 py-0.5 rounded bg-violet-500/10 text-violet-300">{k}</span>
              ))}
            </div>
          </div>
        )}

        {rounds.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-gray-500 mb-1.5">生成过程：</p>
            <ul className="space-y-1 text-xs text-gray-400">
              {rounds.map((r) => (
                <li key={r.round} className="flex items-start gap-1.5">
                  <span className={r.pass ? "text-green-400" : "text-amber-400"}>第 {r.round} 轮：</span>
                  <span>{r.detail}（落地 {r.count} 张）</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mt-4 text-xs text-gray-500 flex items-start gap-1.5">
          <Info size={13} className="flex-shrink-0 mt-0.5" />
          以上为本次降级生成的说明。已为你提供最接近的官方信源卡片，可在仓库中核对样例、编辑配置后再加入检查清单。
        </p>

        <div className="mt-4 flex justify-end">
          <button className="btn-primary text-sm px-4 flex items-center gap-2" onClick={onClose}>
            <Sparkles size={14} /> 知道了
          </button>
        </div>
      </div>
    </div>
  );
};

export default DegradeNotice;
