"""
backend/ws/connection_manager.py - WebSocket 连接管理器
管理所有 WebSocket 连接，提供日志推送能力。

2026-11-21：新增按 session 的日志历史缓存（带序号），断线期间日志不再丢弃，
重连时回放；配合前端心跳做可靠日志流。
"""
import json
import logging
import time
from collections import deque
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger("backend.ws")

MAX_HISTORY = 500


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # session_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self._interrupt_flags: Dict[str, bool] = {}
        # session_id -> deque[ {"seq":int, "entry":dict} ]：断线期间的日志也缓存，供重连回放
        self._history: Dict[str, deque] = {}
        self._seq: Dict[str, int] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> int:
        """建立连接，返回当前 session 最新日志序号（前端据此去重回放）"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        self._interrupt_flags[session_id] = False
        # 回放历史日志（断线期间攒下的），带 seq 供前端去重
        history = list(self._history.get(session_id, []))
        if history:
            try:
                await websocket.send_json({"type": "replay", "logs": [h["entry"] for h in history]})
                logger.info(f"回放 {len(history)} 条历史日志给 {session_id}")
            except Exception as e:
                logger.warning(f"回放历史日志失败: {e}")
        logger.info(f"WebSocket 已连接: {session_id}，当前连接数: {self._connection_count()}")
        return self._seq.get(session_id, 0)

    def disconnect(self, session_id: str, websocket: WebSocket = None):
        """断开 WebSocket 连接，移除指定连接或清理整个 session（历史日志保留用于回放）"""
        if session_id not in self.active_connections:
            return
        if websocket is not None:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
                logger.info(f"WebSocket 连接已移除: {session_id}")
        if not self.active_connections[session_id]:
            del self.active_connections[session_id]
            self._interrupt_flags.pop(session_id, None)
            logger.info(f"WebSocket session 已清理: {session_id}（历史日志保留）")

    def mark_interrupt(self, session_id: str):
        self._interrupt_flags[session_id] = True

    def is_interrupted(self, session_id: str) -> bool:
        return self._interrupt_flags.get(session_id, False)

    def clear_history(self, session_id: str):
        """重置终端时清空该 session 的历史缓存"""
        self._history.pop(session_id, None)
        self._seq.pop(session_id, None)

    async def send_log(self, session_id: str, log_entry: Dict):
        """
        推送日志：先缓存（含断线期间），再发给当前所有连接。
        log_entry 会附带递增 seq，前端据此去重，避免回放重复展示。
        """
        seq = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = seq
        stored = {**log_entry, "seq": seq, "ts": time.time()}
        buf = self._history.setdefault(session_id, deque(maxlen=MAX_HISTORY))
        buf.append({"seq": seq, "entry": stored})

        if session_id not in self.active_connections:
            return  # 无连接也已完成缓存，重连时回放
        connections = list(self.active_connections[session_id])
        disconnected = []
        for conn in connections:
            try:
                await conn.send_json({"type": "log", "data": stored})
            except Exception as e:
                logger.warning(f"推送日志失败: {e}")
                disconnected.append(conn)
        for conn in disconnected:
            if conn in self.active_connections.get(session_id, []):
                self.active_connections[session_id].remove(conn)

    async def send_status(self, session_id: str, status: str):
        if session_id not in self.active_connections:
            return
        for conn in list(self.active_connections[session_id]):
            try:
                await conn.send_json({"type": "status", "data": {"status": status}})
            except Exception:
                pass

    def _connection_count(self) -> int:
        return sum(len(conns) for conns in self.active_connections.values())


# 全局连接管理器实例
manager = ConnectionManager()
