"""
折桂 — FastAPI 后端
将混合引擎暴露为 HTTP API
"""

import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from hybrid_engine import HybridEngine
import database as db
import speed_calc
import model_router
from hallucination_defense import HallucinationDefense
from metrics import get_metrics_summary, record_llm_call, usage_from_response
from recovery import with_retry, classify_error
import os

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
from budget import BudgetRegistry
import learning_profile
import study_plan_history

# 初始化
app = FastAPI(title="折桂 API", version="1.0.0")
engine = HybridEngine()

# CORS（允许前端访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求/响应模型
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    flow_log: list
    intent: dict = None
    stats: dict = None
    meta: dict = None


# 累计统计
_stats = {"code_calls": 0, "model_calls": 0, "tokens_saved": 0}
budget_registry = BudgetRegistry()
ADMIN_PASSWORD = os.getenv("ZHEGUI_ADMIN_PASSWORD", "123456")


def _check_admin_password(password: Optional[str]):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="管理员口令错误")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """处理用户消息"""
    result = await engine.process(req.message, req.session_id)

    # 转换 flow_log
    flow_log = [
        {"node_type": s.node_type, "tool_name": s.tool_name, "success": s.success, "reasoning": s.reasoning}
        for s in result["flow_log"]
    ]

    # 更新统计
    code = sum(1 for s in flow_log if s["node_type"] == "代码")
    model = sum(1 for s in flow_log if s["node_type"] == "模型")
    _stats["code_calls"] += code
    _stats["model_calls"] += model
    _stats["tokens_saved"] += code * 800

    budget_meta = budget_registry.check_turn(req.session_id, req.message, result["response"])
    if result.get("intent") and result["intent"].type in ["daily_practice", "mock_exam", "pre_exam_strategy", "study_plan"]:
        learning_profile.mark_review(req.session_id, result["intent"].type)
        learning_profile.refresh_profile_from_learning_data(req.session_id)

    return ChatResponse(
        response=result["response"],
        flow_log=flow_log,
        intent=result["intent"].__dict__ if result["intent"] else None,
        stats=dict(_stats),
        meta={"budget": budget_meta},
    )


@app.get("/api/profile")
async def get_profile(session_id: str = "default"):
    """获取当前用户学情档案"""
    return learning_profile.refresh_profile_from_learning_data(session_id)


@app.post("/api/profile/refresh")
async def refresh_profile(session_id: str = "default", province: Optional[str] = None):
    """手动刷新学情档案"""
    return learning_profile.refresh_profile_from_learning_data(session_id, province=province)


@app.get("/api/study-plans")
async def list_study_plans(session_id: str = "default"):
    """学习计划历史"""
    return {"plans": study_plan_history.list_study_plans(session_id)}


@app.get("/api/study-plans/latest")
async def latest_study_plan(session_id: str = "default"):
    return {"plan": study_plan_history.get_latest_plan(session_id)}


@app.delete("/api/study-plans/{plan_id}")
async def delete_study_plan(plan_id: int):
    ok = study_plan_history.delete_study_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return {"message": "学习计划已删除"}


@app.post("/api/study-plans/{plan_id}/days/{day}/done")
async def mark_study_plan_day_done(plan_id: int, day: int):
    result = study_plan_history.mark_day_done(plan_id, day)
    if not result:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return {"message": "已标记完成", "plan": result}


@app.delete("/api/study-plans/{plan_id}/days/{day}/done")
async def unmark_study_plan_day_done(plan_id: int, day: int):
    result = study_plan_history.mark_day_undone(plan_id, day)
    if not result:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return {"message": "已取消完成", "plan": result}


@app.post("/api/study-plans/{plan_id}/days/{day}/toggle")
async def toggle_study_plan_day_done(plan_id: int, day: int):
    result = study_plan_history.toggle_day_done(plan_id, day)
    if not result:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return {"message": "已更新进度", "plan": result}


@app.get("/api/stats")
async def get_stats():
    """获取累计统计"""
    return dict(_stats)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/admin/overview")
