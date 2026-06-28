"""
main.py - CLI 入口（无前端环境运行完整流程）
支持通过命令行直接执行采集-分析-推送流程
"""
import os
import sys
import io
from datetime import datetime

# Windows 编码修复
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stdout.reconfigure(line_buffering=True)

# 将项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()


def main():
    print(f"==========================================")
    print(f"🚀 西电校园情报 Agent 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==========================================")

    # --- 第一阶段：原始情报抓取 (Raw Data) ---
    print("\n📡 [Step 1: Data Collection]")
    try:
        from src.collectors.scrapers.scraper import Scraper
        from src.collectors.scrapers.wechat_scraper import WechatScraper
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
        from src.processors.extractors.wechat_parser import WechatParser
        from src.processors.data_processor import DataProcessor
        from src.processors.extractors.content_extractor import ContentExtractor
        from src.processors.mergers.final_merger import FinalMerger

        print("👉 正在解析微信网页正文...")
        WechatParser().run_parser()
        print("👉 正在清洗超星原始 JSON...")
        DataProcessor().run()
        print("👉 正在执行全平台字段对齐...")
        ContentExtractor().clean_and_refine()
        print("👉 正在合并情报流...")
        FinalMerger().merge_intelligence()
        print("✅ 数据处理与合流全部完成。")
    except Exception as e:
        print(f"❌ 数据处理阶段发生致命错误: {e}")
        return

    # --- 第三阶段：AI 深度分析与精准推送 (Agent Core) ---
    print("\n🧠 [Step 3: AI Intelligence & Memory Push]")
    try:
        from src.agent.analyzer import run_analysis_flow
        result = run_analysis_flow()
        if result.get("success") and result.get("pushed", 0) > 0:
            print("✨ 校园情报 Agent 任务圆满执行完毕。")
        elif result.get("success"):
            print("⚠️ 流程已结束，但今日无新增核心情报需要推送。")
        else:
            print(f"❌ 分析流程执行失败: {result.get('message', '未知错误')}")
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
