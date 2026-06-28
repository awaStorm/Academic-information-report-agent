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
    
    # 企业微信 markdown.content 单条上限 4096 字节
    WECOM_CONTENT_LIMIT = 4096

    def _build_wecom_item_md(self, item):
        """构造单条情报的 Markdown 片段"""
        d = item.get('deadline')
        deadline = f"⏰ {d}" if d else ""
        raw_link = item.get('link', '')
        link = f" [🔗详情]({raw_link})" if (raw_link and str(raw_link).startswith('http')) else ""
        category = item.get('category', '校园动态')

        md = f"### {item.get('title')}\n"
        md += f"> **来源**: {item.get('source')} | **分类**: {category}\n"
        if deadline:
            md += f"> **时间**: {deadline}\n"
        md += f"> **干货**: {item.get('brief')}{link}\n\n"
        return md

    def _send_wecom_chunk(self, webhook_url, md_text):
        """发送单条企业微信消息，返回 (success: bool, errcode: int)"""
        data = {
            "msgtype": "markdown",
            "markdown": {"content": md_text}
        }
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            resp_json = response.json()
            errcode = resp_json.get("errcode", -1)
            if errcode == 0:
                return True, errcode
            else:
                print(f"❌ 企业微信推送失败: {response.text}")
                return False, errcode
        except Exception as e:
            print(f"💥 企业微信连接异常: {e}")
            return False, -1

    def send_wecom(self, pushed_items, date_str):
        """
        通过企业微信机器人推送核心提醒
        超过 4096 字节自动切片分条发送
        """
        webhook_url = self.wecom_webhook
        if not webhook_url:
            print("⚠️ 未配置 WECOM_WEBHOOK，跳过企业微信推送。")
            return False

        header = f"# 📅 西电情报核心提醒 | {date_str}\n"

        # 1. 将每条情报转为 Markdown 片段，按切片组装
        chunks = []
        current_chunk = header
        total_items = len(pushed_items)

        for i, item in enumerate(pushed_items):
            item_md = self._build_wecom_item_md(item)
            # 预判加入后是否会超限（用 utf-8 编码计算字节数）
            test_chunk = current_chunk + item_md
            if len(test_chunk.encode('utf-8')) > self.WECOM_CONTENT_LIMIT and current_chunk != header:
                # 当前切片已满，开始新切片
                chunks.append(current_chunk)
                current_chunk = f"# 📅 西电情报核心提醒 | {date_str} (续)\n"
            current_chunk += item_md

        # 别忘了最后一块
        if current_chunk.strip() != header.strip():
            chunks.append(current_chunk)

        # 2. 逐片发送
        if not chunks:
            print("📭 无情报内容需要推送。")
            return True

        all_success = True
        for idx, chunk in enumerate(chunks):
            if len(chunks) > 1:
                print(f"📤 推送切片 {idx + 1}/{len(chunks)}...")
            success, errcode = self._send_wecom_chunk(webhook_url, chunk)
            if not success:
                all_success = False
                # 40058 = 内容超长，尝试进一步细分
                if errcode == 40058 and len(pushed_items) > 1:
                    print("⚠️ 切片仍超长，尝试更细粒度拆分...")
                    mid = len(pushed_items) // 2
                    sub_success_a = self.send_wecom(pushed_items[:mid], date_str)
                    sub_success_b = self.send_wecom(pushed_items[mid:], date_str)
                    return sub_success_a and sub_success_b
                break

        if all_success:
            print(f"🚀 企业微信推送成功！共 {len(chunks)} 条消息，{total_items} 条情报。")
        return all_success
    
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
            resp = requests.post(url, data={"title": title, "desp": desp}, timeout=10)
            resp_data = resp.json()
            if resp_data.get("code") == 0:
                print("📲 Server 酱扩展推送已发出。")
                return True
            else:
                print(f"❌ Server 酱推送失败: {resp_data.get('message', resp.text[:100])}")
                return False
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