async def admin_overview(x_admin_password: Optional[str] = Header(default=None)):
    """管理员总览：Token/调用统计 + 学习数据统计"""
    _check_admin_password(x_admin_password)
    mistakes_stats = db.get_mistake_stats()
    speed_stats = db.get_speed_calc_stats()
    exams = db.get_exam_history(limit=100)
    reports = db.get_reports(limit=100)
    return {
        "runtime": dict(_stats),
        "llm_metrics": get_metrics_summary(),
        "budget": budget_registry.summary(),
        "profile": learning_profile.get_profile(),
        "mistakes": mistakes_stats,
        "speed_calc": speed_stats.get("stats", {}),
        "exam_count": len(exams),
        "report_count": len(reports),
        "admin_password_default": ADMIN_PASSWORD == "123456"
    }


# ========== 管理员 API ==========

@app.post("/api/admin/clear-all")
async def clear_all_data(x_admin_password: Optional[str] = Header(default=None)):
    """清空所有数据（管理员功能）"""
    _check_admin_password(x_admin_password)
    conn = db.get_connection()
    cursor = conn.cursor()

    tables = ['mistakes', 'mistake_attempts', 'speed_calc', 'checkin', 'exam_history', 'reports', 'conversation_state', 'learning_profile', 'llm_calls', 'study_plans']
    cleared = {}

    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        cursor.execute(f"DELETE FROM {table}")
        cleared[table] = count

    conn.commit()
    conn.close()
    budget_registry.reset()

    return {"message": "所有数据已清空", "cleared": cleared}


# ========== 错题本 API ==========

class MistakeCreate(BaseModel):
    module: str
    question: str
    correct_answer: str
    user_answer: Optional[str] = None
    options: Optional[list] = None
    explanation: Optional[str] = None
    error_type: Optional[str] = None
    source: str = "manual"


class MistakeUpdate(BaseModel):
    module: Optional[str] = None
    question: Optional[str] = None
    correct_answer: Optional[str] = None
    user_answer: Optional[str] = None
    options: Optional[list] = None
    explanation: Optional[str] = None
    error_type: Optional[str] = None


class MistakeStatusUpdate(BaseModel):
    status: str  # pending / mastered / review


class MistakeAttempt(BaseModel):
    is_correct: bool
    time_spent: Optional[float] = None  # 用时（秒）


@app.post("/api/mistakes")
async def create_mistake(req: MistakeCreate):
    """添加错题"""
    mistake_id = db.add_mistake(
        module=req.module,
        question=req.question,
        correct_answer=req.correct_answer,
        user_answer=req.user_answer,
        options=req.options,
        explanation=req.explanation,
        error_type=req.error_type,
        source=req.source
    )
    return {"id": mistake_id, "message": "添加成功"}


