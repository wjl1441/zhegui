# 折桂 — 省 70% Token 消耗的考公 AI 备考 Agent

> 路由是代码确定的，不是模型决定的。

## 核心设计

市面上的 AI 备考工具几乎都是「用户提问 → 模型回答」。折桂不这么做。

**折桂用混合引擎：** 计算正确率、查卷子结构、匹配名师、校验数据——这些全部走本地代码。只有意图识别和报告生成才调模型。

这意味着你不会在计算「12 题对 20 题是 60% 正确率」这种问题上花一分钱的 Token。

## 能做什么

折桂不是问答机器人，是一套**完整备考工作流**：

- **刷题复盘** — 输入刷题数据 → 正确率分析（代码算）→ 错因定位（代码+模型）→ 名师推荐（代码匹配）
- **模考分析** — 多模块模考结果 → 数据校验（代码拦截「20 题对了 30 题」这种矛盾）→ 性价比分析 → 完整报告
- **考前策略** — 根据省份自动加载卷子结构 → 用时建议 → 薄弱点分析 → 策略生成
- **学习计划** — 聚合错题本 + 模考记录 + 速算数据 → 7 天备考计划
- **速算练习** — 花生十三题型，计时刷题，每日打卡
- **政治理论** — 小黑老师知识库，随机出题
- **图片题目识别** — 拍题 → 多模态提取 → 一键入错题本
- **数据看板** — 打卡热度、正确率趋势、考试倒计时

## 为什么省 70%

每次用户问「分析一下我的刷题数据」，普通 AI 备考工具的处理流程：

```
用户消息 → 模型分析意图 → 模型算正确率 → 模型查错因 → 模型匹配老师 → 模型写报告
            ↑全部走 LLM，每次 2000-5000 Token↑
```

折桂的处理流程：

```
用户消息 → 模型分析意图（仅此一步走 LLM）
         → calc MCP Server 算正确率（代码，0 Token）
         → matcher MCP Server 查错因 + 匹配老师（代码，0 Token）
         → 模型根据结构化数据写报告（LLM，但输入已经是精准数据而非原始对话）
```

**每轮省下 70% Token** 靠的不是算法优化，是**把模型不擅长的事交给代码做。**

## 技术栈

| 层 | 组件 |
|:--|:-----|
| Web 框架 | FastAPI + SSE 流式输出 |
| 混合引擎 | 代码节点（MCP Server）+ 模型节点按需切换 |
| MCP 协议 | 3 个 MCP Server：calc（计算）/ matcher（数据匹配）/ validator（数据校验） |
| 持久化 | SQLite，重启不丢 |
| 安全 | 三层幻觉防御（输入校验 + 输出审核 + 系统熔断） |
| 工程化 | LLM 调用监控（metrics）、失败重试（recovery）、Token 预算（budget） |
| 前端 | 纯 HTML/CSS/JS |

## 快速开始

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY 和 MIMO_API_KEY

# 2. 安装
pip install -r requirements.txt

# 3. 启动
uvicorn server:app --reload --port 8000

# 4. 访问 http://127.0.0.1:8000
```

## 设计理念

折桂的架构受到 **Harness Engineering** 和 **Loop Engineering** 的启发：

- **Harness（缰绳）：** 代码约束非模型自觉。幻觉防御、数据校验、Token 预算——全部在代码层面硬约束。
- **Loop（方向盘）：** intent → context → action → observation → adjustment 的五步闭环，每个流程有确定出口，不会无限循环。
- **Maker ≠ Checker：** 生成报告的模型不是校验数据的模型。validator MCP Server 独立校验，不信任模型输出。

```
Agent = Model + Harness
```

折桂的价值不在模型选择，在 **Harness 的工程质量。**

## 项目结构

```
折桂/
├── hybrid_engine.py          # 混合引擎核心（71KB，折桂的"大脑"）
├── server.py                 # FastAPI 入口 + SSE 流式
├── hallucination_defense.py  # 三层幻觉防御
├── model_router.py           # DeepSeek / MiMo 双模型路由
├── metrics.py                # LLM 调用监控（延迟/token/成功率）
├── recovery.py               # 指数退避重试 + 降级兜底
├── budget.py                 # Token 软硬上限 + 低产出检测
├── learning_profile.py       # 用户画像管理
├── local_tools.py            # 本地工具（跳过 MCP 子进程）
├── speed_calc.py             # 速算引擎
├── calc_mcp_server.py        # MCP Server：计算
├── matcher_mcp_server.py     # MCP Server：数据匹配
├── validator_mcp_server.py   # MCP Server：数据校验
├── database.py               # SQLite 数据层
├── frontend/index.html       # 前端页面
├── references/               # 知识库（卷子结构/名师/错因/政策）
├── shared-knowledge/         # 共享规则
├── eval/                     # 自动化测试集（常规/边界/攻击）
└── data/                     # SQLite 数据库
```

## License

MIT
