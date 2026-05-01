import os
import time
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

class SessionHarvester:
    """统一会话管理类"""
    # 计算项目根目录的路径 (src/collectors/sessions 是三级目录，所以跳三级)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # 配置路径和URL
    LOGIN_URL = "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.mooc.chaoxing.com"
    TARGET_DOMAINS = [
        "https://i.mooc.chaoxing.com",
        "https://notice.chaoxing.com/pc/notice/myNotice" 
    ]
    STORAGE_PATH = os.path.join(base_dir, "configs", "auth_cookies.json")
    
    def __init__(self):
        """初始化浏览器配置"""
        # 从环境变量获取浏览器路径
        self.executable_path = os.getenv("BROWSER_PATH")
        self.launch_kwargs = {
            "headless": False,  # 必须有头，让用户扫码
            "executable_path": self.executable_path if self.executable_path else None
        }
    
    def is_logged_in(self, page):
        """
        修改后的校验逻辑：
        不但要看 URL，还要看 Cookie 字典里是否已经包含了核心身份字段 UID。
        """
        try:
            current_url = page.url
            # 获取当前所有的 cookies
            cookies = page.context.cookies()
            has_uid = any(c['name'] == 'UID' for c in cookies)
            
            # 只有同时满足在正确域名下，且已经拿到了 UID，才算真正登录成功
            if ("i.mooc.chaoxing.com" in current_url) and has_uid:
                return True
            return False
        except:
            return False
    
    def sync_cookies_to_all_domains(self, page):
        """
        关键步骤：模拟真实用户行为，在所有需要鉴权的子域都走一遍。
        超星的跨域 SSO 依赖这些页面的加载来 'Set-Cookie'。
        """
        print("👉 正在同步全域身份凭证...")
        for domain_url in self.TARGET_DOMAINS:
            print(f"👉 访问: {domain_url}")
            page.goto(domain_url, wait_until="domcontentloaded", timeout=30000)
            # 等待一会，确保网络请求结束，Cookie 种好
            page.wait_for_load_state("networkidle")
        print("🎉 全域身份凭证同步完成！")
    
    def run_harvest(self):
        with sync_playwright() as p:
            print("👉 正在调起超星环境（有头模式）...")
            browser = p.chromium.launch(**self.launch_kwargs)
            # 建议开启隐身模式，防止用户本地 Cookie 干扰
            context = browser.new_context()
            page = context.new_page()
            
            # 1. 导航到登录页
            print("👉 请扫码：即将在浏览器中打开...")
            page.goto(self.LOGIN_URL)
            
            # 2. 轮询状态，等待用户扫码直到跳转
            if self.is_logged_in(page):
                print("✨ 检测到已存在有效的登录 Session，正在跳过扫码直接同步...")
            else:
                print("👉 等待扫码中...")
            
            # 3. 等待登录完成
            while not self.is_logged_in(page):
                # 防止无限等待，可以加一个超时限制，Demo 先简化
                if page.is_closed():
                    print("⚠️ 浏览器已关闭，获取凭证失败。")
                    return
                time.sleep(1) # 每秒检查一次 URL 状态
            
            print("✨ 检测到登录成功，正在进行最后的稳定性校验...")
            # 额外等待网络静默，确保所有身份相关的重定向和 Cookie 注入已完成
            page.wait_for_load_state("networkidle")
            time.sleep(1.5) # 给浏览器 1.5 秒的物理缓冲时间，确保 UID 彻底落盘

            # 4. 如果成功登录，触发跨域 Cookie 同步
            self.sync_cookies_to_all_domains(page)
            
            # 5. 将整个浏览器 context 的状态（含所有域的 Cookie 和 Storage）保存
            print(f"👉 正在保存凭证到 {self.STORAGE_PATH}...")
            context.storage_state(path=self.STORAGE_PATH)
            print("🎉 凭证获取成功，项目已彻底准备好数据源！")
            
            browser.close()

if __name__ == "__main__":
    # 实例化会话采集器并执行
    harvester = SessionHarvester()
    harvester.run_harvest()