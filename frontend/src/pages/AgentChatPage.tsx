/**
 * frontend/src/pages/AgentChatPage.tsx - Agent 对话页面（终端风格）
 *
 * WebSocket 由应用级管理器（api/websocket.ts）持有：
 * - 换页不断开、断线自动重连（此前绑定在组件上，换页即断）
 * - 日志缓冲在管理器中，换页返回后自动回放
 * - 本组件卸载时只取消订阅，绝不关闭连接
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { Send, RotateCcw } from "lucide-react";
import api from "../api/client";
import { wsManager, type LogEntry } from "../api/websocket";

const AgentChatPage: React.FC = () => {
  const [input, setInput] = useState("");
  const [logs, setLogs] = useState<LogEntry[]>(() => wsManager.getBuffer());
  const [connected, setConnected] = useState(wsManager.isConnected);
  const sessionId = wsManager.getSessionId();
  const terminalRef = useRef<HTMLDivElement>(null);

  // 订阅全局 WS：新日志 / 连接状态（幂等连接，已连接时跳过）
  useEffect(() => {
    wsManager.connect(sessionId);
    const offLog = wsManager.onLog((entry) => setLogs((prev) => [...prev, entry]));
    const offConn = wsManager.onConnectionChange(setConnected);
    setConnected(wsManager.isConnected);
    return () => {
      offLog();
      offConn();
    };
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
    const text = input;
    setInput("");
    appendLog("user", `👤 [${new Date().toLocaleTimeString()}] ${text}`);
    // 通过 REST API 发送（LLM 任务可达数分钟，延长超时避免前端中断），
    // WebSocket 仍是实时日志主通道
    api.post<{ success: boolean; response?: string; message?: string }>(
      "/api/v1/agents/xidian/chat",
      null,
      { params: { user_input: text, session_id: sessionId }, timeout: 600000 }
    )
      .then((data) => {
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
  }, [input, connected, sessionId]);

  const resetChat = () => {
    setLogs([]);
    wsManager.clearBuffer(sessionId);
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
