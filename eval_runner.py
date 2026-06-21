"""折桂自动化评测 runner。

用法：
  python eval_runner.py
  python eval_runner.py --set normal
  python eval_runner.py --set edge
  python eval_runner.py --set attack

默认直接调用 HybridEngine，不走 HTTP，避免服务未启动导致评测失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from hybrid_engine import HybridEngine
import database as db

BASE_DIR = Path(__file__).parent
EVAL_DIR = BASE_DIR / "eval"
SETS = {
    "normal": EVAL_DIR / "normal_cases.json",
    "edge": EVAL_DIR / "edge_cases.json",
    "attack": EVAL_DIR / "attack_cases.json",
}


def load_cases(set_name: str | None):
    paths = [SETS[set_name]] if set_name else list(SETS.values())
    cases = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data:
            case["set"] = path.stem.replace("_cases", "")
            cases.append(case)
    return cases


def includes_any(text: str, phrases: list[str] | None) -> bool:
    if not phrases:
        return True
    return any(p in text for p in phrases)


def includes_none(text: str, phrases: list[str] | None) -> bool:
    if not phrases:
        return True
    return not any(p in text for p in phrases)


def judge(case: dict, result: dict) -> tuple[bool, list[str]]:
    failures = []
    response = result.get("response") or ""
    intent = result.get("intent")
    intent_type = intent.type if intent else None

    expected_intent = case.get("expected_intent")
    if expected_intent is not None and intent_type != expected_intent:
        failures.append(f"intent expected={expected_intent}, got={intent_type}")

    if not includes_any(response, case.get("must_include_any")):
        failures.append(f"response missing any of {case.get('must_include_any')}")

    if not includes_none(response, case.get("must_not_include_any")):
        failures.append(f"response contains forbidden phrase from {case.get('must_not_include_any')}")

    return not failures, failures


async def run_eval(set_name: str | None = None):
    cases = load_cases(set_name)
    engine = HybridEngine()
    results = []

    for case in cases:
        session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
        # 避免多轮状态污染
        db.clear_conversation_state(session_id)
        try:
            result = await engine.process(case.get("input", ""), session_id=session_id)
            ok, failures = judge(case, result)
            results.append({
                "id": case["id"],
                "set": case["set"],
                "category": case.get("category"),
                "ok": ok,
                "failures": failures,
                "intent": result.get("intent").type if result.get("intent") else None,
                "response_preview": (result.get("response") or "")[:160],
            })
        except Exception as e:
            results.append({
                "id": case["id"],
                "set": case["set"],
                "category": case.get("category"),
                "ok": False,
                "failures": [str(e)],
                "intent": None,
                "response_preview": "",
            })
        finally:
            db.clear_conversation_state(session_id)

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "results": results,
    }
    return summary


def print_summary(summary: dict):
    print(f"\n折桂评测完成：{summary['passed']}/{summary['total']} 通过，通过率 {summary['pass_rate']}%\n", flush=True)
    for r in summary["results"]:
        mark = "PASS" if r["ok"] else "FAIL"
        line = f"[{mark}] {r['set']}::{r['id']} {r.get('category') or ''} intent={r.get('intent')}"
        print(line.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))
        if not r["ok"]:
            for f in r["failures"]:
                print(f"  - {f}".encode('utf-8', errors='replace').decode('utf-8', errors='replace'))
            preview = r['response_preview'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            # Windows 控制台 GBK 编码兼容
            preview = preview.encode('gbk', errors='replace').decode('gbk')
            print(f"  preview: {preview}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=sorted(SETS.keys()), help="只运行指定评测集")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    summary = await run_eval(args.set)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_summary(summary)

    raise SystemExit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
