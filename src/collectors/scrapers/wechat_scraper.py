import requests
import json
import os
import time
import sys
import io

class WechatScraper:
    """统一爬虫管理类"""
    # 计算项目根目录的路径 (src/collectors/scrapers 是三级目录，所以跳三级)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径和URL
    AUTH_PATH = os.path.join(base_dir, "configs", "wechat_auth.json")
    OUTPUT_FILE = os.path.join(base_dir, "data", "raw", "data_raw_wechat.json")
    
    def __init__(self):
        # Removed sys.stdout redirection for Windows compatibility
        pass
    
    def load_auth(self):
        if not os.path.exists(self.AUTH_PATH):
            print("❌ 找不到微信凭证，请先运行 wechat_harvester.py")
            return None
        with open(self.AUTH_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def fetch_single_account(self, auth, account_name):
        """抓取单个公众号，返回抓取到的文章列表"""
        token = auth["token"]
        
        # 构造基础 Headers
        headers = {
            "User-Agent": auth["user_agent"],
            "Cookie": "; ".join([f"{k}={v}" for k, v in auth["cookies"].items()]),
            "Host": "mp.weixin.qq.com",
            "X-Requested-With": "XMLHttpRequest"
        }
    
        # 1. 搜索步骤
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        headers["Referer"] = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isadd=1&type=10&token={token}&lang=zh_CN"
        
        search_params = {
            "action": "search_biz", "token": token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": account_name, "begin": "0", "count": "5"
        }
    
        try:
            search_resp = requests.get(search_url, params=search_params, headers=headers)
            search_data = search_resp.json()
            
            if not search_data.get("list"):
                print(f"⚠️ 未找到公众号: {account_name}")
                return []
    
            # 获取 ID 和 昵称
            target_biz = search_data["list"][0]["fakeid"]
            nickname = search_data["list"][0]["nickname"]
            print(f"✅ 匹配到: {nickname}")
    
            # 2. 获取文章列表步骤
            # 增加一个明显的延迟，模拟人类从搜索结果点击进入列表的操作
            print("等待接口响应中...")
            time.sleep(6) 
    
            article_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
            article_params = {
                "action": "list_ex",
                "begin": "0",
                "count": "4",  # 尝试改为抓取 4 篇
                "fakeid": target_biz,
                "type": "9",
                "query": "",
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1"
            }
            
            article_resp = requests.get(article_url, params=article_params, headers=headers)
            
            # --- 这里的 DEBUG 信息非常关键 ---
            if "default" in article_resp.text or article_resp.status_code != 200:
                print(f"❌ {nickname} 抓取异常。状态码: {article_resp.status_code}")
                print(f"🔍 响应原始内容: {article_resp.text[:200]}") # 打印前200字符看原因
                return []
    
            article_data = article_resp.json()
            if article_data.get("base_resp", {}).get("ret") == 0:
                articles = article_data.get("app_msg_list", [])
                for a in articles: 
                    a['source_account'] = nickname
                return articles
            else:
                err_msg = article_data.get('base_resp', {}).get('err_msg', 'unknown error')
                print(f"❌ {nickname} 业务错误: {err_msg}")
                return []
    
        except Exception as e:
            print(f"💥 {account_name} 系统异常: {str(e)}")
            return []
    
    def run_scraper_flow(self):
        os.makedirs(os.path.dirname(self.OUTPUT_FILE), exist_ok=True)
        auth = self.load_auth()
        if not auth: return
    
        # 你可以随时在这里增删关注名单
        my_follow_list = [
            "西小电星球", 
            "西电社团", 
            "西电体育"
        ]
    
        all_results = []
        print(f"🔔 开始批量巡检，目标公众号数量: {len(my_follow_list)}")
    
        for name in my_follow_list:
            print(f"\n--- 任务节点: {name} ---")
            articles = self.fetch_single_account(auth, name)
            if articles:
                print(f"📥 成功获取 {len(articles)} 篇文章")
                all_results.extend(articles)
            
            # 公众号切换之间的长间隔
            print("正在切换下一个目标...")
            time.sleep(8)
    
        # 保存结果
        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=4)
    
        print(f"\n✨ 批量任务完成！共收集 {len(all_results)} 条情报。")
        if all_results:
            print(f"📂 数据已存入: {self.OUTPUT_FILE}")

def run_wechat_scraper_flow():
    """
    供外部接口（如 main.py）直接调用的包装函数
    """
    scraper = WechatScraper()
    return scraper.run_scraper_flow()

if __name__ == "__main__":
    # 本地直接运行调试
    run_wechat_scraper_flow()