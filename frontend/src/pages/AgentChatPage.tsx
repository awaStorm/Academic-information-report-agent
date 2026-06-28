/**
 * frontend/src/pages/AgentChatPage.tsx - Agent 对话页面（终端风格）
 * 支持 WebSocket 实时日志流
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { Send, RotateCcw } from "lucide-react";

interface LogEntry {
  cls: string;
  html: string;
}

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8138/ws/logs";

const AgentChatPage: React.FC = () => {
  const [input, setInput] = useState("");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [sessionId] = useState(() => `session_${Date.now()}`);
  const terminalRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // 连接 WebSocket
  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}?session_id=${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      appendLog("status", `🔌 已连接到后端 [${new Date().toLocaleTimeString()}]`);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "log" && msg.data) {
          appendLog(msg.data.cls, msg.data.html);
        }
      } catch (e) {
        console.error("WebSocket 消息解析失败:", e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      appendLog("warn", "🔌 连接已断开");
    };

    ws.onerror = () => {
      appendLog("err", "❌ WebSocket 连接错误");
    };

    return () => { ws.close(); };
  }, [sessionId]);

  // 自动滚动到底部
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  const appendLog = (cls: string, html: string) => {
    setLogs(prev => [...prev, { cls, html }]);
  };

  const sendMessage = useCallback(() => {
    if (!input.trim() || !connected) return;
    appendLog("user", `👤 [${new Date().toLocaleTimeString()}] ${input}`);
    // 通过 REST API 发送，WebSocket 是主要的响应通道
    fetch(`http://localhost:8138/api/v1/agents/xidian/chat?user_input=${encodeURIComponent(input)}&session_id=${sessionId}`, {
      method: "POST",
    })
      .then(async (res) => {
        const data = await res.json();
        // 降级：如果 WebSocket 日志未到达，直接用 REST 响应展示
        if (data.success && data.response) {
          // 用短延迟确保 WebSocket 消息先到达；如果 1s 后还没收到，则降级展示
          setTimeout(() => {
            setLogs(prev => {
              const hasAgentReply = prev.some(l => l.cls === "agent");
              if (!hasAgentReply) {
                return [...prev, { cls: "agent", html: `🤖 ${data.response}` }];
              }
              return prev;
            });
          }, 1000);
        }
        if (!data.success) {
          appendLog("err", `❌ ${data.message || "请求失败"}`);
        }
      })
      .catch(e => appendLog("err", `❌ 发送失败: ${e.message}`));
    setInput("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, connected, sessionId]);

  const resetChat = () => {
    setLogs([]);
    appendLog("status", `🔄 终端已重置 [${new Date().toLocaleTimeString()}]`);
  };

  const clsColors: Record<string, string> = {
    user: "text-accent-light",
    agent: "text-blue-400",
    status: "text-gray-500",
    ok: "text-green-400",
    err: "text-red-400",
    warn: "text-amber-400",
    tool: "text-cyan-400",
    token: "text-purple-400",
  };

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Agent 对话</h2>
          <p className="text-sm text-gray-500 mt-1">与 AI Agent 对话，自主执行采集、分析、推送</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-xs text-gray-500">{connected ? "已连接" : "未连接"}</span>
        </div>
      </div>

      {/* 终端输出区 */}
      <div
        ref={terminalRef}
        className="bg-[#0c0c14] border border-white/10 rounded-xl p-4 font-mono text-sm leading-relaxed min-h-[400px] max-h-[500px] overflow-y-auto"
      >
        {logs.length === 0 ? (
          <div className="text-gray-600">等待输入指令...</div>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} className={`${clsColors[log.cls] || "text-gray-400"} mb-0.5`}
              dangerouslySetInnerHTML={{ __html: log.html }} />
          ))
        )}
        <span className="inline-block w-2 h-4 bg-blue-400 animate-pulse ml-1" />
      </div>

      {/* 输入栏 */}
      <div className="flex gap-2">
        <input
          type="text"
          className="input-field flex-1"
          placeholder="输入指令，如：帮我采集今天的情报..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
        />
        <button className="btn-primary px-4" onClick={sendMessage} disabled={!connected}>
          <Send size={16} />
        </button>
        <button className="btn-secondary px-4" onClick={resetChat}>
          <RotateCcw size={16} />
        </button>
      </div>
    </div>
  );
};

export default AgentChatPage;
