"""
折桂混合引擎
代码节点和模型节点按需切换，路由由代码确定，不依赖模型决策
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
import database as db
from hallucination_defense import HallucinationDefense
import local_tools
from metrics import record_llm_call, usage_from_response
from recovery import with_retry, classify_error
import study_plan_history

# 持久化目录
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "history.jsonl"


def _load_env_file():
    """轻量加载项目 .env，避免 Streamlit 入口拿不到 API Key。"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# 模型配置（从环境变量读取，支持 .env）
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_FALLBACK_MODEL = os.getenv("DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro")


def _python_executable() -> str:
    """返回当前 Python 解释器，MCP 子进程不再依赖系统里必须存在 python 命令。"""
    return sys.executable or "python"


@dataclass
class Intent:
    """用户意图"""
    type: str           # daily_practice, mock_exam, pre_exam_strategy
    module: str         # 模块名称
    correct: int        # 答对题数
    total: int          # 总题数
    province: str       # 省份（模考/考前策略用）
    modules: list       # 多模块数据（模考用）
    raw_message: str    # 原始消息


@dataclass
class FlowStep:
    """流程步骤记录"""
    node_type: str      # "代码" 或 "模型"
    tool_name: str      # 工具/模型名称
    result: any         # 执行结果
    success: bool       # 是否成功
    reasoning: str = "" # 推理过程（CoT）


class HybridEngine:
    """混合引擎：代码节点 + 模型节点"""

    def __init__(self):
        # MCP Server 参数
        self.server_params = {
            "calc": StdioServerParameters(
                command=_python_executable(),
                args=[str(BASE_DIR / "calc_mcp_server.py")]
            ),
            "matcher": StdioServerParameters(
                command=_python_executable(),
                args=[str(BASE_DIR / "matcher_mcp_server.py")]
            ),
            "validator": StdioServerParameters(
                command=_python_executable(),
                args=[str(BASE_DIR / "validator_mcp_server.py")]
            ),
        }

        # DeepSeek API（兼容 OpenAI 格式）
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-placeholder"),
            base_url="https://api.deepseek.com"
        )

        # 流程路由表（代码决定，不是模型决定）
        self.flow_map = {
            "daily_practice": self._daily_practice_flow,
            "mock_exam": self._mock_exam_flow,
            "pre_exam_strategy": self._strategy_flow,
            "study_plan": self._study_plan_flow,
            "memory_query": self._memory_query_flow,
            "casual_chat": self._casual_chat_flow,
        }

        # 熔断器状态
        self._circuit_breaker = {}  # {server_name: {"failures": 0, "last_failure": 0}}

        # MCP 调用锁（确保同一时间只有一个 MCP 调用）
        self._mcp_lock = None

        # 幻觉防御
        self.defense = HallucinationDefense()

    def _llm_chat_completion(self, model: str, messages: list, temperature: float = 0.7, **kwargs):
        """统一 LLM 调用：重试 + 延迟/token 监控。"""
        import time
        start = time.perf_counter()
        try:
            response = with_retry(lambda: self.llm.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                **kwargs
            ))
            input_tokens, output_tokens = usage_from_response(response)
            record_llm_call(model, (time.perf_counter() - start) * 1000, input_tokens, output_tokens, "success")
            return response
        except Exception as e:
            error_type = classify_error(e)
            record_llm_call(model, (time.perf_counter() - start) * 1000, 0, 0, "failed", error_type)
            raise

    async def process(self, user_message: str, session_id: str = "default") -> dict:
        """处理用户消息，返回结果和流程日志

        Args:
            user_message: 用户输入的消息
            session_id: 会话 ID（用于多轮对话）

        Returns:
            {
                "response": "回复内容",
                "flow_log": [FlowStep, ...],
                "intent": Intent
            }
        """
        flow_log = []
        start_time = datetime.now()

        # 持久化：记录流程开始
        self._save_to_history("start", user_message, None)

        try:
            # 检查是否有未完成的多轮对话
            state = db.get_conversation_state(session_id)
            if state:
                if state['flow'] == 'mock_exam':
                    # 继续模考复盘流程
                    response = await self._continue_mock_exam_flow(user_message, state, flow_log)
                    self._save_to_history("complete", user_message, response)
                    return {
                        "response": response,
                        "flow_log": flow_log,
                        "intent": Intent(type="mock_exam", module="", correct=0, total=0, province="", modules=[], raw_message=user_message)
                    }
                elif state['flow'] == 'practice_followup':
                    # 继续刷题后续流程（收集错因）
                    response = await self._continue_practice_followup(user_message, state)
                    self._save_to_history("complete", user_message, response)
                    return {
                        "response": response,
                        "flow_log": flow_log,
                        "intent": Intent(type="daily_practice", module="", correct=0, total=0, province="", modules=[], raw_message=user_message)
                    }

            # ① 模型节点：意图识别
            intent = await self._extract_intent(user_message)
            flow_log.append(FlowStep(
                node_type="模型",
                tool_name="意图识别",
                result=intent.__dict__,
                success=True
            ))

            # ② 路由：根据意图类型查找对应的 flow（代码决定）
            flow_func = self.flow_map.get(intent.type)
            if not flow_func:
                # 未知意图，返回友好提示
                response = self._handle_unknown_intent(user_message)
                self._save_to_history("complete", user_message, response)
                return {
                    "response": response,
                    "flow_log": flow_log,
                    "intent": intent
                }

            # ③ 执行对应的流程
            response = await flow_func(intent, flow_log, session_id)

            # 持久化：记录流程完成
            self._save_to_history("complete", user_message, response)

            return {
                "response": response,
                "flow_log": flow_log,
                "intent": intent
            }

        except Exception as e:
            # 错误处理：记录错误并返回友好提示
            error_response = f"处理过程中出现错误：{str(e)}"
            self._save_to_history("error", user_message, error_response)
            return {
                "response": error_response,
                "flow_log": flow_log,
                "intent": None
            }

    def _save_to_history(self, event_type: str, user_message: str, response: str):
        """持久化：保存对话历史到 JSONL 文件"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "user_message": user_message,
            "response": response
        }
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"持久化写入失败: {e}")

    def get_history(self, limit: int = 10) -> list:
        """读取最近的历史记录"""
        if not HISTORY_FILE.exists():
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = [json.loads(line) for line in lines[-limit*2:]]  # 每轮对话有 start + complete
            # 只返回 complete 记录
            return [r for r in records if r["event_type"] == "complete"][-limit:]
        except Exception as e:
            return []

    def _check_circuit_breaker(self, server_name: str) -> bool:
        """检查熔断器状态，返回 True 表示可以调用"""
        if server_name not in self._circuit_breaker:
            return True

        state = self._circuit_breaker[server_name]
        if state["failures"] < 3:
            return True

        # 检查是否已过 60 秒
        elapsed = (datetime.now() - datetime.fromisoformat(state["last_failure"])).total_seconds()
        if elapsed > 60:
            # 重置熔断器
            self._circuit_breaker[server_name] = {"failures": 0, "last_failure": None}
            return True

        return False

    def _record_failure(self, server_name: str):
        """记录失败次数"""
        if server_name not in self._circuit_breaker:
            self._circuit_breaker[server_name] = {"failures": 0, "last_failure": None}
        self._circuit_breaker[server_name]["failures"] += 1
        self._circuit_breaker[server_name]["last_failure"] = datetime.now().isoformat()

    async def _extract_intent(self, user_message: str) -> Intent:
        """模型节点：意图识别

        使用 DeepSeek API 从用户消息中提取结构化意图
        """
        if not user_message or not user_message.strip():
            return Intent(type="unknown", module="", correct=0, total=0, province="", modules=[], raw_message=user_message)

        prompt = f"""你是一个意图识别助手。从用户消息中提取以下信息：

