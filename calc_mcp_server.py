"""
calc-mcp: 计算类 MCP Server
提供正确率计算、趋势分析、提分性价比排序等功能
"""

import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calc-mcp")


@mcp.tool()
def accuracy(correct: int, total: int) -> dict:
    """计算正确率

    Args:
        correct: 答对题数
        total: 总题数

    Returns:
        包含正确率、答对题数、总题数的字典
    """
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
        "level": _get_level(rate)
    }


@mcp.tool()
def trend(records: list[dict]) -> dict:
    """分析正确率趋势

    Args:
        records: 刷题记录列表，每条包含 date, module, correct, total

    Returns:
        趋势数据和变化分析
    """
    if not records:
        return {"error": "没有记录数据"}

    # 按日期排序
    sorted_records = sorted(records, key=lambda x: x.get("date", ""))

    trend_data = []
    for r in sorted_records:
        if r["total"] > 0:
            rate = round(r["correct"] / r["total"] * 100, 1)
            trend_data.append({
                "date": r["date"],
                "module": r.get("module", "未知"),
                "accuracy": rate,
                "total": r["total"]
            })

    if len(trend_data) < 2:
        return {
            "trend_data": trend_data,
            "changes": [],
            "summary": "记录不足，无法分析趋势"
        }

    # 计算变化
    changes = []
    for i in range(1, len(trend_data)):
        prev = trend_data[i - 1]
        curr = trend_data[i]
        diff = round(curr["accuracy"] - prev["accuracy"], 1)
        changes.append({
            "from_date": prev["date"],
            "to_date": curr["date"],
            "diff": diff,
            "direction": "上升" if diff > 0 else ("下降" if diff < 0 else "持平")
        })

    # 整体趋势判断
    first = trend_data[0]["accuracy"]
    last = trend_data[-1]["accuracy"]
    overall_diff = round(last - first, 1)

    if overall_diff > 5:
        summary = f"整体呈上升趋势，正确率提升了{overall_diff}%"
    elif overall_diff < -5:
        summary = f"整体呈下降趋势，正确率下降了{abs(overall_diff)}%"
    else:
        summary = f"整体稳定，正确率变化{overall_diff}%"

    return {
        "trend_data": trend_data,
        "changes": changes,
        "overall_diff": overall_diff,
        "summary": summary
    }


@mcp.tool()
def roi(modules_data: list[dict]) -> dict:
    """计算提分性价比排序

    Args:
        modules_data: 各模块数据，每条包含 module, correct, total, weight(可选)

    Returns:
        按性价比排序的模块列表和建议
    """
    if not modules_data:
        return {"error": "没有模块数据"}

    ranked = []
    for m in modules_data:
        if m["total"] == 0:
            continue

        accuracy = m["correct"] / m["total"]
        wrong_count = m["total"] - m["correct"]
        # 性价比 = 错题数 * (1 - 正确率)，错题多且正确率低的模块性价比高
        roi_score = round(wrong_count * (1 - accuracy), 2)
        weight = m.get("weight", 1.0)

        ranked.append({
            "module": m["module"],
            "accuracy": round(accuracy * 100, 1),
            "wrong_count": wrong_count,
            "roi_score": roi_score,
            "weighted_roi": round(roi_score * weight, 2)
        })

    # 按性价比降序排序
    ranked.sort(key=lambda x: x["weighted_roi"], reverse=True)

    # 生成建议
    suggestions = []
    for i, r in enumerate(ranked[:3]):
        if r["accuracy"] < 60:
            suggestions.append(f"【优先】{r['module']}正确率仅{r['accuracy']}%，提升空间最大")
        elif r["accuracy"] < 80:
            suggestions.append(f"【推荐】{r['module']}正确率{r['accuracy']}%，突破后提分明显")
        else:
            suggestions.append(f"【保持】{r['module']}正确率{r['accuracy']}%，保持即可")

    return {
        "ranked": ranked,
        "suggestions": suggestions,
        "top_priority": ranked[0]["module"] if ranked else None
    }


def _get_level(rate: float) -> str:
    """根据正确率返回等级"""
    if rate >= 90:
        return "优秀"
    elif rate >= 80:
        return "良好"
    elif rate >= 70:
        return "中等"
    elif rate >= 60:
        return "及格"
    else:
        return "需加强"


if __name__ == "__main__":
    mcp.run(transport="stdio")
