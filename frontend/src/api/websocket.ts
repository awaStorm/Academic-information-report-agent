/**
 * frontend/src/api/websocket.ts - 应用级 WebSocket 管理器
 *
 * 生命周期与应用一致（main.tsx 启动时连接），切换页面不断开。
 * 2026-11-21 可靠性改造：
 * - session id 持久化到 localStorage：关闭/回收标签页后仍保持同一会话
 * - 应用层心跳 ping/pong + 超时判定，检测后台导致的半开连接
 * - visibilitychange 切回前台：失联则立即重连，不受后台退避节流影响
 * - 后端按 session 缓存日志并回放；本管理器按 seq 去重，断线期间的日志不丢、不重
 * - 管理器是日志数据的唯一来源，组件订阅 buffer 变化，重连回放天然不重复展示
 */
import { BASE_URL } from "./client";

export interface LogEntry {
  cls: string;
  html: string;
  seq?: number;
}

type LogListener = (entry: LogEntry) => void;
type BufferListener = () => void;
type ConnListener = (connected: boolean) => void;

const MAX_BUFFER = 500;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_INTERVAL_MS = 20000;
const HEARTBEAT_TIMEOUT_MS = 8000;
const SESSION_KEY = "agent_session_id";

function resolveWsUrl(): string {
  const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
  if (envUrl) return envUrl;
  return `${BASE_URL.replace(/^http/, "ws")}/ws/logs`;
}

class WebSocketManager {
  private ws: WebSocket | null = null;
  private sessionId = "";
  private url = resolveWsUrl();
  private buffers = new Map<string, LogEntry[]>();
  private maxSeq = new Map<string, number>();
  private logListeners = new Set<LogListener>();
  private bufferListeners = new Set<BufferListener>();
  private connListeners = new Set<ConnListener>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;
  private onVisibility: (() => void) | null = null;

  /** 会话 ID：localStorage 持久化，关标签页/回收后仍保持 */
  getSessionId(): string {
    let sid = localStorage.getItem(SESSION_KEY);
    if (!sid) {
      // 从旧的 sessionStorage 迁移，避免升级后丢会话
      sid = sessionStorage.getItem(SESSION_KEY) || `session_${Date.now()}`;
      localStorage.setItem(SESSION_KEY, sid);
      sessionStorage.removeItem(SESSION_KEY);
    }
    return sid;
  }

  /** 幂等连接：已连接且会话一致时直接返回 */
  connect(sessionId?: string): void {
    const sid = sessionId ?? this.getSessionId();
    if (this.ws && this.sessionId === sid
        && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    if (this.ws) {
      this.closedByUs = true;
      this.ws.close();
      this.ws = null;
    }
    this.sessionId = sid;
    this.closedByUs = false;
    this.open();
    this.installVisibilityHandler();
  }

  private open() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    let ws: WebSocket;
    try {
      ws = new WebSocket(`${this.url}?session_id=${encodeURIComponent(this.sessionId)}`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.notifyConn(true);
      this.startHeartbeat();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "pong") {
          this.clearPongTimer();
        } else if (msg.type === "log" && msg.data) {
          this.receiveEntries([msg.data as LogEntry]);
        } else if (msg.type === "replay" && Array.isArray(msg.logs)) {
          // 后端回放断线期间缓存的日志，按 seq 去重后并入 buffer
          this.receiveEntries(msg.logs as LogEntry[]);
        }
      } catch {
        // 忽略非 JSON 消息
      }
    };

