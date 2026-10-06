/**
 * frontend/src/api/websocket.ts - 应用级 WebSocket 管理器
 *
 * 此前 WS 连接绑定在 AgentChatPage 组件上：换页即断开、sessionId 每次挂载重新生成、
 * 无重连逻辑，导致「换个页面日志流就没了」。现在改为应用级单例：
 * - 生命周期与应用一致（main.tsx 启动时连接），切换页面不断开
 * - 断线自动重连（指数退避 1s→2s→4s…上限 30s）
 * - 按 sessionId 缓冲最近 500 条日志，换页返回后仍可完整回看
 * - sessionId 持久化到 sessionStorage：同标签页内保持不变，关闭标签页才失效
 */
import { BASE_URL } from "./client";

export interface LogEntry {
  cls: string;
  html: string;
}

type LogListener = (entry: LogEntry) => void;
type ConnListener = (connected: boolean) => void;

const MAX_BUFFER = 500;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const SESSION_KEY = "agent_session_id";

function resolveWsUrl(): string {
  const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
  if (envUrl) return envUrl;
  // 由 REST baseUrl 推导：http://localhost:8138 -> ws://localhost:8138/ws/logs
  return `${BASE_URL.replace(/^http/, "ws")}/ws/logs`;
}

class WebSocketManager {
  private ws: WebSocket | null = null;
  private sessionId = "";
  private url = resolveWsUrl();
  private buffers = new Map<string, LogEntry[]>();
  private logListeners = new Set<LogListener>();
  private connListeners = new Set<ConnListener>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;

  /** 获取（或创建）本标签页的会话 ID：换页保持，关闭标签页才失效 */
  getSessionId(): string {
    let sid = sessionStorage.getItem(SESSION_KEY);
    if (!sid) {
      sid = `session_${Date.now()}`;
      sessionStorage.setItem(SESSION_KEY, sid);
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
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "log" && msg.data) {
          this.appendLog(this.sessionId, msg.data as LogEntry);
        }
      } catch {
        // 忽略非 JSON 消息
      }
    };

    ws.onerror = () => {
      // onclose 会随后触发，重连统一在 onclose 处理
    };

    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.notifyConn(false);
      if (!this.closedByUs) this.scheduleReconnect();
    };
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
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.notifyConn(false);
  }

  get isConnected(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /** 读取指定会话的日志缓冲（换页回来时回放） */
  getBuffer(sessionId: string = this.sessionId): LogEntry[] {
    return [...(this.buffers.get(sessionId) ?? [])];
  }

  /** 清空指定会话的日志缓冲（终端重置按钮用） */
  clearBuffer(sessionId: string = this.sessionId): void {
    this.buffers.delete(sessionId);
  }

  /** 订阅新日志，返回取消订阅函数 */
  onLog(listener: LogListener): () => void {
    this.logListeners.add(listener);
    return () => this.logListeners.delete(listener);
  }

  /** 订阅连接状态变化，返回取消订阅函数 */
  onConnectionChange(listener: ConnListener): () => void {
    this.connListeners.add(listener);
    return () => this.connListeners.delete(listener);
  }

  private appendLog(sessionId: string, entry: LogEntry) {
    let buf = this.buffers.get(sessionId);
    if (!buf) {
      buf = [];
      this.buffers.set(sessionId, buf);
    }
    buf.push(entry);
    if (buf.length > MAX_BUFFER) buf.shift();
    this.logListeners.forEach((fn) => fn(entry));
  }

  private notifyConn(connected: boolean) {
    this.connListeners.forEach((fn) => fn(connected));
  }
}

export const wsManager = new WebSocketManager();
