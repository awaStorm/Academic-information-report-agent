import json
import os
from datetime import datetime

class DataProcessor:
    """超星通知数据处理类"""
    # 计算项目根目录 (src/processor 是二级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    RAW_CHAOXING = os.path.join(base_dir, "data", "raw", "data_raw_notice.json")
    OUTPUT_REFINED = os.path.join(base_dir, "data", "processed", "data_refined.json")
    
    @staticmethod
    def timestamp_to_str(ts):
        """超星的时间戳是 13 位（毫秒级），转换为易读格式"""
        return datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M')
    
    @staticmethod
    def extract_attachment_url(attachment_str):
        """解析嵌套在字符串里的附件 JSON，提取外链"""
        if not attachment_str or attachment_str == "":
            return None
        try:
            atts = json.loads(attachment_str)
            for att in atts:
                if "att_web" in att:
                    return att["att_web"].get("url")
        except:
            return None
        return None
    
    def process_single_notice(self, item):
        """处理单条超星通知，保留核心情报和状态"""
        ext_url = self.extract_attachment_url(item.get("attachment", ""))
        
        return {
            "source_platform": "chaoxing",
            "origin_name": item.get("createrName", "系统通知"),
            "title": item.get("title", "无标题"),
            "content": item.get("content", "").strip(),
            "external_link": ext_url,
            "is_read": item.get("isread", 1),
            "has_red_dot": item.get("redDot", 0),
            "date": self.timestamp_to_str(item.get("insertTime", 0)),
            "content_id": item.get("idCode") or item.get("uuid")
        }
    
    def run(self):
        """主执行流程"""
        os.makedirs(os.path.dirname(self.OUTPUT_REFINED), exist_ok=True)
        
        if not os.path.exists(self.RAW_CHAOXING):
            print(f"❌ 错误：找不到文件 {self.RAW_CHAOXING}")
            return {"success": False, "error_type": "NO_DATA", "message": f"找不到 {self.RAW_CHAOXING}"}
        
        with open(self.RAW_CHAOXING, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        
        notice_list = raw_data.get("notices", {}).get("list", [])
        print(f"📦 发现 {len(notice_list)} 条原始记录，开始情报提取...")
        
        refined_data = [self.process_single_notice(item) for item in notice_list]
        refined_data.sort(key=lambda x: x['date'], reverse=True)
        
        with open(self.OUTPUT_REFINED, "w", encoding="utf-8") as f:
            json.dump(refined_data, f, ensure_ascii=False, indent=4)
        
        print(f"✨ 清洗完成！标准情报已存入: {self.OUTPUT_REFINED}")
        
        unread_items = [i for i in refined_data if i['is_read'] == 0]
        if unread_items:
            print(f"🔔 发现 {len(unread_items)} 条未读情报：")
            for u in unread_items:
                print(f"   - [{u['date']}] {u['title']} (来自: {u['origin_name']})")
        else:
            print("✅ 暂时没有未读的新情报。")
        return {"success": True, "count": len(refined_data), "unread": len(unread_items)}

if __name__ == "__main__":
    processor = DataProcessor()
    processor.run()