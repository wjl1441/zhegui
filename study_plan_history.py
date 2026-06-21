"""学习计划历史管理。"""

from __future__ import annotations

import json
from datetime import datetime

import database as db


def add_study_plan(content: str, user_id: str = "default", title: str = "7 天备考计划") -> int:
    progress = {"done_days": [], "total_days": 7}
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO study_plans (user_id, title, content, status, progress)
        VALUES (?, ?, ?, 'active', ?)
        """,
        (user_id, title, content, json.dumps(progress, ensure_ascii=False)),
    )
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()
    return plan_id


def _row_to_plan(row) -> dict:
    item = dict(row)
    try:
        item["progress"] = json.loads(item.get("progress") or "{}")
    except Exception:
        item["progress"] = {}
    return item


def list_study_plans(user_id: str = "default", limit: int = 20) -> list[dict]:
    conn = db.get_connection()
    rows = conn.execute(
        """
        SELECT * FROM study_plans
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [_row_to_plan(row) for row in rows]


def get_latest_plan(user_id: str = "default") -> dict | None:
    plans = list_study_plans(user_id, limit=1)
    return plans[0] if plans else None


def get_plan(plan_id: int) -> dict | None:
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM study_plans WHERE id = ?", (plan_id,)).fetchone()
    conn.close()
    return _row_to_plan(row) if row else None


def set_day_done(plan_id: int, day: int, done: bool) -> dict | None:
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM study_plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        return None
    item = dict(row)
    progress = json.loads(item.get("progress") or "{}")
    done_days = {int(d) for d in progress.get("done_days", [])}
    day = int(day)
    if done:
        done_days.add(day)
    else:
        done_days.discard(day)
    progress["done_days"] = sorted(done_days)
    total_days = int(progress.get("total_days", 7))
    status = "completed" if len(done_days) >= total_days else "active"
    conn.execute(
        """
        UPDATE study_plans
        SET progress = ?, status = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """,
        (json.dumps(progress, ensure_ascii=False), status, plan_id),
    )
    conn.commit()
    conn.close()
    return get_plan(plan_id)


def mark_day_done(plan_id: int, day: int) -> dict | None:
    return set_day_done(plan_id, day, True)


def mark_day_undone(plan_id: int, day: int) -> dict | None:
    return set_day_done(plan_id, day, False)


def toggle_day_done(plan_id: int, day: int) -> dict | None:
    plan = get_plan(plan_id)
    if not plan:
        return None
    done_days = {int(d) for d in (plan.get("progress") or {}).get("done_days", [])}
    return set_day_done(plan_id, day, int(day) not in done_days)


def delete_study_plan(plan_id: int) -> bool:
    conn = db.get_connection()
    cur = conn.execute("DELETE FROM study_plans WHERE id = ?", (plan_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted

