"""
测试混合引擎 v2（定稿版本）
"""

import asyncio
import json
from hybrid_engine import HybridEngine


async def test_all_flows():
    engine = HybridEngine()

    test_cases = [
        {
            "name": "刷题分析",
            "message": "我今天刷了20道言语理解，对了12道",
            "expected_type": "daily_practice"
        },
        {
            "name": "模考分析",
            "message": "做了模考，贵州卷，资料分析15对10，判断25对18",
            "expected_type": "mock_exam"
        },
        {
            "name": "考前策略",
            "message": "快考试了，我是国考",
            "expected_type": "pre_exam_strategy"
        }
    ]

    results = []

    for tc in test_cases:
        try:
            result = await engine.process(tc["message"])
            intent = result["intent"]

            # 验证流程日志
            flow_steps = [
                {"step": i+1, "node_type": s.node_type, "tool_name": s.tool_name, "success": s.success}
                for i, s in enumerate(result["flow_log"])
            ]

            # 统计调用次数
            model_calls = sum(1 for s in result["flow_log"] if s.node_type == "模型")
            code_calls = sum(1 for s in result["flow_log"] if s.node_type == "代码")

            results.append({
                "name": tc["name"],
                "message": tc["message"],
                "intent_type": intent.type,
                "intent_ok": intent.type == tc["expected_type"],
                "flow_steps": flow_steps,
                "model_calls": model_calls,
                "code_calls": code_calls,
                "response_length": len(result["response"]),
                "success": True
            })
        except Exception as e:
            results.append({
                "name": tc["name"],
                "message": tc["message"],
                "error": str(e),
                "success": False
            })

    # 输出结果到文件
    output = {
        "test_results": results,
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r["success"]),
            "intent_correct": sum(1 for r in results if r.get("intent_ok"))
        }
    }

    with open("test_engine_v2_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Test completed. Results saved to test_engine_v2_results.json")
    print(f"Success: {output['summary']['success']}/{output['summary']['total']}")
    print(f"Intent correct: {output['summary']['intent_correct']}/{output['summary']['total']}")


if __name__ == "__main__":
    asyncio.run(test_all_flows())
