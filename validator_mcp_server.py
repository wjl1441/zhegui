"""
validator-mcp: 校验类 MCP Server
提供数据合理性校验、模块总和校验、幻觉防御校验等功能
"""

import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("validator-mcp")

# 知识库路径
REFERENCES_DIR = Path(__file__).parent / "references"

# 加载卷子结构用于校验
_exam_structures = {}
_teachers = {}
_error_solutions = {}

with open(REFERENCES_DIR / "exam_structures.json", "r", encoding="utf-8") as f:
    _exam_structures = json.load(f)

with open(REFERENCES_DIR / "teachers.json", "r", encoding="utf-8") as f:
    _teachers = json.load(f)

with open(REFERENCES_DIR / "error_solutions.json", "r", encoding="utf-8") as f:
    _error_solutions = json.load(f)

# 单模块最大题数限制
_MAX_QUESTIONS_PER_MODULE = {
    "政治理论": 15,
    "常识判断": 15,
    "言语理解": 45,
    "数量关系": 25,
    "判断推理": 55,
    "资料分析": 30
}

# 所有合法的老师名（从知识库提取）
_ALL_TEACHERS = set()
for module_teachers in _teachers.values():
    for t in module_teachers:
        _ALL_TEACHERS.add(t["name"])

# 所有合法的错误类型（从知识库提取）
_ALL_ERROR_TYPES = set()
for module_data in _error_solutions.values():
    if isinstance(module_data, dict):
        for sub_type_data in module_data.values():
            if isinstance(sub_type_data, dict):
                _ALL_ERROR_TYPES.update(sub_type_data.keys())


@mcp.tool()
def check_data(correct: int, total: int, module: str = None) -> dict:
    """校验单模块数据合理性

    Args:
        correct: 答对题数
        total: 总题数
        module: 模块名称（可选，用于检查最大题数限制）

    Returns:
        校验结果（pass/fail + 原因）
    """
    errors = []

    # 检查是否为非负整数
    if not isinstance(correct, int) or correct < 0:
        errors.append("答对题数必须为非负整数")
    if not isinstance(total, int) or total < 0:
        errors.append("总题数必须为非负整数")

    # 检查逻辑关系
    if isinstance(correct, int) and isinstance(total, int):
        if total == 0:
            errors.append("总题数不能为0")
        elif correct > total:
            errors.append(f"答对题数({correct})不能大于总题数({total})")

    # 检查模块最大题数限制
    if module and module in _MAX_QUESTIONS_PER_MODULE:
        max_q = _MAX_QUESTIONS_PER_MODULE[module]
        if isinstance(total, int) and total > max_q:
            errors.append(f"模块'{module}'的总题数({total})超过最大限制({max_q})")

    if errors:
        return {
            "status": "fail",
            "errors": errors,
            "reason": "；".join(errors)
        }

    return {
        "status": "pass",
        "reason": "数据校验通过"
    }


@mcp.tool()
def check_module_sum(province: str, modules: list[dict]) -> dict:
    """校验各模块题数之和是否等于卷子总题数

    Args:
        province: 省份名称（如"国考"、"贵州"）
        modules: 各模块数据，每条包含 module, correct, total

    Returns:
        校验结果（pass/fail + 原因）
    """
    if province not in _exam_structures:
        return {
            "status": "fail",
            "reason": f"未找到省份'{province}'的卷子结构数据",
            "available_provinces": list(_exam_structures.keys())
        }

    expected_total = _exam_structures[province]["total_questions"]
    expected_modules = {m["name"]: m["total"] for m in _exam_structures[province]["modules"]}

    errors = []
    actual_total = 0

    for m in modules:
        module_name = m.get("module", "")
        module_total = m.get("total", 0)
        module_correct = m.get("correct", 0)

        # 检查模块是否存在
        if module_name not in expected_modules:
            errors.append(f"未知模块'{module_name}'")
            continue

        # 检查题数是否匹配
        expected = expected_modules[module_name]
        if module_total != expected:
            errors.append(f"模块'{module_name}'题数应为{expected}，实际为{module_total}")

        # 检查正确数是否合理
        if module_correct > module_total:
            errors.append(f"模块'{module_name}'答对题数({module_correct})大于总题数({module_total})")

        actual_total += module_total

    # 检查总题数
    if actual_total != expected_total:
        errors.append(f"各模块题数之和({actual_total})不等于{province}卷总题数({expected_total})")

    if errors:
        return {
            "status": "fail",
            "errors": errors,
            "reason": "；".join(errors),
            "expected_total": expected_total,
            "actual_total": actual_total
        }

    return {
        "status": "pass",
        "reason": f"模块总和校验通过，共{actual_total}题",
        "expected_total": expected_total,
        "actual_total": actual_total
    }


@mcp.tool()
def check_teacher(name: str) -> dict:
    """校验老师名是否在知识库中（幻觉防御）

    Args:
        name: 老师名称

    Returns:
        校验结果
    """
    if name in _ALL_TEACHERS:
        return {
            "status": "pass",
            "reason": f"老师'{name}'存在于知识库中"
        }
    return {
        "status": "fail",
        "reason": f"老师'{name}'不在知识库中，可能为幻觉输出",
        "available_teachers": list(_ALL_TEACHERS)
    }


@mcp.tool()
def check_error_type(error_type: str) -> dict:
    """校验错误类型是否在知识库中（幻觉防御）

    Args:
        error_type: 错误类型名称

    Returns:
        校验结果
    """
    if error_type in _ALL_ERROR_TYPES:
        return {
            "status": "pass",
            "reason": f"错误类型'{error_type}'存在于知识库中"
        }
    return {
        "status": "fail",
        "reason": f"错误类型'{error_type}'不在知识库中，可能为幻觉输出",
        "available_error_types": list(_ALL_ERROR_TYPES)
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
