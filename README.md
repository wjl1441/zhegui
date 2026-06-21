# 折桂 — AI 备考 Agent 平台

面向公务员考试的 AI 备考助手，支持刷题复盘、模考分析、考前策略、学习计划、图片题目识别、速算练习、政治理论刷题、数据看板。

## 核心架构

**混合引擎：代码节点 + 模型节点按需切换。** 模型不参与路由决策，引擎在代码层面预设流程路径。

- **代码节点（MCP Server）：** 计算正确率、查卷子结构、匹配名师、数据校验
- **模型节点：** 意图识别、报告生成、个性化建议

## 技术栈

### 后端
- FastAPI + SSE 流式输出
- MCP 协议（3 个 MCP Server：calc / matcher / validator）
- SQLite 持久化
- 三层幻觉防御（输入校验 + 输出审核 + 系统熔断）
- LLM 调用监控（延迟/token/成功率）
- 失败恢复（指数退避重试 + 降级兜底）
- Token 预算（软硬上限 + 低产出检测）

### 前端
- 纯 HTML/CSS/JS

## 快速开始

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY 和 MIMO_API_KEY

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python server.py
# 或
uvicorn server:app --reload --port 8000

# 4. 访问
# http://127.0.0.1:8000
```

## 项目结构

```
折桂/
├── hybrid_engine.py    # 混合引擎核心
├── server.py           # FastAPI 入口
├── database.py         # SQLite 数据层
├── model_router.py     # 模型路由器
├── hallucination_defense.py  # 三层幻觉防御
├── metrics.py          # LLM 调用监控 (V4)
├── recovery.py         # 失败重试 + 降级 (V4)
├── budget.py           # Token 预算 (V4)
├── learning_profile.py # 用户画像
├── local_tools.py      # 本地工具
├── speed_calc.py       # 速算引擎
├── calc_mcp_server.py  # MCP Server: 计算
├── matcher_mcp_server.py    # MCP Server: 数据匹配
├── validator_mcp_server.py  # MCP Server: 数据校验
├── frontend/           # 前端页面
├── references/         # 知识库
├── shared-knowledge/   # 共享规则
├── eval/               # 自动化测试集
└── data/               # SQLite 数据库
```

## 许可

MIT License
