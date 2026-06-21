"""
测试三个 MCP Server 的基本功能
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_calc_mcp():
    """测试 calc-mcp"""
    print("\n=== 测试 calc-mcp ===")

    server_params = StdioServerParameters(
        command="python",
        args=["calc_mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 测试 accuracy
            result = await session.call_tool("accuracy", {"correct": 12, "total": 20})
            print(f"accuracy(12, 20) = {json.loads(result.content[0].text)}")

            # 测试 trend
            records = [
                {"date": "2024-01-01", "module": "言语理解", "correct": 10, "total": 20},
                {"date": "2024-01-02", "module": "言语理解", "correct": 12, "total": 20},
                {"date": "2024-01-03", "module": "言语理解", "correct": 15, "total": 20},
            ]
            result = await session.call_tool("trend", {"records": records})
            print(f"trend() = {json.loads(result.content[0].text)}")

            # 测试 roi
            modules_data = [
                {"module": "言语理解", "correct": 12, "total": 20},
                {"module": "数量关系", "correct": 5, "total": 15},
                {"module": "资料分析", "correct": 18, "total": 20},
            ]
            result = await session.call_tool("roi", {"modules_data": modules_data})
            print(f"roi() = {json.loads(result.content[0].text)}")


async def test_matcher_mcp():
    """测试 matcher-mcp"""
    print("\n=== 测试 matcher-mcp ===")

    server_params = StdioServerParameters(
        command="python",
        args=["matcher_mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 测试 error_solutions
            result = await session.call_tool("error_solutions", {"module": "言语理解", "sub_type": "逻辑填空", "error_type": "词语辨析不清"})
            print(f"error_solutions(言语理解, 逻辑填空, 词语辨析不清) = {json.loads(result.content[0].text)}")

            # 测试 teachers
            result = await session.call_tool("teachers", {"module": "判断推理"})
            print(f"teachers(判断推理) = {json.loads(result.content[0].text)}")

            # 测试 exam_structure
            result = await session.call_tool("exam_structure", {"province": "贵州"})
            print(f"exam_structure(贵州) = {json.loads(result.content[0].text)}")

            # 测试 time_standard
            result = await session.call_tool("time_standard", {"module": "言语理解", "sub_type": "逻辑填空"})
            print(f"time_standard(言语理解, 逻辑填空) = {json.loads(result.content[0].text)}")


async def test_validator_mcp():
    """测试 validator-mcp"""
    print("\n=== 测试 validator-mcp ===")

    server_params = StdioServerParameters(
        command="python",
        args=["validator_mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 测试 check_data - 正常情况
            result = await session.call_tool("check_data", {"correct": 12, "total": 20, "module": "言语理解"})
            print(f"check_data(12, 20, 言语理解) = {json.loads(result.content[0].text)}")

            # 测试 check_data - 异常情况
            result = await session.call_tool("check_data", {"correct": 25, "total": 20})
            print(f"check_data(25, 20) = {json.loads(result.content[0].text)}")

            # 测试 check_module_sum
            modules = [
                {"module": "政治理论", "correct": 8, "total": 10},
                {"module": "常识判断", "correct": 7, "total": 10},
                {"module": "言语理解", "correct": 24, "total": 30},
                {"module": "数量关系", "correct": 7, "total": 10},
                {"module": "判断推理", "correct": 25, "total": 35},
                {"module": "资料分析", "correct": 16, "total": 20},
            ]
            result = await session.call_tool("check_module_sum", {"province": "贵州", "modules": modules})
            print(f"check_module_sum(贵州) = {json.loads(result.content[0].text)}")


async def main():
    print("开始测试 MCP Servers...")

    try:
        await test_calc_mcp()
    except Exception as e:
        print(f"calc-mcp 测试失败: {e}")

    try:
        await test_matcher_mcp()
    except Exception as e:
        print(f"matcher-mcp 测试失败: {e}")

    try:
        await test_validator_mcp()
    except Exception as e:
        print(f"validator-mcp 测试失败: {e}")

    print("\n测试完成!")


if __name__ == "__main__":
    asyncio.run(main())