1. intent: 意图类型，只能是以下之一：
   - daily_practice（日常刷题）
   - mock_exam（模考/套卷）
   - pre_exam_strategy（考前策略）
   - study_plan（学习计划/复习计划）
   - memory_query（查询上次复盘、聊天记录、学习记忆）
   - casual_chat（闲聊、陪聊、非备考聊天）

2. module: 模块名称，只能是以下之一：
   - 言语理解
   - 数量关系
   - 判断推理
   - 资料分析
   - 常识判断
   - 如果无法判断，返回 null

3. correct: 答对题数（整数），如果没有提到返回 0
4. total: 总题数（整数），如果没有提到返回 0
5. province: 省份名称（如"贵州"、"广东"、"国考"），如果没有提到返回空字符串
6. modules: 模考时各模块数据，格式为 [{{"module": "言语理解", "correct": 12, "total": 20}}, ...]，如果不是模考返回空数组

用户消息：{user_message}

请直接返回 JSON 格式，不要有任何其他文字：
{{"intent": "...", "module": "...", "correct": 0, "total": 0, "province": "", "modules": []}}"""

        try:
            response = self._llm_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            content = response.choices[0].message.content.strip()
            # 提取 JSON 部分
            if "{" in content:
                json_str = content[content.index("{"):content.rindex("}") + 1]
                data = json.loads(json_str)
            else:
                data = json.loads(content)

            parsed = self._parse_intent_from_text(user_message)
            intent_type = data.get("intent", "unknown")
            # 对模型输出做代码侧兜底校正：高频关键词不交给模型自由发挥。
            rule_type = self._rule_based_intent_type(user_message)
            if rule_type != "unknown":
                intent_type = rule_type

            # 安全类/越权类请求强制走 unknown，不采纳模型分类。
            if self._is_unsafe_request(user_message) or self._is_greeting(user_message):
                intent_type = "unknown"

            return Intent(
                type=intent_type,
                module=parsed.get("module") or data.get("module", ""),
                correct=parsed.get("correct") if parsed.get("correct") is not None else data.get("correct", 0),
                total=parsed.get("total") if parsed.get("total") is not None else data.get("total", 0),
                province=parsed.get("province") or data.get("province", ""),
                modules=parsed.get("modules") or data.get("modules", []),
                raw_message=user_message
            )
        except Exception as e:
            # 模型调用失败时，尝试简单关键词匹配
            return self._fallback_intent(user_message)

    def _is_greeting(self, user_message: str) -> bool:
        msg = user_message.strip().lower()
        greetings = {"你好", "您好", "hi", "hello", "嗨", "早上好", "下午好", "晚上好"}
        return msg in greetings

    def _is_unsafe_request(self, user_message: str) -> bool:
        """拦截越权、注入、敏感信息请求。
        
        Harness Engineering ratchet：
        - 数据销毁类："清除/删除/重置 + 数据/数据库/系统"（结构性匹配，不枚举全部同义组合）
        - 凭证窃取类：具体的关键词列表
        - 角色篡改类："你不是 + 折桂" 或 "忽略 + 规则"（需要同时出现，防止单字误杀）
        """
        msg = user_message.lower()
        
        # 凭证窃取类：精确关键词
        credential_kw = ["管理员口令", "admin password", ".env", "api_key", "sk-",
                         "输出环境变量", "env 文件"]
        if any(k in msg for k in credential_kw):
            return True
        
        # 角色篡改类：两个关键词必须同时出现
        role_hijack_pairs = [
            ("你不是", "折桂"), ("你不是", "考试助手"), ("你现在", "不是折桂"),
            ("忽略", "规则"), ("忽略", "指令"), ("ignore", "instruction"),
        ]
        for a, b in role_hijack_pairs:
            if a in msg and b in msg:
                return True
        
        # 数据销毁类：动作词 + 目标词
        destroy_actions = ["删除", "清除", "清空", "重置", "删库", "drop"]
        destroy_targets = ["数据", "数据库", "记录", "内容", "全部", "所有", "系统", "table", "database"]
        for act in destroy_actions:
            for tgt in destroy_targets:
                if act in msg and tgt in msg:
                    return True
        
        return False

    def _is_memory_query(self, user_message: str) -> bool:
        """查询学习记忆/复盘历史。"""
        msg = user_message.lower()
        patterns = [
            "上一次复盘", "上次复盘", "最近一次复盘", "复盘是什么时候",
            "上一次聊天", "上一次对话", "上次聊天", "上次对话",
            "聊天记录", "对话记录", "之前聊过", "之前说了",
            "什么时候复盘", "什么时候聊", "什么时候对话",
            "我的记忆", "我的记录", "学习记录", "学情档案",
        ]
        return any(p in msg for p in patterns)

    def _is_casual_chat_request(self, user_message: str) -> bool:
        """识别用户明确想闲聊/非备考交流。"""
        msg = user_message.lower()
        patterns = [
            "聊聊天", "闲聊", "陪我聊", "随便聊", "想和你聊",
            "想和你说话", "不想学习", "不聊学习", "放松一下",
            "今天天气", "你叫什么", "你是谁", "你是什么",
        ]
        return any(p in msg for p in patterns)

    def _is_general_chat(self, user_message: str) -> bool:
        """兼容旧调用：识别非考试相关通用聊天。"""
        return self._is_memory_query(user_message) or self._is_casual_chat_request(user_message)

    def _rule_based_intent_type(self, user_message: str) -> str:
        """高置信关键词路由，防止 LLM 把「刷题」误分到模考。"""
        msg = user_message
        if self._is_memory_query(user_message):
            return "memory_query"
        if self._is_casual_chat_request(user_message):
            return "casual_chat"
        if any(kw in msg for kw in ["学习计划", "复习计划", "备考计划", "每日计划", "怎么学"]):
            return "study_plan"
        if any(kw in msg for kw in ["模考", "模拟", "套卷", "真题"]):
            return "mock_exam"
        if any(kw in msg for kw in ["快考试", "考前", "冲刺"]):
            return "pre_exam_strategy"
        if any(kw in msg for kw in ["刷了", "刷题", "练了", "做题", "对了", "错了"]) or ("做了" in msg and ("题" in msg or "道" in msg)):
            return "daily_practice"
        return "unknown"

    def _parse_intent_from_text(self, user_message: str) -> dict:
        """规则解析题量/模块/省份，减少简单数字抽取对 LLM 的依赖。"""
        import re

        msg = user_message.strip()
        module_aliases = {
            "政治理论": ["政治理论", "政治", "理论"],
            "言语理解": ["言语理解", "言语", "选词", "片段"],
            "数量关系": ["数量关系", "数量", "数学", "数资"],
            "判断推理": ["判断推理", "判断", "图推", "逻辑", "类比", "定义"],
            "资料分析": ["资料分析", "资料", "资分"],
            "常识判断": ["常识判断", "常识"],
        }
        province_aliases = {
            "国考副省级": ["国考副省级", "副省级", "副省"],
            "国考地市": ["国考地市", "地市级", "地市"],
            "国考": ["国考"],
            "湖北": ["湖北"],
            "贵州": ["贵州"],
            "江苏": ["江苏"],
            "广东": ["广东"],
            "浙江": ["浙江"],
        }

        def find_module(text: str) -> str:
            for module, aliases in module_aliases.items():
                if any(a in text for a in aliases):
                    return module
            return ""

        def find_province(text: str) -> str:
            for province, aliases in province_aliases.items():
                if any(a in text for a in aliases):
                    return province
            return ""

        parsed = {"module": find_module(msg), "correct": None, "total": None, "province": find_province(msg), "modules": []}

        # 模块片段：资料分析15对10 / 资料15/10 / 判断25道对18道
        module_pattern = "|".join(re.escape(a) for aliases in module_aliases.values() for a in aliases)
        for m in re.finditer(rf"(?P<name>{module_pattern})\D{{0,8}}(?P<a>\d+)\s*(?:道|题)?\s*(?:对|/|答对|正确)\s*(?P<b>\d+)", msg):
            module = find_module(m.group("name"))
            a, b = int(m.group("a")), int(m.group("b"))
            total, correct = (max(a, b), min(a, b))
            if module and total > 0:
                parsed["modules"].append({"module": module, "correct": correct, "total": total})

        if parsed["modules"]:
            # 单模块刷题时也同步顶层字段，模考时流程会优先使用 modules。
            first = parsed["modules"][0]
            parsed.update({"module": first["module"], "correct": first["correct"], "total": first["total"]})
            return parsed

        # 常见单模块：20道言语理解对了12道 / 言语20题正确12题
        m = re.search(r"(?P<total>\d+)\s*(?:道|题).{0,12}?(?P<module>" + module_pattern + r").{0,12}?(?:对了|答对|正确|对)\s*(?P<correct>\d+)", msg)
        if not m:
            m = re.search(r"(?P<module>" + module_pattern + r").{0,12}?(?P<total>\d+)\s*(?:道|题)?.{0,8}?(?:对了|答对|正确|对)\s*(?P<correct>\d+)", msg)
        if m:
            parsed["module"] = find_module(m.group("module"))
            parsed["total"] = int(m.group("total"))
            parsed["correct"] = int(m.group("correct"))
            return parsed

        # 简写：20对12 / 20/12，结合上下文里的模块。
        m = re.search(r"(?P<a>\d+)\s*(?:对|/)\s*(?P<b>\d+)", msg)
        if m:
            a, b = int(m.group("a")), int(m.group("b"))
            parsed["total"], parsed["correct"] = max(a, b), min(a, b)

        # 错了 N 道，共 M 道。
        m = re.search(r"错(?:了)?\s*(?P<wrong>\d+)\s*(?:道|题)?.{0,8}?(?:共|总共|一共)\s*(?P<total>\d+)\s*(?:道|题)?", msg)
        if m:
            total = int(m.group("total"))
            wrong = int(m.group("wrong"))
            parsed["total"] = total
            parsed["correct"] = max(total - wrong, 0)

        return parsed

    def _fallback_intent(self, user_message: str) -> Intent:
        """备用意图识别：关键词匹配"""
        msg = user_message

        # 意图类型：先匹配更具体的流程，避免“做了模考”被“做了”误判为日常刷题
        intent_type = "unknown"
        if self._is_unsafe_request(msg) or self._is_greeting(msg):
            intent_type = "unknown"
        else:
            intent_type = self._rule_based_intent_type(msg)

        parsed = self._parse_intent_from_text(user_message)

        # 模块
        module = parsed.get("module") or ""

        correct = parsed.get("correct") or 0
        total = parsed.get("total") or 0

        return Intent(
            type=intent_type,
            module=module,
            correct=correct,
            total=total,
            province=parsed.get("province") or "",
            modules=parsed.get("modules") or [],
            raw_message=user_message
        )

    async def _daily_practice_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """刷题分析流程"""

        # ① 代码节点：校验数据
        check_result = await self._call_mcp("validator", "check_data", {
            "correct": intent.correct,
            "total": intent.total,
            "module": intent.module or ""
        })
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="validator.check_data",
            result=check_result,
            success=check_result.get("status") == "pass",
            reasoning=f"校验数据：答对 {intent.correct} 题，共 {intent.total} 题，模块「{intent.module}」"
        ))

        if check_result.get("status") != "pass":
            reason = check_result.get('reason', '未知错误')
            if '总题数不能为0' in reason:
                return "你好！我是折桂，考公备考助手。请告诉我你刷了多少题，例如：\n- 「我今天刷了20道言语理解，对了12道」\n- 「数量关系做了15道，只对了5道」"
            return f"数据校验失败：{reason}"

        # ② 代码节点：计算正确率
        accuracy_result = await self._call_mcp("calc", "accuracy", {
            "correct": intent.correct,
            "total": intent.total
        })
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="calc.accuracy",
            result=accuracy_result,
            success="accuracy" in accuracy_result,
            reasoning=f"计算正确率：{intent.correct} ÷ {intent.total} = {accuracy_result.get('accuracy', '?')}%"
        ))

        # ③ 代码节点：查询名师
        teachers_result = await self._call_mcp("matcher", "teachers", {
            "module": intent.module or "言语理解"
        })
        teacher_names = [t["name"] for t in teachers_result.get("teacher_list", [])]
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.teachers",
            result=teachers_result,
            success="teacher_list" in teachers_result,
            reasoning=f"查询名师：模块「{intent.module}」→ {', '.join(teacher_names) if teacher_names else '无'}"
        ))

        # ④ 代码节点：查询错因方案
        solutions_result = None
        wrong_count = intent.total - intent.correct
        if wrong_count > 0:
            solutions_result = await self._call_mcp("matcher", "error_solutions", {
                "module": intent.module or "言语理解"  # 默认值
            })
            flow_log.append(FlowStep(
                node_type="代码",
                tool_name="matcher.error_solutions",
                result=solutions_result,
                success="all_solutions" in solutions_result if solutions_result else False,
                reasoning=f"查询错因方案：错 {wrong_count} 题，获取解决方案"
            ))

        # ⑤ 代码节点：幻觉防御 - 校验老师名
        if teachers_result and "teacher_list" in teachers_result:
            for teacher in teachers_result["teacher_list"]:
                check_teacher_result = await self._call_mcp("validator", "check_teacher", {
                    "name": teacher["name"]
                })
                flow_log.append(FlowStep(
                    node_type="代码",
                    tool_name="validator.check_teacher",
                    result=check_teacher_result,
                    success=check_teacher_result.get("status") == "pass",
                    reasoning=f"幻觉防御：校验老师「{teacher['name']}」是否在知识库中"
                ))

        # ⑥ 模型节点：生成分析报告
        report = await self._generate_report(intent, accuracy_result, teachers_result, solutions_result)
        flow_log.append(FlowStep(
            node_type="模型",
            tool_name="生成分析报告",
            result=report[:100] + "...",
            success=True,
            reasoning="基于以上数据生成分析报告"
        ))

        # ⑦ 引导用户补充错因信息
        wrong_count = intent.total - intent.correct
        if wrong_count > 0:
            # 保存状态，进入多轮对话收集错因
            db.save_conversation_state(session_id, "practice_followup", 1, {
                "module": intent.module,
                "total": intent.total,
                "correct": intent.correct,
                "report": report,
                "solutions": solutions_result.get("all_solutions", {}) if solutions_result else {}
            })

            # 生成错因引导
            error_guide = self._generate_error_guide(intent.module, solutions_result)
            return report + "\n\n---\n\n" + error_guide

        return report

    def _generate_error_guide(self, module: str, solutions: dict) -> str:
        """生成错因引导提示"""
        guide = "📝 **错题记录**\n\n"
        guide += f"你有 {module} 的错题，要不要记录下来方便以后复习？\n\n"
        guide += "请告诉我：\n"

        if solutions and "all_solutions" in solutions:
            # 列出该模块的常见错因类型
            error_types = []
            for _, errors in solutions["all_solutions"].items():
                for error_type in errors.keys():
                    error_types.append(f"- {error_type}")

            if error_types:
                guide += "**1. 错因类型**（可选以下，或自己描述）：\n"
                guide += "\n".join(error_types[:6]) + "\n\n"

        guide += "**2. 题目描述**（可选，方便以后复习）\n\n"
        guide += "直接输入错因即可，例如：「词语辨析不清」或「计算粗心」"

        return guide

    async def _continue_practice_followup(self, user_message: str, state: dict) -> str:
        """继续刷题后续流程（收集错因）"""
        session_id = state["session_id"]
        data = state["data"]

        # 用户回复了错因
        error_type = user_message.strip()

        # 保存到错题本：按本次错题数量生成待补全题卡，而不是只生成 1 条汇总记录
        wrong_count = max(int(data.get("total", 0)) - int(data.get("correct", 0)), 1)
        for i in range(wrong_count):
            db.add_mistake(
                module=data["module"],
                question=f"{data['module']}刷题错题 {i + 1}/{wrong_count}（{data['correct']}/{data['total']}）",
                correct_answer="",
                error_type=error_type,
                source="practice"
            )

        # 清除状态
        db.clear_conversation_state(session_id)

        return f"✅ 已根据本次错题数生成 {wrong_count} 张待补全错题卡，错因统一标记为「{error_type}」。\n\n请到错题本逐条补全题干、正确答案和解析，补全后就可以进入复习作答。"

    async def _generate_report(self, intent: Intent, accuracy: dict, teachers: dict, solutions: dict) -> str:
        """模型节点：生成分析报告（带幻觉防御）"""

        # 第1层：清洗数据
        clean_data = self.defense.sanitize_input_data({
            "mistakes_stats": {"total": intent.total, "mastered": 0, "pending": intent.total - intent.correct, "modules": []},
            "speed_stats": {"stats": {"total_sessions": 0, "avg_accuracy": 0, "avg_time": 0}},
            "exams": [],
            "streak": 0,
            "teachers": {intent.module: teachers.get('teacher_list', [])},
        })

        # 构造上下文
        context = f"""用户刷题数据：
