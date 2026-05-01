import os
import sys
import io
from datetime import datetime

# Keep main.py's stdout redirection for Windows compatibility
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stdout.reconfigure(line_buffering=True)

# 1. 导入数据采集模块 (Scrapers)
from src.collectors.scrapers.scraper import Scraper
from src.collectors.scrapers.wechat_scraper import WechatScraper

# 2. 导入数据解析与精炼模块 (Processors)
from src.processors.data_processor import DataProcessor
from src.processors.extractors.wechat_parser import WechatParser
from src.processors.extractors.content_extractor import ContentExtractor

# 3. 导入合流与 AI 分析模块 (Merger & Agent)
from src.processors.mergers.final_merger import FinalMerger
from src.agent.analyzer import run_analysis_flow

def main():
    print(f"==========================================")
    print(f"🚀 西电校园情报 Agent 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==========================================")

    # --- 第一阶段：原始情报抓取 (Raw Data) ---
    print("\n📡 [Step 1: Data Collection]")
    try:
        print("👉 正在启动超星通知抓取...")
        Scraper().fetch_and_save()
        
        print("👉 正在启动微信公众号抓取...")
        WechatScraper().run_scraper_flow()
    except Exception as e:
        print(f"❌ 采集阶段发生致命错误: {e}")
        return

    # --- 第二阶段：多维解析与合流 (Processing) ---
    print("\n🧪 [Step 2: Parsing & Refining]")
    try:
        # 2.1 微信正文深度解析 (HTML -> Full Text)
        print("👉 正在解析微信网页正文...")
        WechatParser().run_parser()
        
        # 2.2 超星数据初步清洗 (Raw -> Refined)
        print("👉 正在清洗超星原始 JSON...")
        DataProcessor().run()
        
        # 2.3 统一字段精炼 (归一化 ID, Title, Body)
        print("👉 正在执行全平台字段对齐...")
        ContentExtractor().clean_and_refine()
        
        # 2.4 多源情报大合流 (Merging)
        print("👉 正在合并情报流...")
        FinalMerger().merge_intelligence()
        print("✅ 数据处理与合流全部完成。")
    except Exception as e:
        print(f"❌ 数据处理阶段发生致命错误: {e}")
        return

    # --- 第三阶段：AI 深度分析与精准推送 (Agent Core) ---
    print("\n🧠 [Step 3: AI Intelligence & Memory Push]")
    try:
        # 调用 analyzer.py 中已经集成了 DeepSeek 和数据库去重的核心流
        if run_analysis_flow():
            print("✨ 校园情报 Agent 任务圆满执行完毕。")
        else:
            print("⚠️ 流程已结束，但今日无新增核心情报需要推送。")
    except Exception as e:
        print(f"❌ AI 分析推送阶段发生致命错误: {e}")

    print(f"\n==========================================")
    print(f"🏁 任务调度结束 | {datetime.now().strftime('%H:%M:%S')}")
    print(f"==========================================")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 用户手动终止了程序。")
        sys.exit(0)