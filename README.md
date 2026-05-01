# Academic Information Report Agent

针对“学习通”及其衍生app如”学在西电“与校园公众号的资讯采集 Agent。自动抓取并汇总竞赛报名、限额选课及志愿招募等关键情报

## 🎯 项目目标
解决校园信息碎片化问题，自动监控并汇总以下关键情报：
- 🏆 **学科竞赛**：数学建模、互联网+等报名提醒。
- 📚 **限额课程**：名额稀缺的选修课或讲座信息。
- 🤝 **志愿招募**：校内外的志愿服务机会。

## 📂 目录结构
- `agents/`: 基于 LLM 的信息提取与决策逻辑。
- `configs/`: 监控名单与关键词配置。
- `prompts/`: 用于信息分类与摘要的 Prompt 模板。
- `tools/`: 爬虫工具（Requests/Playwright）与解析器。

## 快速开始

1. 克隆仓库
2. 安装依赖：`pip install -r requirements.txt`
3. 安装 Playwright 浏览器：`playwright install chromium`
4. 复制 `.env.example` 为 `.env`，填入你的 API Key
5. 运行凭证采集：`python src/collectors/sessions/session_harvester.py`
6. 运行主流程：`python main.py`

## 项目结构

- `main.py` - 主调度入口
- `src/collectors/` - 数据采集（超星 + 微信）
- `src/processors/` - 数据清洗与合并
- `src/agent/` - AI 分析与推送
- `data/` - 数据文件（不提交）
- `configs/` - 凭证文件（不提交）
