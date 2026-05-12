import sqlite3
import hashlib
import json
from datetime import datetime
import os

class AgentMemory:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, "data", "memory.db")
        else:
            self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """初始化所有表"""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS intelligence_memory (
                hash_id TEXT PRIMARY KEY,
                title TEXT,
                platform TEXT,
                status TEXT,
                reason TEXT,
                created_at DATETIME
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pushed_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                platform TEXT,
                category TEXT,
                brief TEXT,
                link TEXT,
                status TEXT,
                push_time DATETIME
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                categories TEXT
            )
        ''')
        self.conn.commit()

    # ---- 情报去重 ----

    def get_hash(self, title, content):
        return hashlib.md5((title + str(content)).encode('utf-8')).hexdigest()

    def is_seen(self, hash_id):
        self.cursor.execute("SELECT 1 FROM intelligence_memory WHERE hash_id = ?", (hash_id,))
        return self.cursor.fetchone() is not None

    def save_memory(self, hash_id, title, platform, status, reason=""):
        self.cursor.execute('''
            INSERT OR REPLACE INTO intelligence_memory
            (hash_id, title, platform, status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (hash_id, title, platform, status, reason, datetime.now()))
        self.conn.commit()

    # ---- 推送记录 ----

    def save_pushed_record(self, title, platform, category="其他", brief="", link="", status="pushed"):
        """保存推送记录"""
        self.cursor.execute('''
            INSERT INTO pushed_records (title, platform, category, brief, link, status, push_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, platform, category, brief, link, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()

    def get_pushed_records_by_date_range(self, start_date, end_date, platform=None, limit=None):
        """按日期范围查询推送记录"""
        query = '''
            SELECT title, platform, category, brief, link, status, push_time
            FROM pushed_records
            WHERE push_time >= ? AND push_time <= ?
        '''
        params = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]

        if platform:
            query += " AND platform = ?"
            params.append(platform)

        query += " ORDER BY push_time DESC"

        if limit:
            query += f" LIMIT {int(limit)}"

        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows]

    # ---- 偏好管理 ----

    def get_categories(self):
        """获取用户偏好类别列表"""
        self.cursor.execute("SELECT categories FROM preferences WHERE id = 1")
        row = self.cursor.fetchone()
        if row and row['categories']:
            return json.loads(row['categories'])
        return []

    def save_categories(self, categories):
        """保存用户偏好类别"""
        data = json.dumps(categories, ensure_ascii=False)
        self.cursor.execute('''
            INSERT OR REPLACE INTO preferences (id, categories) VALUES (1, ?)
        ''', (data,))
        self.conn.commit()

    def close(self):
        self.conn.close()


# ---- 模块级便捷函数（供 app.py 直接调用）----

def get_preferences():
    """获取偏好设置"""
    db = AgentMemory()
    try:
        categories = db.get_categories()
        return {"success": True, "categories": categories}
    except Exception as e:
        return {"success": False, "categories": [], "message": str(e)}
    finally:
        db.close()

def update_preferences(selected_categories):
    """更新偏好设置"""
    db = AgentMemory()
    try:
        db.save_categories(selected_categories)
        return {"success": True, "categories": selected_categories}
    except Exception as e:
        return {"success": False, "categories": [], "message": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    db = AgentMemory()
    print(f"Database path: {db.db_path}")
    db.save_memory(db.get_hash("test", "content"), "test", "local", "pushed")
    print("Test record saved")

    # 测试推送记录
    db.save_pushed_record("测试推送", "wechat", "讲座活动", "这是一条测试", "https://example.com", "pushed")
    records = db.get_pushed_records_by_date_range("2020-01-01", "2030-12-31")
    print(f"Pushed records: {len(records)}")

    # 测试偏好
    db.save_categories(["讲座活动", "竞赛信息"])
    cats = db.get_categories()
    print(f"Categories: {cats}")

    db.close()
