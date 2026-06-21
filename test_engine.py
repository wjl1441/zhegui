"""
测试混合引擎（简化版，避免终端编码问题）
"""

import asyncio
import json
from hybrid_engine import HybridEngine


async def test_engine():
    engine = HybridEngine()

    test_cases = [
        {"message": "我今天刷了20道言语理解，对了12道", "expected_module": "言语理解"},
        {"message": "数量关系做了15道，只对了5道", "expected_module": "数量关系"},
    ]

    results = []

    for tc in test_cases:
        try:
            result = await engine.process(tc["message"])
            intent = result["intent"]

            # 验证意图识别
            intent_ok = (
                intent.type == "daily_practice" and
                intent.module == tc["expected_module"]
            )

            # 验证流程日志
            flow_steps = [(s.node_type, s.tool_name, s.success) for s in result["flow_log"]]

            results.append({
                "message": tc["message"],
                "intent_type": intent.type,
                "intent_module": intent.module,
                "intent_correct": intent.correct,
                "intent_total": intent.total,
                "intent_ok": intent_ok,
                "flow_steps": flow_steps,
                "response_length": len(result["response"]),
                "success": True
            })
        except Exception as e:
            results.append({
                "message": tc["message"],
                "error": str(e),
                "success": False
            })

    # 输出结果到文件（避免终端编码问题）
    output = {
        "test_results": results,
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r["success"]),
            "intent_correct": sum(1 for r in results if r.get("intent_ok"))
        }
    }

    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Test completed. Results saved to test_results.json")
    print(f"Success: {output['summary']['success']}/{output['summary']['total']}")
    print(f"Intent correct: {output['summary']['intent_correct']}/{output['summary']['total']}")


if __name__ == "__main__":
    asyncio.run(test_engine())