    ws.onerror = () => {
      // onclose 会随后触发；若一直不触发，心跳超时会主动 close
      this.clearPongTimer();
    };

    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.stopHeartbeat();
      this.notifyConn(false);
      if (!this.closedByUs) this.scheduleReconnect();
    };
  }

  private receiveEntries(entries: LogEntry[]) {
    let changed = false;
    for (const entry of entries) {
      // seq 去重：回放/重发的历史日志不重复展示
      if (entry.seq != null) {
        const last = this.maxSeq.get(this.sessionId) ?? 0;
        if (entry.seq <= last) continue;
        this.maxSeq.set(this.sessionId, entry.seq);
      }
      this.pushRaw(this.sessionId, entry);
      this.logListeners.forEach((fn) => fn(entry));
      changed = true;
    }
    if (changed) this.notifyBuffer();
  }

  private pushRaw(sessionId: string, entry: LogEntry) {
    let buf = this.buffers.get(sessionId);
    if (!buf) { buf = []; this.buffers.set(sessionId, buf); }
    buf.push(entry);
    if (buf.length > MAX_BUFFER) buf.shift();
  }

  /** 本地追加（如用户消息/终端重置提示），不走 WS、无 seq */
  appendLocal(entry: LogEntry, sessionId: string = this.sessionId) {
    this.pushRaw(sessionId, entry);
    this.logListeners.forEach((fn) => fn(entry));
    this.notifyBuffer();
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;
      try { this.ws.send(JSON.stringify({ type: "ping", ts: Date.now() })); } catch { return; }
      // 每当发出 ping 就设一个 pong 超时；收到 pong 会清掉，累计超时则判定半开连接
      if (this.pongTimer) clearTimeout(this.pongTimer);
      this.pongTimer = setTimeout(() => {
        loggerWarn("心跳超时，主动断开以触发重连");
        this.ws?.close(); // onclose 里 closedByUs=false，会自动重连
      }, HEARTBEAT_TIMEOUT_MS);
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null; }
    this.clearPongTimer();
  }

  private clearPongTimer() {
    if (this.pongTimer) { clearTimeout(this.pongTimer); this.pongTimer = null; }
  }

  /** 页面切回前台：连接失联则立即重连，不等待被后台节流的定时器 */
  private installVisibilityHandler() {
    if (this.onVisibility) return;
    this.onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      if (!this.isConnected && !this.closedByUs) {
        this.reconnectAttempts = 0;
        if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
        this.open();
      } else if (this.isConnected) {
        // 连接可能已半开（后台期间无 pong），主动 ping 探活
        try { this.ws?.send(JSON.stringify({ type: "ping", ts: Date.now() })); } catch { /* ignore */ }
      }
    };
    document.addEventListener("visibilitychange", this.onVisibility);
  }

  private scheduleReconnect() {
    if (this.reconnectTimer || this.closedByUs) return;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.reconnectAttempts, RECONNECT_MAX_MS);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closedByUs) this.open();
    }, delay);
  }

  /** 手动断开（应用卸载时） */
  disconnect(): void {
    this.closedByUs = true;
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    this.stopHeartbeat();
    if (this.onVisibility) {
      document.removeEventListener("visibilitychange", this.onVisibility);
      this.onVisibility = null;
    }
    this.ws?.close();
    this.ws = null;
    this.notifyConn(false);
  }

  get isConnected(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /** 读取指定会话的日志缓冲（组件渲染的唯一数据源） */
  getBuffer(sessionId: string = this.sessionId): LogEntry[] {
    return [...(this.buffers.get(sessionId) ?? [])];
  }

  /** 清空日志缓冲，并通知后端清历史（终端重置） */
  clearBuffer(sessionId: string = this.sessionId): void {
    this.buffers.delete(sessionId);
    this.maxSeq.delete(sessionId);
    if (this.ws?.readyState === WebSocket.OPEN) {
      try { this.ws.send(JSON.stringify({ type: "clear_history" })); } catch { /* ignore */ }
    }
    this.notifyBuffer();
  }

  onLog(listener: LogListener): () => void {
    this.logListeners.add(listener);
    return () => this.logListeners.delete(listener);
  }

  /** 订阅 buffer 整体变化（重连回放后全量刷新用） */
  onBufferChange(listener: BufferListener): () => void {
    this.bufferListeners.add(listener);
    return () => this.bufferListeners.delete(listener);
  }

  onConnectionChange(listener: ConnListener): () => void {
    this.connListeners.add(listener);
    return () => this.connListeners.delete(listener);
  }

  private notifyBuffer() {
    this.bufferListeners.forEach((fn) => fn());
  }

  private notifyConn(connected: boolean) {
    this.connListeners.forEach((fn) => fn(connected));
  }
}

function loggerWarn(msg: string) {
  console.warn(`[WS] ${msg}`);
}

export const wsManager = new WebSocketManager();
