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
    
    def merge_intelligence(self):
        """主合并逻辑"""
        all_news = []
        os.makedirs(os.path.dirname(self.FINAL_OUT), exist_ok=True)
        
        # 1. 加载超星线数据
        if os.path.exists(self.CHAOXING_IN):
            with open(self.CHAOXING_IN, "r", encoding="utf-8") as f:
                cx_data = json.load(f)
                print(f"📥 [超星线] 汇入情报: {len(cx_data)} 条")
                all_news.extend(cx_data)
        else:
            print("⚠️ 未找到超星线数据")
        
        # 2. 加载微信线数据
        if os.path.exists(self.WECHAT_IN):
            with open(self.WECHAT_IN, "r", encoding="utf-8") as f:
                wx_data = json.load(f)
                print(f"📥 [微信线] 汇入情报: {len(wx_data)} 条")
                all_news.extend(wx_data)
        else:
            print("⚠️ 未找到微信线数据")
        
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