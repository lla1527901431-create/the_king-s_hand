# The King's Hand

一个基于 LangChain + DeepSeek 的 AI 日历助手。

用自然语言说一句话，它会自动识别日程、查天气、检查冲突，帮你安排时间。

## 功能

- 自然语言添加日程，自动解析时间、地点、备注
- 日程冲突检查
- 天气查询与出行建议（Open-Meteo，免密钥）
- 任务先进入"待确认 / 待计划"列表，确认后才写入日历
- 长期记忆（自动蒸馏用户的 facts 和 preferences）
- 导出 .ics 文件，或直接发送到邮箱
- 手机上打开邮件附件即可导入日历

## 技术栈

- Python 3.12
- FastAPI + uvicorn
- LangChain / LangChain Classic
- DeepSeek API
- Open-Meteo API（天气，无需密钥）
- 原生 HTML / CSS / JavaScript

## 项目结构

the_kings_hand/
├── main.py # 启动入口
├── agent/ # 模型、工具、数据层
│ ├── llm.py # DeepSeek 客户端
│ ├── tools.py # 本地工具（时间、日历增查）
│ ├── weather_openmeteo.py # 天气工具
│ ├── calendar_store.py # events.json 读写
│ ├── pending_store.py # pending.json 读写
│ ├── memory_store.py # memory.json 读写
│ └── ics_exporter.py # 生成 ics + 发邮件
├── server/ # Web 层
│ ├── app.py # FastAPI 路由
│ └── agent_runner.py # Agent 组装与调度
├── static/ # 前端
│ ├── index.html
│ ├── style.css
│ └── app.js
└── data/ # 运行时数据（不上传）
├── events.json
├── pending.json
└── memory.json