- 模块：{intent.module}
- 总题数：{intent.total}
- 答对题数：{intent.correct}
- 正确率：{accuracy.get('accuracy', '未知')}%
- 等级：{accuracy.get('level', '未知')}

推荐名师：
{json.dumps(teachers.get('teacher_list', []), ensure_ascii=False, indent=2)}

错因解决方案：
{json.dumps(solutions.get('all_solutions', {}) if solutions else {}, ensure_ascii=False, indent=2)}"""

        prompt = f"""你是一个考公备考助手，叫折桂。请根据用户的刷题数据，生成一段简洁的分析报告。

要求：
1. 只使用提供的真实数据，不要编造
2. 先总结正确率和等级
3. 如果有错题，列出错因类型（不分析原因）
4. 推荐对应的名师（只列名字）
5. 语气友好、鼓励

数据：
{context}

请直接输出分析报告。"""

        try:
            response = self._llm_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            report = response.choices[0].message.content

            # 第2层：输出校验
            validation = self.defense.validate_output(report, clean_data)
            if not validation["valid"]:
                return validation["cleaned_report"]

            return report

        except Exception as e:
            # 第3层：兜底报告
            return self._fallback_report(intent, accuracy, teachers, solutions)

    def _fallback_report(self, intent: Intent, accuracy: dict, teachers: dict, solutions: dict) -> str:
        """备用报告生成：不依赖模型"""
        acc = accuracy.get("accuracy", 0)
        level = accuracy.get("level", "未知")
        wrong = intent.total - intent.correct

        report = f"## 刷题分析报告\n\n"
        report += f"**模块**：{intent.module}\n"
        report += f"**正确率**：{acc}%（{level}）\n"
        report += f"**答对**：{intent.correct}/{intent.total}\n\n"

        if wrong > 0:
            report += "### 薄弱分析\n"
            report += f"本次错 {wrong} 题，建议重点突破以下错因：\n"
            if solutions and "all_solutions" in solutions:
                for sub_type, errors in solutions["all_solutions"].items():
                    report += f"- {sub_type}\n"
            report += "\n"

        if teachers and "teacher_list" in teachers:
            report += "### 推荐名师\n"
            for t in teachers["teacher_list"]:
                report += f"- **{t['name']}**：{t['speciality']}\n"
            report += "\n"

        if acc >= 80:
            report += "### 建议\n继续保持，可以尝试限时训练提升速度。"
        elif acc >= 60:
            report += "### 建议\n正确率有提升空间，建议针对错题类型专项突破。"
        else:
            report += "### 建议\n建议先跟名师课程打基础，再大量刷题巩固。"

        return report

    async def _generate_mock_report(self, intent: Intent, province: str, modules_data: list,
                                     accuracy_results: list, roi_result: dict,
                                     time_results: dict, structure_result: dict) -> str:
        """模型节点：生成模考分析报告（带幻觉防御）"""

        # 第1层：清洗数据
        clean_data = self.defense.sanitize_input_data({
            "mistakes_stats": {"total": sum(m.get("total", 0) for m in modules_data), "mastered": 0, "pending": 0, "modules": []},
            "speed_stats": {"stats": {"total_sessions": 0, "avg_accuracy": 0, "avg_time": 0}},
            "exams": [{"date": datetime.now().strftime('%Y-%m-%d'), "province": province, "total_score": sum(r.get("correct", 0) for r in accuracy_results) / max(sum(r.get("total", 0) for r in accuracy_results), 1) * 100}],
            "streak": 0,
        })

        # 构造上下文
        context = f"""模考数据（{province}卷）：

