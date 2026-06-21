"""
matcher-mcp: 匹配类 MCP Server
提供错因→方案、模块→名师、省份→卷子结构等查表功能
"""

import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("matcher-mcp")

# 知识库路径
REFERENCES_DIR = Path(__file__).parent / "references"

# 启动时加载数据
_error_solutions = {}
_teachers = {}
_exam_structures = {}
_time_standards = {}


def _load_data():
    """加载知识库数据到内存"""
    global _error_solutions, _teachers, _exam_structures, _time_standards

    with open(REFERENCES_DIR / "error_solutions.json", "r", encoding="utf-8") as f:
        _error_solutions = json.load(f)

    with open(REFERENCES_DIR / "teachers.json", "r", encoding="utf-8") as f:
        _teachers = json.load(f)

    with open(REFERENCES_DIR / "exam_structures.json", "r", encoding="utf-8") as f:
        _exam_structures = json.load(f)

    with open(REFERENCES_DIR / "time_standards.json", "r", encoding="utf-8") as f:
        _time_standards = json.load(f)


# 启动时加载
_load_data()


@mcp.tool()
def error_solutions(module: str, sub_type: str = None, error_type: str = None) -> dict:
    """查询错因对应的解决方案

    Args:
        module: 模块名称（如"言语理解"、"数量关系"）
        sub_type: 题型（如"逻辑填空"、"片段阅读"），可选
        error_type: 具体错误类型（如"词语辨析不清"），可选

    Returns:
        解决方案
    """
    if module not in _error_solutions:
        return {
            "error": f"未找到模块'{module}'的错因数据",
            "available_modules": list(_error_solutions.keys())
        }

    module_data = _error_solutions[module]

    # 只指定模块，返回该模块所有数据
    if not sub_type:
        return {
            "module": module,
            "all_solutions": module_data
        }

    # 指定了题型
    if sub_type not in module_data:
        return {
            "error": f"未找到'{module}'中的题型'{sub_type}'",
            "available_types": list(module_data.keys())
        }

    sub_data = module_data[sub_type]

    # 指定了具体错误类型
    if error_type:
        if error_type in sub_data:
            return {
                "module": module,
                "sub_type": sub_type,
                "error_type": error_type,
                "solution": sub_data[error_type]
            }
        else:
            return {
                "error": f"未找到'{sub_type}'中的错误类型'{error_type}'",
                "available_error_types": list(sub_data.keys())
            }

    # 返回该题型所有错误和方案
    return {
        "module": module,
        "sub_type": sub_type,
        "solutions": sub_data
    }


@mcp.tool()
def teachers(module: str) -> dict:
    """查询模块推荐名师

    Args:
        module: 模块名称（如"言语理解"、"数量关系"）

    Returns:
        名师列表
    """
    if module not in _teachers:
        return {
            "error": f"未找到模块'{module}'的名师数据",
            "available_modules": list(_teachers.keys())
        }

    return {
        "module": module,
        "teacher_list": _teachers[module]
    }


@mcp.tool()
def exam_structure(province: str) -> dict:
    """查询省份卷子结构

    Args:
        province: 省份名称（如"国考"、"贵州"、"广东"）

    Returns:
        卷子结构信息
    """
    if province not in _exam_structures:
        return {
            "error": f"未找到省份'{province}'的卷子结构",
            "available_provinces": list(_exam_structures.keys())
        }

    structure = _exam_structures[province]
    return {
        "province": province,
        "modules": structure["modules"],
        "total_time": structure["total_time"],
        "total_questions": structure["total_questions"]
    }


@mcp.tool()
def time_standard(module: str, sub_type: str = None) -> dict:
    """查询模块用时标准

    Args:
        module: 模块名称（如"言语理解"、"数量关系"）
        sub_type: 题型（如"逻辑填空"），可选

    Returns:
        用时标准和建议
    """
    if module not in _time_standards:
        return {
            "error": f"未找到模块'{module}'的用时标准",
            "available_modules": list(_time_standards.keys())
        }

    standard = _time_standards[module]

    # 有子题型且有 sub_types 字段
    if sub_type and "sub_types" in standard:
        if sub_type in standard["sub_types"]:
            sub = standard["sub_types"][sub_type]
            return {
                "module": module,
                "sub_type": sub_type,
                "per_question": sub["per_question"],
                "max_per_question": sub["max_per_question"],
                "tips": sub["tips"]
            }
        else:
            return {
                "error": f"未找到'{module}'中的题型'{sub_type}'",
                "available_types": list(standard["sub_types"].keys())
            }

    # 返回整个模块的用时标准
    result = {
        "module": module,
        "total_time": standard["total_time"],
        "tips": standard.get("tips", "")
    }
    if "sub_types" in standard:
        result["sub_types"] = standard["sub_types"]
    if "per_question" in standard:
        result["per_question"] = standard["per_question"]
    if "max_per_question" in standard:
        result["max_per_question"] = standard["max_per_question"]
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
