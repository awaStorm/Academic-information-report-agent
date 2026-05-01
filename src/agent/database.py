import sqlite3
import hashlib
from datetime import datetime
import os

class AgentMemory:
    def __init__(self, db_path=None):
        # 如果不传路径，则自动计算基于项目根目录的路径
        if db_path is None:
            # 方案：获取当前文件所在目录的父目录的父目录（即 src/agent/ 的上两级）
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, "data", "memory.db")
        else:
            self.db_path = db_path
        # 建立连接，SQLite 在本地就是一个文件
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        """初始化情报记忆表"""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS intelligence_memory (
                hash_id TEXT PRIMARY KEY,   -- 根据标题和内容生成的唯一ID
                title TEXT,
                platform TEXT,
                status TEXT,               -- 'pushed' (已推送) 或 'filtered' (已过滤)
                reason TEXT,               -- AI 给出的理由
                created_at DATETIME
            )
        ''')
        self.conn.commit()

    def get_hash(self, title, content):
        """生成情报的唯一指纹"""
        return hashlib.md5((title + str(content)).encode('utf-8')).hexdigest()

    def is_seen(self, hash_id):
        """检查这条情报是否已经处理过"""
        self.cursor.execute("SELECT 1 FROM intelligence_memory WHERE hash_id = ?", (hash_id,))
        return self.cursor.fetchone() is not None

    def save_memory(self, hash_id, title, platform, status, reason=""):
        """保存处理结果到记忆"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO intelligence_memory 
            (hash_id, title, platform, status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (hash_id, title, platform, status, reason, datetime.now()))
        self.conn.commit()

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    db = AgentMemory()
    print(f"Database path: {db.db_path}")
    # 测试数据库操作
    db.save_memory(db.get_hash("test", "content"), "test", "local", "pushed")
    print("Test record saved")

