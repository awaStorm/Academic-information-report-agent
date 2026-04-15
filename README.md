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

## 🚀 快速开始
1. `git clone https://github.com/awaStorm/Academic-information-report-agent.git`
2. `pip install -r requirements.txt`
3. 配置 `.env` 文件。
