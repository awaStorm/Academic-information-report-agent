"""
backend/ws/connection_manager.py - WebSocket 连接管理器
管理所有 WebSocket 连接，提供日志推送能力
"""
import json
import logging
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger("backend.ws")


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # session_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self._interrupt_flags: Dict[str, bool] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """建立 WebSocket 连接"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        self._interrupt_flags[session_id] = False
        logger.info(f"WebSocket 已连接: {session_id}，当前连接数: {self._connection_count()}")

    def disconnect(self, session_id: str, websocket: WebSocket = None):
        """断开 WebSocket 连接，移除指定连接或清理整个 session"""
        if session_id not in self.active_connections:
            return
        if websocket is not None:
            # 移除指定连接
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
                logger.info(f"WebSocket 连接已移除: {session_id}")
        # 如果该 session 下没有连接了，清理 key
        if not self.active_connections[session_id]:
            del self.active_connections[session_id]
            self._interrupt_flags.pop(session_id, None)
            logger.info(f"WebSocket session 已清理: {session_id}")

    def mark_interrupt(self, session_id: str):
        """标记中断信号"""
        self._interrupt_flags[session_id] = True

    def is_interrupted(self, session_id: str) -> bool:
        """检查是否收到中断信号"""
        return self._interrupt_flags.get(session_id, False)

    async def send_log(self, session_id: str, log_entry: Dict):
        """
        向指定 session 推送日志条目
        log_entry 格式: {"cls": "ok"|"err"|"tool"|"status"|"agent"|"user", "html": "..."}
        """
        if session_id not in self.active_connections:
            return
        connections = self.active_connections[session_id]
        # 构造 WebSocket 消息
        message = json.dumps({
            "type": "log",
            "data": log_entry,
        }, ensure_ascii=False)
        disconnected = []
        for conn in connections:
            try:
                await conn.send_json({"type": "log", "data": log_entry})
            except Exception as e:
                logger.warning(f"推送日志失败: {e}")
                disconnected.append(conn)
        # 清理断开的连接
        for conn in disconnected:
            if conn in connections:
                connections.remove(conn)

    async def send_status(self, session_id: str, status: str):
        """向指定 session 推送状态更新"""
        if session_id not in self.active_connections:
            return
        for conn in self.active_connections[session_id]:
            try:
                await conn.send_json({"type": "status", "data": {"status": status}})
            except Exception:
                pass

    def _connection_count(self) -> int:
        """统计总连接数"""
        return sum(len(conns) for conns in self.active_connections.values())


# 全局连接管理器实例
manager = ConnectionManager()
