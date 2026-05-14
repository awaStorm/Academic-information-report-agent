import json
import os

class ContentExtractor:
    """统一内容处理类"""
    # 计算项目根目录的路径 (src/processor/extractors 是三级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径
    INPUT_FILE = os.path.join(base_dir, "data", "processed", "data_refined.json")
    OUTPUT_FILE = os.path.join(base_dir, "data", "processed", "data_ready_for_ai.json")
    
    def __init__(self):
        """初始化配置"""
        pass
    
    def clean_and_refine(self):
        """精炼数据字段并清洗内容"""
        if not os.path.exists(self.INPUT_FILE):
            print(f"❌ 未找到输入文件: {self.INPUT_FILE}")
            return {"success": False, "error_type": "NO_DATA", "message": f"找不到 {self.INPUT_FILE}"}
        
        with open(self.INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        print(f"🧹 正在进行数据字段精炼...")
        refined_data = []
        
        for item in data:
            # 1. 字段重命名与合并 (核心逻辑)
            # 优先取 content，如果之前处理过则取 body，都没有就空字符串
            raw_text = item.get("content") or item.get("body") or ""
            
            # 2. 构建精简版对象
            # 只保留 AI 总结日报所必须的字段，其他的全部扔掉
            refined_item = {
                "id": item.get("content_id") or item.get("id"),
                "platform": item.get("source_platform", "unknown"),
                "author": item.get("origin_name", "未知"),
                "title": item.get("title", "").strip(),
                "date": item.get("date", ""),
                "body": raw_text.strip(),
                "link": item.get("external_link") # 仅保留链接，不抓取内容
            }
            
            # 3. 简单的内部文本清洗（不联网）
            # 比如去掉过多的换行符，让 AI 读起来更顺
            refined_item["body"] = "\n".join([line.strip() for line in refined_item["body"].split('\n') if line.strip()])
            
            refined_data.append(refined_item)
        
        # 保存结果
        os.makedirs(os.path.dirname(self.OUTPUT_FILE), exist_ok=True)
        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(refined_data, f, ensure_ascii=False, indent=4)
        
        print(f"✨ 精炼完成！")
        print(f"📂 已生成 AI 就绪文件: {self.OUTPUT_FILE}")
        print(f"📝 原始字段已优化：content -> body, content_id -> id")
        return {"success": True, "count": len(refined_data)}
    
if __name__ == "__main__":
    # 实例化处理器并执行
    extractor = ContentExtractor()
    extractor.clean_and_refine()