各模块正确率：
{json.dumps([{"模块": r.get("module", ""), "正确率": r.get("accuracy", 0), "答对": r.get("correct", 0), "总题": r.get("total", 0)} for r in accuracy_results], ensure_ascii=False, indent=2)}

性价比排序：
{json.dumps(roi_result.get("ranked", []) if roi_result else [], ensure_ascii=False, indent=2)}

用时标准：
{json.dumps(time_results, ensure_ascii=False, indent=2)}

卷子结构：
{json.dumps(structure_result.get("modules", []) if structure_result else [], ensure_ascii=False, indent=2)}"""

        prompt = f"""你是一个考公备考助手，叫折桂。请根据用户的模考数据，生成一份分析报告。

要求：
1. 只使用提供的真实数据，不要编造
2. 用表格展示各模块正确率
3. 列出性价比排序（只列模块名和正确率）
4. 列出用时标准（只列数字）
5. 语气友好

数据：
{context}

请直接输出分析报告。"""

        try:
            response = self._llm_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            report = response.choices[0].message.content

            # 第2层：输出校验
            validation = self.defense.validate_output(report, clean_data)
            if not validation["valid"]:
                return validation["cleaned_report"]

            return report

        except Exception as e:
            # 第3层：兜底报告
            return self._fallback_mock_report(province, accuracy_results, roi_result, time_results)

    def _fallback_mock_report(self, province: str, accuracy_results: list,
                               roi_result: dict, time_results: dict) -> str:
        """备用模考报告生成"""
        report = f"## 模考分析报告（{province}卷）\n\n"

        # 各模块正确率
        report += "### 各模块正确率\n"
        for r in accuracy_results:
            module = r.get("module", "")
            acc = r.get("accuracy", 0)
            report += f"- **{module}**：{acc}%\n"
        report += "\n"

        # 性价比排序
        if roi_result and "ranked" in roi_result:
            report += "### 提分性价比排序\n"
            for i, r in enumerate(roi_result["ranked"][:3]):
                report += f"{i+1}. {r['module']}（正确率 {r['accuracy']}%）\n"
            report += "\n"

        # 建议
        if roi_result and "suggestions" in roi_result:
            report += "### 建议\n"
            for s in roi_result["suggestions"]:
                report += f"- {s}\n"

        return report

    async def _generate_strategy_report(self, intent: Intent, province: str,
                                         roi_result: dict, all_teachers: dict,
                                         structure_result: dict) -> str:
        """模型节点：生成考前策略报告（带幻觉防御）"""

        # 第1层：清洗数据
        clean_data = self.defense.sanitize_input_data({
            "mistakes_stats": {"total": 0, "mastered": 0, "pending": 0, "modules": []},
            "speed_stats": {"stats": {"total_sessions": 0, "avg_accuracy": 0, "avg_time": 0}},
            "exams": [],
            "streak": 0,
            "teachers": all_teachers,
        })

        context = f"""考区：{province}

