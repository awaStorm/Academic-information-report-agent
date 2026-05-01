import json
import os
import re
import sys
import io
from playwright.sync_api import sync_playwright

class WechatHarvester:
    """微信凭证采集器"""
    # 计算项目根目录的路径 (src/collectors/sessions 是三级目录)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径
    AUTH_PATH = os.path.join(base_dir, "configs", "wechat_auth.json")
    
    def get_token(self, page):
        """等待并提取登录后的 token"""
        print("正在监听登录状态...")
        token = None
        max_retries = 60  # 设置 60 秒等待上限
        retry_count = 0
        
        while retry_count < max_retries:
            current_url = page.url
            if "token=" in current_url:
                # 使用正则提取 token 数值
                match = re.search(r'token=(\d+)', current_url)
                if match:
                    token = match.group(1)
                    page.wait_for_load_state("networkidle")
                    break
            page.wait_for_timeout(1000)
            retry_count += 1
        
        if not token:
            print("超时：未能捕获到 Token，请检查是否登录成功。")
            return None
            
        print(f"成功获取令牌 (Token): {token}")
        return token
    
    def save_auth_data(self, auth_data):
        """保存凭证到本地"""
        os.makedirs(os.path.dirname(self.AUTH_PATH), exist_ok=True)
        with open(self.AUTH_PATH, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, ensure_ascii=False, indent=4)
        print(f"凭证已成功保存至: {self.AUTH_PATH}")
    
    def run_harvest(self):
        with sync_playwright() as p:
            # 启动浏览器 (headless=False 以便人工扫码)
            print("--- 微信凭证收割程序启动 ---")
            print("正在调起浏览器，请完成扫码登录...")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            print(">>> 请在弹出的浏览器窗口中完成扫码登录 <<<")
            
            try:
                # 1. 导航到登录页
                page.goto("https://mp.weixin.qq.com/")
                
                # 2. 获取 token
                token = self.get_token(page)
                if not token:
                    return
                
                # 3. 抓取当前会话的所有 Cookies
                cookies = context.cookies()
                # 4. 抓取浏览器指纹 (User-Agent)
                ua = page.evaluate("navigator.userAgent")
                
                # 5. 封装并保存数据
                auth_data = {
                    "token": token,
                    "cookies": {c['name']: c['value'] for c in cookies},
                    "user_agent": ua
                }
                self.save_auth_data(auth_data)
                
                print("你现在可以关闭浏览器或等待程序自动结束。")
                
            except Exception as e:
                print(f"运行过程中发生错误: {str(e)}")
            finally:
                browser.close()

if __name__ == "__main__":
    # 实例化采集器并执行
    harvester = WechatHarvester()
    harvester.run_harvest()