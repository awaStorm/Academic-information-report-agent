import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()

class Scraper:
    """统一爬虫管理类"""
    # 计算项目根目录的路径 (src/collectors/scrapers 是三级目录，所以跳三级)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径和URL
    COOKIE_PATH = os.path.join(base_dir, "configs", "auth_cookies.json")
    NOTICE_LIST_URL = "https://notice.chaoxing.com/pc/notice/getNoticeList"
    OUTPUT_FILE = os.path.join(base_dir, "data", "raw", "data_raw_notice.json")
    
    def __init__(self):
        """初始化爬虫配置"""
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://notice.chaoxing.com/pc/notice/myNotice",
        }
        self.payload = {
            "type": "2",
            "year": "2026",
            "queryFolderNoticePrevYear": "0"
        }

    def load_cookies_from_json(self, path):
        """加载并转换凭证"""
        if not os.path.exists(path):
            print(f"❌ 找不到凭证文件: {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            return {c['name']: c['value'] for c in state['cookies']}
        except Exception as e:
            print(f"❌ 解析凭证失败: {e}")
            return None

    def fetch_and_save(self):
        """抓取数据并保存到本地文件"""
        os.makedirs(os.path.dirname(self.OUTPUT_FILE), exist_ok=True)
        cookies = self.load_cookies_from_json(self.COOKIE_PATH)
        if not cookies:
            return {"success": False, "error_type": "AUTH", "message": "找不到超星凭证文件"}

        print("🚀 正在发起请求并准备保存原始响应...")

        try:
            # 设置 Cookie
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain=".chaoxing.com")

            resp = self.session.post(self.NOTICE_LIST_URL, data=self.payload, headers=self.headers)
            
            if resp.status_code == 200:
                data = resp.json()
                notices_list = data.get('notices', {}).get('list', [])
                
                # --- 核心修正点：使用 self.OUTPUT_FILE ---
                with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                
                print(f"✅ 原始数据已保存至: {self.OUTPUT_FILE}")
                
                if notices_list:
                    print(f"📊 成功捕获 {len(notices_list)} 条通知数据。")
                    unread_count = sum(1 for item in notices_list if item.get('isread') == 0)
                    print(f"🔔 其中未读消息数量: {unread_count}")
                    return {"success": True, "count": len(notices_list), "unread": unread_count}
                else:
                    print("ℹ️ 服务器返回成功，但目前通知列表为空。")
                    return {"success": True, "count": 0}
            else:
                print(f"❌ 请求失败，HTTP 状态码: {resp.status_code}")
                return {"success": False, "error_type": "HTTP", "message": f"状态码 {resp.status_code}"}

        except Exception as e:
            print(f"💥 运行异常: {str(e)}")
            return {"success": False, "error_type": "EXCEPTION", "message": str(e)}

def run_scraper_flow():
    """供 main.py 调用的入口函数"""
    scraper = Scraper()
    scraper.fetch_and_save()

if __name__ == "__main__":
    run_scraper_flow()