"""
折桂本地工具层

把原 MCP server 中的纯函数能力搬到进程内调用，避免每次工具调用都启动
stdio MCP 子进程。MCP server 文件仍保留，便于兼容外部 MCP 调试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
REFERENCES_DIR = BASE_DIR / "references"


def _load_json(name: str) -> Any:
    with open(REFERENCES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


_ERROR_SOLUTIONS = _load_json("error_solutions.json")
_TEACHERS = _load_json("teachers.json")
_EXAM_STRUCTURES = _load_json("exam_structures.json")
_TIME_STANDARDS = _load_json("time_standards.json")

_MAX_QUESTIONS_PER_MODULE = {
    "政治理论": 15,
    "常识判断": 15,
    "言语理解": 45,
    "数量关系": 25,
    "判断推理": 55,
    "资料分析": 30,
}

_ALL_TEACHERS = {t["name"] for teachers in _TEACHERS.values() for t in teachers}
_ALL_ERROR_TYPES = set()
for module_data in _ERROR_SOLUTIONS.values():
    if isinstance(module_data, dict):
        for sub_type_data in module_data.values():
            if isinstance(sub_type_data, dict):
                _ALL_ERROR_TYPES.update(sub_type_data.keys())


def accuracy(correct: int, total: int) -> dict:
    if total == 0:
        return {"error": "总题数不能为0"}
    if correct < 0 or total < 0:
        return {"error": "题数不能为负数"}
    if correct > total:
        return {"error": "答对题数不能大于总题数"}

    rate = round(correct / total * 100, 1)
    return {
        "accuracy": rate,
        "correct": correct,
        "total": total,
        "wrong": total - correct,
        "level": _get_level(rate),
    }


def trend(records: list[dict]) -> dict:
    if not records:
        return {"error": "没有记录数据"}

    sorted_records = sorted(records, key=lambda x: x.get("date", ""))
    trend_data = []
    for r in sorted_records:
        if r["total"] > 0:
            trend_data.append({
                "date": r["date"],
                "module": r.get("module", "未知"),
                "accuracy": round(r["correct"] / r["total"] * 100, 1),
                "total": r["total"],
            })

    if len(trend_data) < 2:
        return {"trend_data": trend_data, "changes": [], "summary": "记录不足，无法分析趋势"}

    changes = []
    for i in range(1, len(trend_data)):
        prev = trend_data[i - 1]
        curr = trend_data[i]
        diff = round(curr["accuracy"] - prev["accuracy"], 1)
        changes.append({
            "from_date": prev["date"],
            "to_date": curr["date"],
            "diff": diff,
            "direction": "上升" if diff > 0 else ("下降" if diff < 0 else "持平"),
        })

    overall_diff = round(trend_data[-1]["accuracy"] - trend_data[0]["accuracy"], 1)
    if overall_diff > 5:
        summary = f"整体呈上升趋势，正确率提升了{overall_diff}%"
    elif overall_diff < -5:
        summary = f"整体呈下降趋势，正确率下降了{abs(overall_diff)}%"
    else:
        summary = f"整体稳定，正确率变化{overall_diff}%"

    return {"trend_data": trend_data, "changes": changes, "overall_diff": overall_diff, "summary": summary}


def roi(modules_data: list[dict]) -> dict:
    if not modules_data:
        return {"error": "没有模块数据"}

    ranked = []
    for m in modules_data:
        if m["total"] == 0:
            continue
        acc = m["correct"] / m["total"]
        wrong_count = m["total"] - m["correct"]
        roi_score = round(wrong_count * (1 - acc), 2)
        weight = m.get("weight", 1.0)
        ranked.append({
            "module": m["module"],
            "accuracy": round(acc * 100, 1),
            "wrong_count": wrong_count,
            "roi_score": roi_score,
            "weighted_roi": round(roi_score * weight, 2),
        })

    ranked.sort(key=lambda x: x["weighted_roi"], reverse=True)
    suggestions = []
    for r in ranked[:3]:
        if r["accuracy"] < 60:
            suggestions.append(f"【优先】{r['module']}正确率仅{r['accuracy']}%，提升空间最大")
        elif r["accuracy"] < 80:
            suggestions.append(f"【推荐】{r['module']}正确率{r['accuracy']}%，突破后提分明显")
        else:
            suggestions.append(f"【保持】{r['module']}正确率{r['accuracy']}%，保持即可")

    return {"ranked": ranked, "suggestions": suggestions, "top_priority": ranked[0]["module"] if ranked else None}


def error_solutions(module: str, sub_type: str | None = None, error_type: str | None = None) -> dict:
    if module not in _ERROR_SOLUTIONS:
        return {"error": f"未找到模块'{module}'的错因数据", "available_modules": list(_ERROR_SOLUTIONS.keys())}
    module_data = _ERROR_SOLUTIONS[module]
    if not sub_type:
        return {"module": module, "all_solutions": module_data}
    if sub_type not in module_data:
        return {"error": f"未找到'{module}'中的题型'{sub_type}'", "available_types": list(module_data.keys())}
    sub_data = module_data[sub_type]
    if error_type:
        if error_type in sub_data:
            return {"module": module, "sub_type": sub_type, "error_type": error_type, "solution": sub_data[error_type]}
        return {"error": f"未找到'{sub_type}'中的错误类型'{error_type}'", "available_error_types": list(sub_data.keys())}
    return {"module": module, "sub_type": sub_type, "solutions": sub_data}


def teachers(module: str) -> dict:
    if module not in _TEACHERS:
        return {"error": f"未找到模块'{module}'的名师数据", "available_modules": list(_TEACHERS.keys())}
    return {"module": module, "teacher_list": _TEACHERS[module]}


def exam_structure(province: str) -> dict:
    if province not in _EXAM_STRUCTURES:
        return {"error": f"未找到省份'{province}'的卷子结构", "available_provinces": list(_EXAM_STRUCTURES.keys())}
    s = _EXAM_STRUCTURES[province]
    return {"province": province, "modules": s["modules"], "total_time": s["total_time"], "total_questions": s["total_questions"]}


def time_standard(module: str, sub_type: str | None = None) -> dict:
    if module not in _TIME_STANDARDS:
        return {"error": f"未找到模块'{module}'的用时标准", "available_modules": list(_TIME_STANDARDS.keys())}
    standard = _TIME_STANDARDS[module]
    if sub_type and "sub_types" in standard:
        if sub_type in standard["sub_types"]:
            sub = standard["sub_types"][sub_type]
            return {"module": module, "sub_type": sub_type, "per_question": sub["per_question"], "max_per_question": sub["max_per_question"], "tips": sub["tips"]}
        return {"error": f"未找到'{module}'中的题型'{sub_type}'", "available_types": list(standard["sub_types"].keys())}
    result = {"module": module, "total_time": standard["total_time"], "tips": standard.get("tips", "")}
    for key in ["sub_types", "per_question", "max_per_question"]:
        if key in standard:
            result[key] = standard[key]
    return result


def check_data(correct: int, total: int, module: str | None = None) -> dict:
    errors = []
    if not isinstance(correct, int) or correct < 0:
        errors.append("答对题数必须为非负整数")
    if not isinstance(total, int) or total < 0:
        errors.append("总题数必须为非负整数")
    if isinstance(correct, int) and isinstance(total, int):
        if total == 0:
            errors.append("总题数不能为0")
        elif correct > total:
            errors.append(f"答对题数({correct})不能大于总题数({total})")
    if module and module in _MAX_QUESTIONS_PER_MODULE and isinstance(total, int) and total > _MAX_QUESTIONS_PER_MODULE[module]:
        errors.append(f"模块'{module}'的总题数({total})超过最大限制({_MAX_QUESTIONS_PER_MODULE[module]})")
    if errors:
        return {"status": "fail", "errors": errors, "reason": "；".join(errors)}
    return {"status": "pass", "reason": "数据校验通过"}


def check_module_sum(province: str, modules: list[dict]) -> dict:
    if province not in _EXAM_STRUCTURES:
        return {"status": "fail", "reason": f"未找到省份'{province}'的卷子结构数据", "available_provinces": list(_EXAM_STRUCTURES.keys())}
    expected_total = _EXAM_STRUCTURES[province]["total_questions"]
    expected_modules = {m["name"]: m["total"] for m in _EXAM_STRUCTURES[province]["modules"]}
    errors = []
    actual_total = 0
    for m in modules:
        name = m.get("module", "")
        total = m.get("total", 0)
        correct = m.get("correct", 0)
        if name not in expected_modules:
            errors.append(f"未知模块'{name}'")
            continue
        if total != expected_modules[name]:
            errors.append(f"模块'{name}'题数应为{expected_modules[name]}，实际为{total}")
        if correct > total:
            errors.append(f"模块'{name}'答对题数({correct})大于总题数({total})")
        actual_total += total
    if actual_total != expected_total:
        errors.append(f"各模块题数之和({actual_total})不等于{province}卷总题数({expected_total})")
    if errors:
        return {"status": "fail", "errors": errors, "reason": "；".join(errors), "expected_total": expected_total, "actual_total": actual_total}
    return {"status": "pass", "reason": f"模块总和校验通过，共{actual_total}题", "expected_total": expected_total, "actual_total": actual_total}


def check_teacher(name: str) -> dict:
    if name in _ALL_TEACHERS:
        return {"status": "pass", "reason": f"老师'{name}'存在于知识库中"}
    return {"status": "fail", "reason": f"老师'{name}'不在知识库中，可能为幻觉输出", "available_teachers": list(_ALL_TEACHERS)}


def check_error_type(error_type: str) -> dict:
    if error_type in _ALL_ERROR_TYPES:
        return {"status": "pass", "reason": f"错误类型'{error_type}'存在于知识库中"}
    return {"status": "fail", "reason": f"错误类型'{error_type}'不在知识库中，可能为幻觉输出", "available_error_types": list(_ALL_ERROR_TYPES)}


def call_tool(server_name: str, tool_name: str, arguments: dict) -> dict | None:
    tools = {
        "calc": {"accuracy": accuracy, "trend": trend, "roi": roi},
        "matcher": {"error_solutions": error_solutions, "teachers": teachers, "exam_structure": exam_structure, "time_standard": time_standard},
        "validator": {"check_data": check_data, "check_module_sum": check_module_sum, "check_teacher": check_teacher, "check_error_type": check_error_type},
    }
    fn = tools.get(server_name, {}).get(tool_name)
    if not fn:
        return None
    return fn(**arguments)


def _get_level(rate: float) -> str:
    if rate >= 90:
        return "优秀"
    if rate >= 80:
        return "良好"
    if rate >= 70:
        return "中等"
    if rate >= 60:
        return "及格"
    return "需加强"
