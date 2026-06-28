import json
import os
import sys
import io

class FinalMerger:
    """多源情报合并类"""
    # 计算项目根目录 (src/processor/mergers 是三级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    CHAOXING_IN = os.path.join(base_dir, "data", "processed", "data_ready_for_ai.json")
    WECHAT_IN = os.path.join(base_dir, "data", "processed", "data_wechat_ready.json")
    FINAL_OUT = os.path.join(base_dir, "data", "processed", "full_intelligence_stream.json")
    
    def __init__(self):
        pass
    
    def merge_intelligence(self, progress_callback=None):
        """主合并逻辑"""
        all_news = []
        os.makedirs(os.path.dirname(self.FINAL_OUT), exist_ok=True)
        
        sources = [
            ("超星线", self.CHAOXING_IN),
            ("微信线", self.WECHAT_IN),
        ]
        
        for idx, (label, path) in enumerate(sources):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"📥 [{label}] 汇入情报: {len(data)} 条")
                    all_news.extend(data)
            else:
                print(f"⚠️ 未找到{label}数据")
            
            if progress_callback:
                try:
                    progress_callback(idx + 1, len(sources), f"已加载 {label} 数据")
                except Exception:
                    pass
        
        if not all_news:
            print("❌ 无可用情报，请检查前置采集脚本。")
            return {"success": False, "error_type": "NO_DATA", "message": "无可用情报"}
        
        # 3. 全局时间排序
        all_news.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        # 4. 保存
        with open(self.FINAL_OUT, "w", encoding="utf-8") as f:
            json.dump(all_news, f, ensure_ascii=False, indent=4)
        
        print(f"\n✨ 大合流完成！")
        print(f"📊 总情报量: {len(all_news)} 条")
        print(f"📂 汇总文件: {self.FINAL_OUT}")
        return {"success": True, "count": len(all_news)}

if __name__ == "__main__":
    merger = FinalMerger()
    merger.merge_intelligence()