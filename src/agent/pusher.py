import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

class Pusher:
    """统一推送管理类"""
    def __init__(self):
        self.wecom_webhook = os.getenv("WECOM_WEBHOOK")
        self.serverchan_sendkey = os.getenv("SERVERCHAN_SENDKEY")
    
    def send_wecom(self, pushed_items, date_str):
        """
        通过企业微信机器人推送核心提醒
        """
        webhook_url = self.wecom_webhook
        if not webhook_url:
            print("⚠️ 未配置 WECOM_WEBHOOK，跳过企业微信推送。")
            return False

        # 1. 构造 Markdown 内容
        md_text = f"# 📅 西电情报核心提醒 | {date_str}\n"
        for item in pushed_items:
            d = item.get('deadline')
            deadline = f"⏰截止 {d}" if d else "📅常规动态"
            link = f" [🔗详情]({item.get('link')})" if item.get('link') else ""
            category = item.get('category', '校园动态')
            
            md_text += f"### {item.get('title')}\n"
            md_text += f"> **来源**: {item.get('source')} | **分类**: {category}\n"
            md_text += f"> **时间**: {deadline}\n"
            md_text += f"> **干货**: {item.get('brief')}{link}\n\n"
        
        # 2. 发送请求
        data = {
            "msgtype": "markdown",
            "markdown": {"content": md_text}
        }
        
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            if response.json().get("errcode") == 0:
                print("🚀 企业微信推送成功！")
                return True
            else:
                print(f"❌ 企业微信推送失败: {response.text}")
                return False
        except Exception as e:
            print(f"💥 企业微信连接异常: {e}")
            return False
    
    def send_serverchan(self, pushed_items, date_str):
        """
        作为扩展方案：通过 Server 酱推送
        """
        send_key = self.serverchan_sendkey
        if not send_key:
            print("⚠️ 未配置 SERVERCHAN_SENDKEY，跳过扩展推送。")
            return False

        title = f"西电情报核心提醒 {date_str}"
        
        # 构造简单的正文
        desp = ""
        for item in pushed_items:
            desp += f"### {item.get('title')}\n- {item.get('brief')}\n\n"

        url = f"https://sctapi.ftqq.com/{send_key}.send"
        try:
            requests.post(url, data={"title": title, "desp": desp}, timeout=10)
            print("📲 Server 酱扩展推送已发出。")
            return True
        except Exception as e:
            print(f"💥 Server 酱连接异常: {e}")
            return False

if __name__ == "__main__":
    # 测试用例
    test_items = [{
        "title": "推送模块集成测试",
        "source": "Agent",
        "deadline": "2026-05-01",
        "brief": "企业微信主方案 + Server酱备选方案已就绪",
        "link": "https://github.com"
    }]
    
    # 实例化推送器并测试
    pusher = Pusher()
    print("🚀 企业微信推送结果:", pusher.send_wecom(test_items, "2026-04-29"))
    print("📲 Server酱推送结果:", pusher.send_serverchan(test_items, "2026-04-29"))