卷子结构：
{json.dumps(structure_result.get("modules", []) if structure_result else [], ensure_ascii=False, indent=2)}

各模块名师：
{json.dumps(all_teachers, ensure_ascii=False, indent=2)}"""

        prompt = f"""你是一个考公备考助手，叫折桂。请根据用户的情况，生成一份考前策略报告。

要求：
1. 只使用提供的真实数据，不要编造
2. 列出卷子结构（模块名和题数）
3. 列出各模块名师（只列名字和擅长领域）
4. 给出时间分配建议（基于卷子结构）
5. 语气友好

数据：
{context}

请直接输出策略报告。"""

        try:
            response = self._llm_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            report = response.choices[0].message.content

            # 第2层：输出校验
            validation = self.defense.validate_output(report, clean_data)
            if not validation["valid"]:
                return validation["cleaned_report"]

            return report

        except Exception as e:
            # 第3层：兜底报告
            return self._fallback_strategy_report(province, structure_result, all_teachers)

    def _fallback_strategy_report(self, province: str, structure_result: dict, all_teachers: dict) -> str:
        """备用考前策略报告生成"""
        report = f"## 考前策略报告（{province}卷）\n\n"

        # 卷子结构
        if structure_result and "modules" in structure_result:
            report += "### 卷子结构\n"
            for m in structure_result["modules"]:
                report += f"- {m['name']}：{m['total']}题\n"
            report += "\n"

        # 做题顺序建议
        report += "### 做题顺序建议\n"
        report += "1. 常识判断（快速过，不纠结）\n"
        report += "2. 资料分析（必须拿分）\n"
        report += "3. 言语理解（稳定输出）\n"
        report += "4. 判断推理（逻辑性强）\n"
        report += "5. 数量关系（挑会的做）\n\n"

        # 名师推荐
        if all_teachers:
            report += "### 推荐名师\n"
            for module, teachers in all_teachers.items():
                if teachers:
                    report += f"- **{module}**：{teachers[0]['name']}\n"
            report += "\n"

        report += "### 蒙题策略\n"
        report += "- 不会的题选 B 或 C（统计上概率略高）\n"
        report += "- 排除明显错误选项后再蒙\n"
        report += "- 不要空着，蒙了还有 25% 概率\n"

        return report

    async def _memory_query_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """查询持久化记忆：复盘时间、错题、速算、薄弱模块。"""
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="db.memory_profile",
            result={"session_id": session_id},
            success=True,
            reasoning="读取学情档案与历史复盘记录"
        ))
        return self._get_memory_response(session_id)

    async def _casual_chat_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """闲聊流程：允许自然语言回复，但不生成学习计划。"""
        flow_log.append(FlowStep(
            node_type="模型",
            tool_name="casual_chat",
            result={},
            success=True,
            reasoning="用户明确想闲聊，使用轻量对话而不是生成备考计划"
        ))
        prompt = f"""你是「折桂」，一个温和、克制、有考公备考气质的中文助手。
用户现在不是要学习计划，也不是要刷题分析，而是想和你闲聊。

要求：
1. 自然回应，不要输出 7 天计划、每日安排、薄弱模块分析。
2. 可以轻松聊天，但保持边界：你主要是考公备考助手。
3. 不要编造用户没有提供的个人经历。
4. 回复控制在 120 字以内。

