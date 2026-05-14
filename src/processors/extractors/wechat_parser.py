import requests
from bs4 import BeautifulSoup
import json
import os
import time
import sys
import io

class WechatParser:
    """微信内容解析器"""
    # 计算项目根目录的路径 (src/processor/extractors 是三级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径
    INPUT_FILE = os.path.join(base_dir, "data", "raw", "data_raw_wechat.json")
    OUTPUT_FILE = os.path.join(base_dir, "data", "processed", "data_wechat_ready.json")
    
    def __init__(self):
        pass
    
    def parse_single_article(self, url):
        """
        最小化解析：只负责把文字扣出来
        """
        try:
            # 增加基础 UA，防止最简单的拦截
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            res = requests.get(url, headers=headers, timeout=15)
            res.encoding = 'utf-8' # 微信原文强制 utf-8
            
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 微信正文容器 ID 极为固定
            content_area = soup.find(id="js_content")
            
            if content_area:
                # get_text(separator='\n') 会保留标签间的换行，非常实用
                return content_area.get_text(separator='\n', strip=True)
            else:
                return "(未找到正文内容)"
                
        except Exception as e:
            return f"(解析异常: {str(e)})"
    
    def run_parser(self):
        if not os.path.exists(self.INPUT_FILE):
            print(f"❌ 找不到输入文件: {self.INPUT_FILE}")
            return {"success": False, "error_type": "NO_DATA", "message": f"找不到 {self.INPUT_FILE}"}
        
        with open(self.INPUT_FILE, "r", encoding="utf-8") as f:
            raw_articles = json.load(f)
        
        print(f"📖 开始解析 {len(raw_articles)} 篇文章的正文...")
        
        refined_data = []
        
        for item in raw_articles:
            title = item.get("title", "无标题")
            link = item.get("link", "")
            
            print(f"🚀 正在处理: {title[:20]}...")
            
            # 核心抓取动作
            full_body = self.parse_single_article(link)
            
            # 时间转换：wechat_scraper 给的是 update_time (秒级时间戳)
            formatted_date = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.get("update_time", time.time())))
            
            # 构建精简版对象
            refined_item = {
                "id": str(item.get("aid", item.get("appmsgid"))), # 微信的唯一 ID
                "platform": "wechat",
                "author": item.get("source_account", "微信公众号"),
                "title": title.strip(),
                "date": formatted_date,
                "body": full_body,
                "link": link
            }
            
            refined_data.append(refined_item)
            
            # 礼貌性延迟，避免被微信 CDN 短期屏蔽
            time.sleep(1)
        
        # 保存结果
        os.makedirs(os.path.dirname(self.OUTPUT_FILE), exist_ok=True)
        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(refined_data, f, ensure_ascii=False, indent=4)
        
        print(f"\n✨ 解析完成！已就绪数据存入: {self.OUTPUT_FILE}")
        return {"success": True, "count": len(refined_data)}
    
if __name__ == "__main__":
    # 实例化解析器并执行
    parser = WechatParser()
    parser.run_parser()