/**
 * frontend/src/components/common/Toast.tsx - 全局轻提示公共组件
 * 通过 toast.success/error/warning/info 从任意模块触发，无需 context 透传。
 */
import React, { useEffect, useState } from "react";
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from "lucide-react";

type ToastKind = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  leaving?: boolean;
}

type Listener = (item: ToastItem) => void;
const listeners = new Set<Listener>();
let seq = 0;

function emit(kind: ToastKind, message: string) {
  const item: ToastItem = { id: ++seq, kind, message };
  listeners.forEach((fn) => fn(item));
}

export const toast = {
  success: (msg: string) => emit("success", msg),
  error: (msg: string) => emit("error", msg),
  warning: (msg: string) => emit("warning", msg),
  info: (msg: string) => emit("info", msg),
};

const STYLE: Record<ToastKind, { border: string; icon: React.ReactNode }> = {
  success: { border: "border-green-500/40", icon: <CheckCircle2 size={16} className="text-green-400" /> },
  error: { border: "border-red-500/40", icon: <XCircle size={16} className="text-red-400" /> },
  warning: { border: "border-amber-500/40", icon: <AlertTriangle size={16} className="text-amber-400" /> },
  info: { border: "border-violet-500/40", icon: <Info size={16} className="text-accent-light" /> },
};

export const ToastContainer: React.FC = () => {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const listener: Listener = (item) => {
      setItems((prev) => [...prev, item]);
      // 先标记离场播放淡出，再真正移除，避免 4s 到点瞬间消失
      window.setTimeout(() => setItems((prev) => prev.map((t) => t.id === item.id ? { ...t, leaving: true } : t)), 4000);
      window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== item.id)), 4300);
    };
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[min(92vw,360px)]">
      {items.map((item) => (
        <div
          key={item.id}
          className={`flex items-start gap-2.5 px-3.5 py-3 rounded-lg bg-[#1E1E2E]/95 backdrop-blur border ${STYLE[item.kind].border} shadow-xl shadow-black/30 ${
            item.leaving ? "animate-[toastOut_.3s_ease-in_forwards]" : "animate-[toastIn_.2s_ease-out]"
          }`}
        >
          <span className="mt-0.5 flex-shrink-0">{STYLE[item.kind].icon}</span>
          <span className="text-sm text-gray-200 leading-relaxed flex-1 break-words">{item.message}</span>
          <button
            aria-label="关闭提示"
            className="text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0"
            onClick={() => setItems((prev) => prev.filter((t) => t.id !== item.id))}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
};

export default ToastContainer;
