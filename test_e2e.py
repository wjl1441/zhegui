"""
端到端验证测试
验证设计文档中的所有要求：
1. 代码节点确实调了 MCP Server，不是模型算的
2. 模型只参与了意图识别和报告生成
3. 流程日志能看出哪些步是代码、哪些步是模型
"""

import asyncio
import json
from hybrid_engine import HybridEngine


async def run_e2e_tests():
    """运行端到端测试"""
    engine = HybridEngine()
    results = []

    # 测试用例：用户说"我今天刷了20道言语理解，对了12道"
    test_message = "我今天刷了20道言语理解，对了12道"

    print(f"Test case: {test_message}")
    print("=" * 60)

    result = await engine.process(test_message)

    # 1. 验证意图识别
    intent = result["intent"]
    assert intent.type == "daily_practice", f"Intent type error: {intent.type}"
    assert intent.module == "言语理解", f"Module error: {intent.module}"
    assert intent.correct == 12, f"Correct error: {intent.correct}"
    assert intent.total == 20, f"Total error: {intent.total}"
    print("[PASS] Intent recognition correct")

    # 2. 验证流程日志
    flow_log = result["flow_log"]
    assert len(flow_log) == 6, f"Flow steps error: {len(flow_log)}"

    # 验证每一步的节点类型和工具名称
    expected_steps = [
        ("模型", "意图识别"),
        ("代码", "validator.check_data"),
        ("代码", "calc.accuracy"),
        ("代码", "matcher.teachers"),
        ("代码", "matcher.error_solutions"),
        ("模型", "生成分析报告"),
    ]

    for i, (expected_type, expected_tool) in enumerate(expected_steps):
        step = flow_log[i]
        assert step.node_type == expected_type, \
            f"Step {i+1} type error: expected {expected_type}, got {step.node_type}"
        assert step.tool_name == expected_tool, \
            f"Step {i+1} tool error: expected {expected_tool}, got {step.tool_name}"
        assert step.success, f"Step {i+1} failed"
    print("[PASS] Flow steps correct (6 steps: 2 model + 4 code)")

    # 3. 验证代码节点的返回值
    # validator.check_data
    check_result = flow_log[1].result
    assert check_result["status"] == "pass", f"Check should pass: {check_result}"
    print("[PASS] validator.check_data correct")

    # calc.accuracy
    accuracy_result = flow_log[2].result
    assert accuracy_result["accuracy"] == 60.0, f"Accuracy should be 60%: {accuracy_result}"
    assert accuracy_result["correct"] == 12, f"Correct should be 12: {accuracy_result}"
    assert accuracy_result["total"] == 20, f"Total should be 20: {accuracy_result}"
    print("[PASS] calc.accuracy correct (60%)")

    # matcher.teachers
    teachers_result = flow_log[3].result
    assert "teacher_list" in teachers_result, f"Should have teacher_list: {teachers_result}"
    assert len(teachers_result["teacher_list"]) > 0, "Should return at least 1 teacher"
    print(f"[PASS] matcher.teachers correct ({len(teachers_result['teacher_list'])} teachers)")

    # matcher.error_solutions
    solutions_result = flow_log[4].result
    assert "all_solutions" in solutions_result, f"Should have all_solutions: {solutions_result}"
    print("[PASS] matcher.error_solutions correct")

    # 4. 验证回复内容
    response = result["response"]
    assert len(response) > 100, f"Response too short: {len(response)} chars"
    print(f"[PASS] Response content correct ({len(response)} chars)")

    # 5. 统计模型调用次数
    model_calls = [s for s in flow_log if s.node_type == "模型"]
    code_calls = [s for s in flow_log if s.node_type == "代码"]
    assert len(model_calls) == 2, f"Model calls should be 2: {len(model_calls)}"
    assert len(code_calls) == 4, f"Code calls should be 4: {len(code_calls)}"
    print(f"[PASS] Call stats correct: 2 model + 4 code")

    print("=" * 60)
    print("[SUCCESS] All verifications passed!")

    # 输出详细结果
    output = {
        "test_message": test_message,
        "intent": intent.__dict__,
        "flow_log": [
            {
                "step": i + 1,
                "node_type": s.node_type,
                "tool_name": s.tool_name,
                "success": s.success
            }
            for i, s in enumerate(flow_log)
        ],
        "model_calls": len(model_calls),
        "code_calls": len(code_calls),
        "response_length": len(response),
        "all_passed": True
    }

    with open("test_e2e_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n详细结果已保存到 test_e2e_results.json")

    return output


if __name__ == "__main__":
    asyncio.run(run_e2e_tests())
