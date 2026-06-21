"""LLM 调用监控。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "zhegui.db"


def record_llm_call(model, latency_ms, input_tokens=0, output_tokens=0, status="success", error_code=None):
    """记录一次 LLM 调用，不让监控失败影响主流程。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            """
            INSERT INTO llm_calls (model, latency_ms, input_tokens, output_tokens, status, error_code)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (model, int(latency_ms or 0), int(input_tokens or 0), int(output_tokens or 0), status, error_code),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[metrics] record_llm_call failed: {e}")


def get_metrics_summary():
    """返回 LLM 调用概览。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM llm_calls")
    total = cur.fetchone()["total"] or 0

    cur.execute("""
        SELECT
            AVG(latency_ms) AS avg_latency_ms,
            AVG(input_tokens + output_tokens) AS avg_tokens,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS failed
        FROM llm_calls
    """)
    row = cur.fetchone()
    failed = row["failed"] or 0

    cur.execute("""
        SELECT model, latency_ms, input_tokens, output_tokens, status, error_code, created_at
        FROM llm_calls
        ORDER BY id DESC
        LIMIT 10
    """)
    recent = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total_calls": total,
        "avg_latency_ms": round(row["avg_latency_ms"] or 0),
        "avg_tokens": round(row["avg_tokens"] or 0),
        "input_tokens": row["input_tokens"] or 0,
        "output_tokens": row["output_tokens"] or 0,
        "failed_calls": failed,
        "failure_rate": round((failed / total * 100), 1) if total else 0,
        "recent": recent,
    }


def usage_from_response(response):
    """兼容 OpenAI SDK 的 usage 字段。"""
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    return getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