用户：{intent.raw_message}
"""
        try:
            response = self._llm_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return "可以，我们先不聊学习。你想聊点轻松的，还是想把最近备考的压力说一说？"

    async def _study_plan_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """学习计划流程：基于已有错题/速算/模考数据生成 7 天可执行计划。"""
        mistakes_stats = db.get_mistake_stats()
        speed_stats = db.get_speed_calc_stats()
        exams = db.get_exam_history(limit=3)
        weakness = db.get_weakness_analysis()

        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="db.learning_snapshot",
            result={
                "mistakes_total": mistakes_stats.get("total", 0),
                "speed_sessions": speed_stats.get("stats", {}).get("total_sessions", 0),
                "exam_count": len(exams),
            },
            success=True,
            reasoning="读取错题、速算、模考历史，作为学习计划依据"
        ))

        modules = ["言语理解", "数量关系", "判断推理", "资料分析", "常识判断"]
        module_counts = {m: 0 for m in modules}
        for item in mistakes_stats.get("modules", []) or []:
            name = item.get("module") or item.get("name")
            if name in module_counts:
                module_counts[name] = item.get("count", 0)

        weak_modules = [m for m, _ in sorted(module_counts.items(), key=lambda x: x[1], reverse=True) if module_counts[m] > 0]
        if not weak_modules:
            weak_modules = ["资料分析", "判断推理", "言语理解"]

        teachers = {}
        for module in weak_modules[:3]:
            teachers[module] = await self._call_mcp("matcher", "teachers", {"module": module})

        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.teachers",
            result=teachers,
            success=True,
            reasoning="给薄弱模块匹配知识库内名师，避免编造老师"
        ))

        plan = self._fallback_study_plan(weak_modules, module_counts, teachers, speed_stats, exams)
        study_plan_history.add_study_plan(plan, user_id=session_id)
        return plan

    def _fallback_study_plan(self, weak_modules: list, module_counts: dict, teachers: dict, speed_stats: dict, exams: list) -> str:
        """不依赖模型的 7 天学习计划。"""
        speed_sessions = speed_stats.get("stats", {}).get("total_sessions", 0) or 0
        avg_accuracy = speed_stats.get("stats", {}).get("avg_accuracy", 0) or 0
        exam_note = f"已记录 {len(exams)} 次模考" if exams else "暂无模考记录"

        plan_modules = (weak_modules + ["资料分析", "判断推理", "言语理解", "数量关系", "常识判断"])[:7]
        report = "## 7 天备考计划\n\n"
        report += "### 依据\n"
        report += f"- 薄弱模块优先级：{'、'.join(weak_modules[:3])}\n"
        report += f"- 错题分布：{json.dumps(module_counts, ensure_ascii=False)}\n"
        report += f"- 速算练习：{speed_sessions} 次，平均正确率 {round(avg_accuracy, 1) if avg_accuracy else 0}%\n"
        report += f"- 模考记录：{exam_note}\n\n"

        report += "### 每日安排\n"
        for day in range(1, 8):
            module = plan_modules[(day - 1) % len(plan_modules)]
            report += f"**第 {day} 天：{module}**\n"
            review_count = min(3, max(module_counts.get(module, 0), 1))
            if module_counts.get(module, 0) > 0:
                report += f"- 30 分钟：复盘 {review_count} 道{module}错题，写出错因标签\n"
            else:
                report += "- 30 分钟：补 1 组基础题，记录新错题和错因标签\n"
            report += "- 45 分钟：限时专项训练，记录正确率和用时\n"
            report += "- 20 分钟：整理 1 条可复用方法或公式\n"
            if module in teachers and teachers[module].get("teacher_list"):
                first = teachers[module]["teacher_list"][0]
                report += f"- 推荐参考：{first['name']}（{first.get('speciality', '专项训练')}）\n"
            report += "\n"

        report += "### 执行规则\n"
        report += "- 每天只追一个主模块，不同时铺开多个薄弱点。\n"
        report += "- 正确率低于 60%：先看解析/方法，再刷题；高于 75%：改为限时训练。\n"
        report += "- 第 7 天结束后做一次小套卷复盘，把错题录入错题本。"
        return report

    def _handle_unknown_intent(self, user_message: str) -> str:
        """处理未知意图，返回友好提示"""
        # 越权/注入类请求：明确警告，不透露任何系统信息
        if self._is_unsafe_request(user_message):
            return "[安全提醒] 检测到异常请求。折桂是考公备考助手，仅处理学习相关的问题。如有管理需求，请通过正规管理后台操作。"

        # 通用闲聊（"上一次聊天是什么时候" 之类）
        if self._is_general_chat(user_message):
            return self._get_memory_response()

        # 检查是否是打招呼
        greetings = ["你好", "hi", "hello", "嗨", "您好", "早上好", "下午好", "晚上好"]
        if any(g in user_message.lower() for g in greetings):
            return "你好！我是折桂，你的考公备考 AI 助手。\n\n你可以告诉我：\n- 刷题数据，例如「20道言语理解对了12道」\n- 模考成绩，例如「贵州模考，资料分析15对10」\n- 考试情况，例如「快考试了，还有10天」\n\n或者上传题目图片，我来帮你分析。"

        # 检查是否是问句
        if "?" in user_message or "？" in user_message or "怎么" in user_message or "什么" in user_message:
            return "我是折桂，专注于考公备考辅导。\n\n我擅长：\n- 📊 刷题分析：输入题量和正确数，分析薄弱点\n- 📋 模考复盘：输入各模块成绩，六步复盘\n- 🎯 考前策略：输入剩余天数，制定冲刺计划\n- 📝 图片识别：上传题目图片，自动提取内容\n\n请告诉我你的学习数据，开始分析吧！"

        # 其他未知意图
        return "抱歉，我没有完全理解你的意思。\n\n请告诉我你的刷题数据，例如：\n- 「20道言语理解对了12道」\n- 「贵州模考，资料分析15对10」\n- 「快考试了，帮我安排策略」"

    def _get_memory_response(self, session_id: str = "default") -> str:
        """从持久化记忆（学情档案 + 对话历史）生成回复。"""
        import learning_profile
        from datetime import datetime
        
        profile = learning_profile.get_profile(session_id)
        parts = []
        
        # 1. 最后一次复盘时间
        last_date = profile.get("last_review_date")
        review_count = profile.get("review_count", 0)
        if last_date:
            try:
                last_dt = datetime.strptime(last_date, "%Y-%m-%d")
                delta = (datetime.now() - last_dt).days
                if delta == 0:
                    parts.append(f"上一次复盘就在今天。")
                elif delta == 1:
                    parts.append(f"上一次复盘是昨天（{last_date}）。")
                else:
                    parts.append(f"上一次复盘是 {last_date}，距今 {delta} 天。")
            except Exception:
                parts.append(f"上一次复盘：{last_date}。")
            parts.append(f"累计复盘 {review_count} 次。")
        else:
            parts.append("暂时还没有复盘记录。")
        
        # 2. 错题本情况
        mistake_total = profile.get("mistake_total", 0)
        mistake_pending = profile.get("mistake_pending", 0)
        mistake_mastered = profile.get("mistake_mastered", 0)
        if mistake_total > 0:
            parts.append(f"错题本收录 {mistake_total} 道，已掌握 {mistake_mastered} 道，待复习 {mistake_pending} 道。")
        else:
            parts.append("错题本暂无内容，开始记录错题是进步的第一步。")
        
        # 3. 薄弱模块
        weak = profile.get("weak_modules")
        if weak and len(weak) > 0:
            parts.append(f"当前薄弱模块：{'、'.join(weak[:5])}。")
        
        # 4. 速算练习
        speed_sessions = profile.get("speed_sessions", 0)
        speed_acc = profile.get("speed_avg_accuracy", 0)
        if speed_sessions > 0:
            # speed_avg_accuracy 在数据库中可能是 0.6，也可能是 60.0；统一按百分数展示。
            acc_value = float(speed_acc or 0)
            display_acc = acc_value * 100 if acc_value <= 1 else acc_value
            parts.append(f"速算练习 {speed_sessions} 次，平均正确率 {display_acc:.1f}%。")
        
        # 5. 打卡连续天数
        streak = profile.get("checkin_streak", 0)
        if streak > 0:
            parts.append(f"已连续打卡 {streak} 天{'，继续保持！' if streak >= 7 else ''}")
        
        prefix = "根据我的记忆：\n\n"
        return prefix + "\n".join(f"• {p}" for p in parts) + "\n\n有什么我可以帮你的？"

    def _dedupe_modules(self, modules: list) -> list:
        """按模块去重，保留用户最后一次输入。"""
        normalized = {}
        for item in modules or []:
            name = item.get("module")
            if not name:
                continue
            normalized[name] = {
                "module": name,
                "correct": int(item.get("correct", 0)),
                "total": int(item.get("total", 0)),
                **({"time": item["time"]} if "time" in item else {})
            }
        return list(normalized.values())

    def _missing_modules(self, expected_modules: list, provided_modules: list) -> list:
        """返回卷子结构中仍缺少或题量不匹配的模块。"""
        provided_by_name = {m.get("module"): m for m in provided_modules or []}
        missing = []
        for expected in expected_modules:
            provided = provided_by_name.get(expected.get("name"))
            if not provided or int(provided.get("total", 0)) != int(expected.get("total", 0)):
                missing.append(expected)
        return missing

    async def _mock_exam_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """模考分析流程（多轮引导模式）

        流程：
        1. 询问省份
        2. 逐个模块询问答对题数
        3. 收集完毕后生成分析报告
        """
        # 如果用户直接提供了部分/完整数据，优先保留；缺失项再引导补齐
        provided_modules = self._dedupe_modules(intent.modules or [])
        if intent.province and provided_modules:
            structure = await self._call_mcp("matcher", "exam_structure", {"province": intent.province})
            if "modules" in structure and not self._missing_modules(structure["modules"], provided_modules):
                return await self._analyze_mock_exam(intent.province, provided_modules, flow_log)
            db.save_conversation_state(session_id, "mock_exam", 2, {"province": intent.province, "modules": provided_modules})
            return await self._ask_next_module(session_id, intent.province, provided_modules, flow_log)

        # 否则开始引导流程
        province = intent.province or ""

        if not province:
            # 第一步：询问省份，同时保留用户已输入的模块成绩
            db.save_conversation_state(session_id, "mock_exam", 1, {"province": "", "modules": provided_modules})
            recorded = ""
            if provided_modules:
                recorded = "\n\n我已经先记下：\n" + "\n".join([f"- {m['module']}：{m['correct']}/{m['total']}" for m in provided_modules])
            return "好的，我来帮你做模考复盘。\n\n请问你是哪个省份的考试？\n\n可选：国考副省级、国考地市、湖北、贵州、江苏、广东、浙江" + recorded

        # 用户提供了省份，进入下一步
        db.save_conversation_state(session_id, "mock_exam", 2, {"province": province, "modules": provided_modules})
        return await self._ask_next_module(session_id, province, provided_modules, flow_log)

    async def _continue_mock_exam_flow(self, user_message: str, state: dict, flow_log: list) -> str:
        """继续模考复盘流程（多轮对话）"""
        session_id = state['session_id']
        step = state['step']
        data = state['data']
        province = data.get('province', '')
        modules = data.get('modules', [])

        if step == 1:
            # 用户回复了省份
            province = user_message.strip()
            # 验证省份是否有效
            structure = await self._call_mcp("matcher", "exam_structure", {"province": province})
            if "error" in structure:
                return f"未找到省份「{province}」，请重新输入。可选：国考副省级、国考地市、湖北、贵州、江苏、广东、浙江"

            db.save_conversation_state(session_id, "mock_exam", 2, {"province": province, "modules": modules})
            return await self._ask_next_module(session_id, province, modules, flow_log)

        elif step == 2:
            # 用户回复了答对题数
            try:
                correct = int(user_message.strip())
            except ValueError:
                return "请输入数字，例如：15"

            # 获取当前模块信息
            structure = await self._call_mcp("matcher", "exam_structure", {"province": province})
            if "modules" not in structure:
                return "获取卷子结构失败，请重新开始。"

            all_modules = structure["modules"]
            missing_modules = self._missing_modules(all_modules, modules)

            if not missing_modules:
                return await self._finish_mock_exam(session_id, province, modules, flow_log)

            current_module = missing_modules[0]
            total = current_module["total"]

            if correct < 0 or correct > total:
                return f"答对题数必须在 0-{total} 之间，请重新输入。"

            # 暂存答对题数，等待用时
            db.save_conversation_state(session_id, "mock_exam", 3, {
                "province": province,
                "modules": modules,
                "pending_module": {
                    "module": current_module["name"],
                    "correct": correct,
                    "total": total
                }
            })

            return f"**{current_module['name']}** 答对 {correct}/{total} 题\n\n这个模块用了多少分钟？（输入数字，如 25）"

        elif step == 3:
            # 用户回复了用时
            try:
                time_spent = int(user_message.strip())
            except ValueError:
                return "请输入数字，例如：25"

            pending = data.get("pending_module", {})
            if not pending:
                return "流程异常，请重新开始。"

            # 记录这个模块（包含用时）
            modules.append({
                "module": pending["module"],
                "correct": pending["correct"],
                "total": pending["total"],
                "time": time_spent
            })

            # 查询下一个模块
            structure = await self._call_mcp("matcher", "exam_structure", {"province": province})
            all_modules = structure.get("modules", [])
            missing_modules = self._missing_modules(all_modules, modules)

            if missing_modules:
                db.save_conversation_state(session_id, "mock_exam", 2, {"province": province, "modules": modules})
                return await self._ask_next_module(session_id, province, modules, flow_log)
            else:
                return await self._finish_mock_exam(session_id, province, modules, flow_log)

        return "流程异常，请重新开始模考复盘。"

    async def _ask_next_module(self, session_id: str, province: str, modules: list, flow_log: list) -> str:
        """询问下一个模块的答对题数"""
        structure = await self._call_mcp("matcher", "exam_structure", {"province": province})

        if "modules" not in structure:
            return "获取卷子结构失败，请稍后重试。"

        all_modules = structure["modules"]
        missing_modules = self._missing_modules(all_modules, modules)

        if not missing_modules:
            return await self._finish_mock_exam(session_id, province, modules, flow_log)

        current_module = missing_modules[0]
        total = current_module["total"]
        name = current_module["name"]

        # 构造进度提示
        completed = len(all_modules) - len(missing_modules)
        progress = f"({completed + 1}/{len(all_modules)})"
        already = ""
        if modules:
            already = "\n\n已记录：\n" + "\n".join([f"  ✅ {m['module']}: {m['correct']}/{m['total']}（{m.get('time', '?')}分钟）" for m in modules])
        missing_names = "、".join([m["name"] for m in missing_modules])

        return f"还需要补充或确认这些模块：{missing_names}\n\n**{name}**（共 {total} 题）{progress}\n\n答对几题？{already}"

    async def _finish_mock_exam(self, session_id: str, province: str, modules: list, flow_log: list) -> str:
        """完成数据收集，生成分析报告"""
        # 清除对话状态
        db.clear_conversation_state(session_id)
        modules = self._dedupe_modules(modules)

        # 保存模考记录到数据库
        total_correct = sum(m["correct"] for m in modules)
        total_questions = sum(m["total"] for m in modules)
        total_score = round(total_correct / total_questions * 100, 1) if total_questions > 0 else 0

        db.add_exam(province, total_score, {m["module"]: m["correct"] for m in modules})

        # 生成分析报告
        return await self._analyze_mock_exam(province, modules, flow_log)

    async def _analyze_mock_exam(self, province: str, modules_data: list, flow_log: list) -> str:
        """执行模考分析（数据收集完毕后调用）"""
        modules_data = self._dedupe_modules(modules_data)

        # ① 代码节点：逐项校验
        for m in modules_data:
            check_result = await self._call_mcp("validator", "check_data", {
                "correct": m.get("correct", 0),
                "total": m.get("total", 0),
                "module": m.get("module", "")
            })
            flow_log.append(FlowStep(
                node_type="代码",
                tool_name="validator.check_data",
                result=check_result,
                success=check_result.get("status") == "pass"
            ))

        # ② 代码节点：查询卷子结构
        structure_result = await self._call_mcp("matcher", "exam_structure", {"province": province})
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.exam_structure",
            result=structure_result,
            success="modules" in structure_result
        ))

        # ③ 代码节点：计算每模块正确率
        accuracy_results = []
        for m in modules_data:
            acc_result = await self._call_mcp("calc", "accuracy", {
                "correct": m.get("correct", 0),
                "total": m.get("total", 0)
            })
            acc_result["module"] = m.get("module", "")
            accuracy_results.append(acc_result)
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="calc.accuracy",
            result=accuracy_results,
            success=True
        ))

        # ④ 代码节点：计算性价比排序
        roi_result = await self._call_mcp("calc", "roi", {
            "modules_data": [
                {"module": m["module"], "correct": m["correct"], "total": m["total"]}
                for m in modules_data
            ]
        })
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="calc.roi",
            result=roi_result,
            success="ranked" in roi_result
        ))

        # ⑤ 代码节点：查询用时标准
        time_results = {}
        for m in modules_data:
            time_result = await self._call_mcp("matcher", "time_standard", {"module": m["module"]})
            time_results[m["module"]] = time_result
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.time_standard",
            result=time_results,
            success=True
        ))

        # ⑥ 模型节点：生成分析报告
        report = await self._generate_mock_report(
            Intent(type="mock_exam", module="", correct=0, total=0, province=province, modules=modules_data, raw_message=""),
            province, modules_data, accuracy_results, roi_result, time_results, structure_result
        )
        flow_log.append(FlowStep(
            node_type="模型",
            tool_name="生成模考分析报告",
            result=report[:100] + "...",
            success=True
        ))

        return report

    async def _strategy_flow(self, intent: Intent, flow_log: list, session_id: str = "default") -> str:
        """考前策略流程

        流程路径（代码硬编码）：
        ① 代码：calc-mcp roi(历史数据) → 提分性价比排序
        ② 代码：matcher-mcp teachers(各薄弱模块) → 推荐老师
        ③ 代码：matcher-mcp exam_structure(考区) → 卷子结构 + 时间分配
        ④ 模型：生成考前策略
        """
        province = intent.province or "国考副省级"

        # ① 代码节点：计算性价比（如果有历史数据）
        # 注：历史数据从持久化文件读取，此处简化为使用当前 session 数据
        roi_result = None
        if intent.modules:
            roi_result = await self._call_mcp("calc", "roi", {
                "modules_data": intent.modules
            })
            flow_log.append(FlowStep(
                node_type="代码",
                tool_name="calc.roi",
                result=roi_result,
                success="ranked" in roi_result
            ))

        # ② 代码节点：查询各模块名师
        all_teachers = {}
        for module in ["言语理解", "数量关系", "判断推理", "资料分析", "常识判断"]:
            teachers_result = await self._call_mcp("matcher", "teachers", {
                "module": module
            })
            if "teacher_list" in teachers_result:
                all_teachers[module] = teachers_result["teacher_list"]
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.teachers(全模块)",
            result=all_teachers,
            success=len(all_teachers) > 0
        ))

        # ③ 代码节点：查询卷子结构
        structure_result = await self._call_mcp("matcher", "exam_structure", {
            "province": province
        })
        flow_log.append(FlowStep(
            node_type="代码",
            tool_name="matcher.exam_structure",
            result=structure_result,
            success="modules" in structure_result
        ))

        # ④ 模型节点：生成考前策略
        report = await self._generate_strategy_report(
            intent, province, roi_result, all_teachers, structure_result
        )
        flow_log.append(FlowStep(
            node_type="模型",
            tool_name="生成考前策略",
            result=report[:100] + "...",
            success=True
        ))

        return report

    async def _get_lock(self):
        """获取或创建 MCP 调用锁"""
        if self._mcp_lock is None:
            self._mcp_lock = asyncio.Lock()
        return self._mcp_lock

    async def _call_mcp(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """调用 MCP Server 的工具

        Args:
            server_name: Server 名称（calc/matcher/validator）
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具返回的结果
        """
        # 优先走进程内本地工具，避免每次调用都启动 MCP 子进程；失败时再回退到 MCP。
        try:
            local_result = local_tools.call_tool(server_name, tool_name, arguments)
            if local_result is not None:
                return local_result
        except Exception as e:
            # 本地工具异常时保留原 MCP 兜底路径。
            print(f"本地工具调用失败，回退 MCP: {server_name}.{tool_name}: {e}")

        server_params = self.server_params.get(server_name)
        if not server_params:
            return {"error": f"未知的 MCP Server: {server_name}"}

        # 检查熔断器
        if not self._check_circuit_breaker(server_name):
            return {"error": f"MCP Server {server_name} 已熔断，请稍后重试"}

        # 获取锁
        lock = await self._get_lock()

        # 使用锁确保同一时间只有一个 MCP 调用
        async with lock:
            # 重试逻辑（最多重试 1 次）
            for attempt in range(2):
                try:
                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(tool_name, arguments)

                            # 检查返回内容是否有效
                            if not result.content or not result.content[0].text:
                                return {"error": "MCP 返回空内容", "degraded": True}

                            # 检查是否是错误消息
                            text = result.content[0].text
                            if text.startswith("Error executing tool"):
                                return {"error": text, "degraded": True}

                            # 成功则重置熔断器
                            if server_name in self._circuit_breaker:
                                self._circuit_breaker[server_name]["failures"] = 0
                            return json.loads(text)
                except Exception as e:
                    if attempt == 0:
                        # 第一次失败，重试
                        continue
                    # 第二次失败，记录并降级
                    self._record_failure(server_name)
                    return {"error": f"MCP 调用失败: {str(e)}", "degraded": True}


async def main():
    """测试混合引擎"""
    engine = HybridEngine()

    test_messages = [
        "我今天刷了20道言语理解，对了12道",
        "数量关系做了15道，只对了5道",
        "资料分析20道对了18道",
    ]

    for msg in test_messages:
        print(f"\n{'='*50}")
        print(f"用户：{msg}")
        print(f"{'='*50}")

        result = await engine.process(msg)

        print(f"\n折桂：\n{result['response']}")
        print(f"\n流程日志：")
        for step in result["flow_log"]:
            print(f"  [{step.node_type}] {step.tool_name} {'✓' if step.success else '✗'}")


if __name__ == "__main__":
    asyncio.run(main())