@app.get("/api/mistakes")
async def list_mistakes(
    module: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """查询错题列表（分页 + 搜索）"""
    return db.get_mistakes(module=module, status=status, search=search, page=page, page_size=page_size)


@app.post("/api/mistakes/{mistake_id}/expand-practice")
async def expand_practice_mistake(mistake_id: int):
    """把旧版单条刷题占位错题扩展为按错题数生成的多张待补全题卡。"""
    import re
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM mistakes WHERE id = ?", (mistake_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="错题不存在")
    m = dict(row)
    match = re.search(r"（(\d+)/(\d+)）", m.get("question") or "")
    if not match:
        raise HTTPException(status_code=400, detail="无法从题卡中识别本次正确数/总题数")
    correct, total = int(match.group(1)), int(match.group(2))
    wrong_count = max(total - correct, 1)

    # 如果已经是 1/N 格式，认为已展开。
    if re.search(r"刷题错题\s+\d+/\d+", m.get("question") or ""):
        return {"message": "这条错题已经按错题数展开", "created": 0, "expected": wrong_count}

    # 将原卡改成第 1 张，再补齐剩余卡。
    db.update_mistake(
        mistake_id,
        question=f"{m['module']}刷题错题 1/{wrong_count}（{correct}/{total}）"
    )
    created = 0
    for i in range(2, wrong_count + 1):
        db.add_mistake(
            module=m["module"],
            question=f"{m['module']}刷题错题 {i}/{wrong_count}（{correct}/{total}）",
            correct_answer="",
            explanation=m.get("explanation"),
            error_type=m.get("error_type"),
            source=m.get("source") or "practice"
        )
        created += 1
    return {"message": f"已补齐 {created} 张待补全题卡", "created": created, "expected": wrong_count}


@app.put("/api/mistakes/{mistake_id}")
async def update_mistake(mistake_id: int, req: MistakeUpdate):
    """补全/编辑错题内容"""
    result = db.update_mistake(
        mistake_id=mistake_id,
        module=req.module,
        question=req.question,
        correct_answer=req.correct_answer,
        user_answer=req.user_answer,
        options=req.options,
        explanation=req.explanation,
        error_type=req.error_type,
    )
    if result:
        return {"message": "错题已更新", "mistake": result}
    raise HTTPException(status_code=404, detail="错题不存在")


@app.put("/api/mistakes/{mistake_id}/status")
async def update_mistake_status(mistake_id: int, req: MistakeStatusUpdate):
    """更新错题状态"""
    db.update_mistake_status(mistake_id, req.status)
    return {"message": "状态已更新"}


@app.post("/api/mistakes/{mistake_id}/attempt")
async def attempt_mistake(mistake_id: int, req: MistakeAttempt):
    """记录一次作答"""
    result = db.attempt_mistake(mistake_id, req.is_correct, req.time_spent)
    if result:
        return {"message": "记录成功", "mistake": result}
    raise HTTPException(status_code=404, detail="错题不存在")


@app.get("/api/mistakes/stats")
async def get_mistake_stats():
    """获取错题统计"""
    return db.get_mistake_stats()


# ========== 速算记录 API ==========

class SpeedCalcSubmit(BaseModel):
    correct_count: int
    total_count: int
    avg_time: float
    questions: list


@app.post("/api/speed-calc")
async def submit_speed_calc(req: SpeedCalcSubmit):
    """提交速算记录"""
    record_id = db.add_speed_calc(
        correct_count=req.correct_count,
        total_count=req.total_count,
        avg_time=req.avg_time,
        questions=req.questions
    )
    return {"id": record_id, "message": "记录已保存"}


@app.get("/api/speed-calc/stats")
async def get_speed_calc_stats():
    """获取速算统计"""
    return db.get_speed_calc_stats()


@app.get("/api/speed-calc/history")
async def get_speed_calc_history(days: int = 30):
    """获取速算历史"""
    return {"history": db.get_speed_calc_history(days)}


@app.get("/api/speed-calc/generate")
async def generate_speed_calc(count: int = 10):
    """生成速算练习题"""
    questions = speed_calc.generate_session(count)
    return {"questions": questions, "count": len(questions)}


# ========== 打卡 API ==========

@app.get("/api/checkin/streak")
async def get_streak():
    """获取连续打卡天数"""
    return {"streak": db.get_checkin_streak()}


@app.get("/api/checkin/history")
async def get_checkin_history(days: int = 30):
    """获取打卡历史"""
    return {"history": db.get_checkin_history(days)}


# ========== 模考历史 API ==========

class ExamCreate(BaseModel):
    province: str
    total_score: float
    module_scores: dict


@app.post("/api/exams")
async def create_exam(req: ExamCreate):
    """添加模考记录"""
    exam_id = db.add_exam(req.province, req.total_score, req.module_scores)
    return {"id": exam_id, "message": "模考记录已保存"}


@app.get("/api/exams")
async def list_exams(limit: int = 10):
    """获取模考历史"""
    return {"exams": db.get_exam_history(limit)}


# ========== 报告 API ==========

class ReportCreate(BaseModel):
    content: str
    type: str = "weekly"


@app.post("/api/reports")
async def create_report(req: ReportCreate):
    """添加报告"""
    report_id = db.add_report(req.content, req.type)
    return {"id": report_id, "message": "报告已保存"}


@app.get("/api/reports")
async def list_reports(limit: int = 10):
    """获取报告列表"""
    return {"reports": db.get_reports(limit)}


# ========== 政治理论 API ==========

# 加载政治理论知识库
POLITICAL_THEORY_PATH = Path(__file__).parent / "references" / "political_theory.json"
_political_theory = None


def _load_political_theory():
    """加载政治理论知识库"""
    global _political_theory
    if _political_theory is None:
        with open(POLITICAL_THEORY_PATH, "r", encoding="utf-8") as f:
            _political_theory = json.load(f)
    return _political_theory


@app.get("/api/political-theory/categories")
async def get_categories():
    """获取政治理论分类列表"""
    data = _load_political_theory()
    categories = [
        {"id": c["id"], "name": c["name"], "icon": c["icon"], "count": len(c["topics"])}
        for c in data["categories"]
    ]
    return {"categories": categories}


@app.get("/api/political-theory/topics")
async def get_topics(category_id: Optional[str] = None):
    """获取知识点列表"""
    data = _load_political_theory()

    if category_id:
        category = next((c for c in data["categories"] if c["id"] == category_id), None)
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")
        return {"category": category["name"], "topics": category["topics"]}

    # 返回所有知识点
    all_topics = []
    for c in data["categories"]:
        for t in c["topics"]:
            all_topics.append({**t, "category": c["name"], "category_id": c["id"]})
    return {"topics": all_topics}


@app.get("/api/political-theory/search")
async def search_topics(q: str = Query(..., min_length=1)):
    """搜索知识点"""
    data = _load_political_theory()
    results = []

    for c in data["categories"]:
        for t in c["topics"]:
            # 搜索标题、内容、关键词
            if (q.lower() in t["title"].lower() or
                q.lower() in t["content"].lower() or
                any(q.lower() in kw.lower() for kw in t["keywords"])):
                results.append({**t, "category": c["name"], "category_id": c["id"]})

    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/political-theory/random")
async def get_random_topic():
    """随机获取一个知识点（用于随机一题模式）"""
    import random as _rnd
    data = _load_political_theory()

    all_topics = []
    for c in data["categories"]:
        for t in c["topics"]:
            all_topics.append({**t, "category": c["name"]})

    if not all_topics:
        raise HTTPException(status_code=404, detail="知识库为空")

    topic = random.choice(all_topics)
    return {"topic": topic}


# ========== 图片题目导入 API ==========

class ImageUpload(BaseModel):
    image_base64: str
    prompt: str = ""


@app.post("/api/extract-question")
async def extract_question(req: ImageUpload):
    """从图片提取题目（路由到 mimo-v2.5 识别图片）"""
    result = model_router.image_recognition(req.image_base64, req.prompt)
    return result


# ========== 数据看板 API ==========

class ExamTarget(BaseModel):
    province: str
    exam_date: str  # YYYY-MM-DD


@app.get("/api/dashboard")
async def get_dashboard(province: Optional[str] = None, exam_date: Optional[str] = None):
    """获取数据看板数据"""
    from datetime import datetime, timedelta

    today = datetime.now().date()

    # 1. 倒计时
    days_left = None
    if exam_date:
        try:
            target = datetime.strptime(exam_date, '%Y-%m-%d').date()
            days_left = (target - today).days
        except:
            pass

    # 2. 连续打卡天数
    streak = db.get_checkin_streak()

    # 3. 本周错题统计
    mistakes_stats = db.get_mistake_stats()

    # 4. 速算统计
    speed_stats = db.get_speed_calc_stats()

    # 5. 模考成绩趋势
    exams = db.get_exam_history(limit=5)

    # 6. 今日速算状态
    today_speed = speed_stats.get('today', [])
    today_speed_done = len(today_speed) > 0

    # 7. 今日打卡状态
    checkin_history = db.get_checkin_history(days=1)
    today_checkin = len(checkin_history) > 0

    return {
        "exam": {
            "province": province,
            "exam_date": exam_date,
            "days_left": days_left
        },
        "streak": streak,
        "mistakes": {
            "total": mistakes_stats['total'],
            "mastered": mistakes_stats['mastered'],
            "pending": mistakes_stats['pending'],
            "modules": mistakes_stats['modules']
        },
        "speed_calc": {
            "today_done": today_speed_done,
            "today_accuracy": today_speed[0]['correct_count'] / today_speed[0]['total_count'] * 100 if today_speed else None,
            "total_sessions": speed_stats['stats']['total_sessions'],
            "avg_accuracy": speed_stats['stats']['avg_accuracy'],
            "trend": speed_stats['trend']
        },
        "exams": [
            {
                "date": e['date'],
                "province": e['province'],
                "total_score": e['total_score'],
                "module_scores": json.loads(e['module_scores']) if isinstance(e['module_scores'], str) else e['module_scores']
            }
            for e in exams
        ],
        "today": {
            "checkin": today_checkin,
            "speed_calc_done": today_speed_done,
            "mistakes_added": 0  # TODO: 统计今日新增错题
        }
    }



# ========== 看板图表数据 API ==========

@app.get("/api/dashboard/chart-data")
async def get_chart_data():
    """返回数据看板图表所需的全部数据"""
    from datetime import datetime, timedelta
    today = datetime.now().date()

    mistakes_stats = db.get_mistake_stats()
    speed_stats = db.get_speed_calc_stats()
    streak = db.get_checkin_streak()
    exams = db.get_exam_history(limit=5)
    weakness_data = db.get_weakness_analysis()
    weakness = weakness_data["weakness_by_module"]

    exam_date_str = os.getenv("EXAM_DATE", "2026-11-29")
    try:
        exam_date = datetime.strptime(exam_date_str, "%Y-%m-%d").date()
        days_left = (exam_date - today).days
    except:
        days_left = None

    total_mistakes = mistakes_stats["total"]
    mastered = mistakes_stats["mastered"]
    total_accuracy = round(mastered / total_mistakes * 100, 1) if total_mistakes > 0 else 0
    total_sessions = speed_stats["stats"]["total_sessions"] or 0

    stats = [
        {"label": "累计刷题", "value": str(total_mistakes + total_sessions), "unit": "道", "sub": "总刷题量", "accent": False, "prominent": False},
        {"label": "整体正确率", "value": str(total_accuracy), "unit": "%", "sub": "已掌握 " + str(mastered) + " / " + str(total_mistakes), "trend": "up" if total_accuracy >= 60 else "down", "trendVal": ""},
        {"label": "连续打卡", "value": str(streak), "unit": "天", "sub": "每日速算即打卡", "accent": True, "prominent": False},
        {"label": "距考试", "value": str(days_left) if days_left else "—", "unit": "天", "sub": "锁定 " + exam_date_str, "accent": False, "prominent": True}
    ]

    modules_order = ["言语理解", "判断推理", "资料分析", "数量关系", "常识判断"]

    radar_scores = []
    for mod in modules_order:
        ms = next((m for m in weakness if m["module"] == mod), None)
        rate = round(ms["mastery_rate"] * 100, 1) if ms and ms["total"] > 0 else 0
        radar_scores.append(rate)

    heatmap_data = []
    checkin_history = db.get_checkin_history(days=90)
    checkin_dates = {c["date"]: c for c in checkin_history}
    for i in range(89, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        count = max(1, checkin_dates[ds].get("duration_minutes", 0) // 5) if ds in checkin_dates else 0
        heatmap_data.append([ds, count])

    dates_30 = []
    questions_30 = []
    accuracy_30 = []
    speed_trend = speed_stats.get("trend") or []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        dates_30.append(d.strftime("%m-%d"))
        ds = d.strftime("%Y-%m-%d")
        day_s = [s for s in speed_trend if s.get("date") == ds]
        if day_s:
            acc = round(day_s[0].get("accuracy", 0), 1)
            q = day_s[0].get("total", day_s[0].get("questions", 0))
        else:
            acc = 0
            q = 0
        questions_30.append(q)
        accuracy_30.append(acc)

    mod_names = []
    mod_acc = []
    for mod in modules_order:
        ms = next((m for m in weakness if m["module"] == mod), None)
        mod_names.append(mod)
        mod_acc.append(round(ms["mastery_rate"] * 100, 1) if ms and ms["total"] > 0 else 0)

    import random as _rnd
    sub_map = {
        "言语理解": ["片段阅读", "语句表达", "逻辑填空"],
        "数量关系": ["数字推理", "数学运算", "工程问题"],
        "判断推理": ["图形推理", "定义判断", "类比推理", "逻辑判断"],
        "资料分析": ["增长量", "增长率", "比重", "倍数"],
        "常识判断": ["政治常识", "法律常识", "经济常识", "文史常识"]
    }
    knowledge = []
    for mod in modules_order:
        ms = next((m for m in weakness if m["module"] == mod), None)
        base = round(ms["mastery_rate"], 2) if ms and ms["total"] > 0 else 0.5
        for sub in sub_map.get(mod, []):
            rng = _rnd.Random(mod + sub)
            mastery = max(0.1, min(1.0, base + rng.uniform(-0.15, 0.15)))
            knowledge.append({"module": mod, "name": sub, "mastery": round(mastery, 2)})

    worst = sorted(weakness, key=lambda x: x["mastery_rate"])[0] if weakness else None
    point_map = {"言语理解":"逻辑填空","数量关系":"数学运算","判断推理":"逻辑判断","资料分析":"比重","常识判断":"法律常识"}
    rec = {
        "module": worst["module"] if worst else "资料分析",
        "point": point_map.get(worst["module"] if worst else "", "综合分析"),
        "accuracy": round(worst["mastery_rate"] * 100, 1) if worst else 70,
        "questionCount": 15,
        "estimatedTime": "30 分钟"
    }

    return {
        "stats": stats,
        "radar": {"dimensions": modules_order, "scores": radar_scores, "max": 100},
        "trend": {"dates": dates_30, "questions": questions_30, "accuracy": accuracy_30},
        "modules": {"names": mod_names, "accuracy": mod_acc},
        "knowledge": knowledge,
        "recommendation": rec,
        "heatmap": heatmap_data
    }

# ========== 私人定制 Agent API ==========

@app.post("/api/reports/generate")
async def generate_report():
    """生成个人分析报告（私人定制 Agent）"""
    from openai import OpenAI
    import os
    from datetime import datetime

    # 初始化幻觉防御
    defense = HallucinationDefense()

    # 聚合数据
    mistakes_stats = db.get_mistake_stats()
    speed_stats = db.get_speed_calc_stats()
    exams = db.get_exam_history(limit=5)
    streak = db.get_checkin_streak()
    weakness_data = db.get_weakness_analysis()
    weakness = weakness_data["weakness_by_module"]

    # ========== 数据阈值检查 ==========
    THRESHOLDS = {
        "mistakes_min": 3,
        "speed_calc_min": 2,
        "exams_min": 1,
    }

    missing = []
    if mistakes_stats['total'] < THRESHOLDS['mistakes_min']:
        missing.append(f"错题数量（当前 {mistakes_stats['total']} 道，需要至少 {THRESHOLDS['mistakes_min']} 道）")
    if (speed_stats['stats']['total_sessions'] or 0) < THRESHOLDS['speed_calc_min']:
        missing.append(f"速算练习（当前 {speed_stats['stats']['total_sessions'] or 0} 次，需要至少 {THRESHOLDS['speed_calc_min']} 次）")
    if len(exams) < THRESHOLDS['exams_min']:
        missing.append(f"模考记录（当前 {len(exams)} 次，需要至少 {THRESHOLDS['exams_min']} 次）")

    if missing:
        return {
            "id": None,
            "content": f"📊 **数据不足，暂无法生成分析报告**\n\n为了生成有价值的个性化报告，还需要更多数据：\n\n" + "\n".join([f"- ❌ {m}" for m in missing]) + "\n\n请先完成以下任务后再试：\n- 📝 添加错题（错题本 → 添加错题）\n- ⚡ 完成速算练习\n- 📋 完成一次模考复盘",
            "date": datetime.now().strftime('%Y-%m-%d'),
            "threshold_met": False
        }

    # 获取名师数据
    all_teachers = {}
    for module in ["言语理解", "数量关系", "判断推理", "资料分析", "常识判断"]:
        try:
            teachers_result = await engine._call_mcp("matcher", "teachers", {"module": module})
            if "teacher_list" in teachers_result:
                all_teachers[module] = teachers_result["teacher_list"]
        except:
            pass

    # ========== 第1层：输入层 · 数据清洗 ==========
    clean_data = defense.sanitize_input_data({
        "mistakes_stats": mistakes_stats,
        "speed_stats": speed_stats,
        "exams": exams,
        "streak": streak,
        "teachers": all_teachers,
        "weakness": weakness
    })

    # 构造上下文（使用清洗后的数据）
    context = f"""=== 真实数据（直接使用，不要修改） ===

【错题数据】
- 总错题数：{clean_data['mistakes']['total']} 道
- 已掌握：{clean_data['mistakes']['mastered']} 道
- 待复习：{clean_data['mistakes']['pending']} 道
- 各模块错题分布：{json.dumps(clean_data['mistakes']['modules'], ensure_ascii=False)}

【薄弱点数据】
- 各模块错误统计：{json.dumps(clean_data['weakness']['by_module'], ensure_ascii=False)}
- 高频错误类型：{json.dumps(clean_data['weakness']['common_errors'], ensure_ascii=False) if clean_data['weakness']['common_errors'] else '暂无数据'}
- 各模块平均用时：{json.dumps(clean_data['weakness']['time_by_module'], ensure_ascii=False) if clean_data['weakness']['time_by_module'] else '暂无数据'}

【速算数据】
- 总练习次数：{clean_data['speed_calc']['total_sessions']} 次
- 平均正确率：{clean_data['speed_calc']['avg_accuracy']}%
- 平均用时：{clean_data['speed_calc']['avg_time']}秒

【模考数据】
- 模考次数：{len(clean_data['exams'])} 次
{chr(10).join([f'  - {e["date"]} {e["province"]}卷 总分{e["total_score"]}' for e in clean_data['exams']]) if clean_data['exams'] else '  - 暂无模考记录'}

【打卡数据】
- 连续打卡：{clean_data['streak']} 天

【名师数据】（只使用这里列出的老师，不要编造）
{json.dumps(clean_data['teachers'], ensure_ascii=False, indent=2)}

=== 以上数据全部真实，不要编造任何额外数据 ==="""

    prompt = f"""你是一个考公备考助手，叫折桂。请根据用户的真实学习数据，生成一份分析报告。

【严格要求】
1. 只使用下面提供的真实数据，不要编造任何数据
2. 如果某项数据为空或为0，直接说明"暂无数据"，不要猜测
3. 所有数字必须与提供的数据完全一致
4. 不要夸大或缩小任何数据
5. 【禁止解读】不要分析原因、不要猜测用户心理、不要评价好坏
6. 【禁止编造建议】不要给出没有数据支撑的建议（如"放在前半段"）
7. 只陈述事实，不发表观点

【报告结构】
1. **学习概况**：用表格展示真实数据（只列数字，不评价）
2. **错题数据**：
   - 各模块错题数量（从多到少排列）
   - 高频错误类型（直接列出，不分析原因）
3. **速算数据**：
   - 总次数、平均正确率、平均用时（只列数字）
4. **模考总结**：
   - 各次模考成绩（只列日期、省份、分数）
   - 如果有多次，列出最高分、最低分、平均分
5. **时间数据**：
   - 连续打卡天数
   - 速算平均用时
6. **薄弱模块**：错题最多的模块（只说哪个模块，不解释为什么）
7. **推荐名师**：基于薄弱模块，列出对应名师（只列名字和擅长领域）
8. **鼓励**：一句话鼓励，不要长篇大论

【真实数据】
{context}

请直接输出分析报告。"""

    # ========== 第2层：输出层 · 生成并校验 ==========
    try:
        llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-placeholder"),
            base_url="https://api.deepseek.com"
        )
        import time
        start = time.perf_counter()
        try:
            response = with_retry(lambda: llm.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            ))
            input_tokens, output_tokens = usage_from_response(response)
            record_llm_call(DEEPSEEK_MODEL, (time.perf_counter() - start) * 1000, input_tokens, output_tokens, "success")
        except Exception as llm_error:
            error_type = classify_error(llm_error)
            record_llm_call(DEEPSEEK_MODEL, (time.perf_counter() - start) * 1000, 0, 0, "failed", error_type)
            raise
        report_content = response.choices[0].message.content

        # 输出校验
        validation = defense.validate_output(report_content, clean_data)
        if not validation["valid"]:
            print(f"[幻觉防御] 检测到违规: {validation['violations']}")
            # 使用清洗后的报告
            report_content = validation["cleaned_report"]

    except Exception as e:
        # ========== 第3层：系统层 · 兜底保障 ==========
        print(f"[幻觉防御] 模型调用失败，使用兜底报告: {e}")
        report_content = defense.generate_fallback_report(clean_data)

    # 保存报告
    report_id = db.add_report(report_content, "weekly")

    return {
        "id": report_id,
        "content": report_content,
        "date": datetime.now().strftime('%Y-%m-%d'),
        "threshold_met": True
    }


@app.get("/api/reports/latest")
async def get_latest_report():
    """获取最新报告"""
    reports = db.get_reports(limit=1)
    if not reports:
        return {"report": None}
    return {"report": reports[0]}


# ========== 挂载前端静态文件 ==========
DIST_DIR = Path(__file__).parent / "frontend"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("ZHEGUI_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
