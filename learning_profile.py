"""折桂学情档案。

把用户长期学习状态持久化到 SQLite，避免只依赖浏览器 localStorage。
"""

from __future__ import annotations

import json
from datetime import datetime

import database as db

DEFAULT_USER_ID = "default"


def _set_profile_value(user_id: str, key: str, value):
    conn = db.get_connection()
    payload = json.dumps(value, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO learning_profile (user_id, key, value, updated_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(user_id, key)
        DO UPDATE SET value = excluded.value, updated_at = datetime('now', 'localtime')
        """,
        (user_id, key, payload),
    )
    conn.commit()
    conn.close()


def update_profile(user_id: str = DEFAULT_USER_ID, **updates):
    for key, value in updates.items():
        _set_profile_value(user_id, key, value)


def get_profile(user_id: str = DEFAULT_USER_ID) -> dict:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT key, value, updated_at FROM learning_profile WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    profile = {"user_id": user_id}
    updated_at = None
    for row in rows:
      try:
          profile[row["key"]] = json.loads(row["value"])
      except Exception:
          profile[row["key"]] = row["value"]
      updated_at = row["updated_at"]
    profile["updated_at"] = updated_at
    return profile


def refresh_profile_from_learning_data(user_id: str = DEFAULT_USER_ID, province: str | None = None) -> dict:
    """从错题、速算、模考数据重新生成学情摘要。"""
    mistakes = db.get_mistake_stats()
    weakness = db.get_weakness_analysis()
    speed = db.get_speed_calc_stats()
    exams = db.get_exam_history(limit=3)
    streak = db.get_checkin_streak()

    modules = mistakes.get("modules", []) or []
    weak_modules = sorted(modules, key=lambda x: x.get("count", 0), reverse=True)
    weak_modules = [m.get("module") for m in weak_modules if m.get("count", 0) > 0]

    common_errors = weakness.get("common_errors", []) or []
    common_error_names = []
    for item in common_errors[:5]:
        if isinstance(item, dict):
            common_error_names.append(item.get("error_type") or item.get("name") or str(item))
        else:
            common_error_names.append(str(item))

    latest_exam = exams[0] if exams else None
    profile_updates = {
        "province": province,
        "mistake_total": mistakes.get("total", 0),
        "mistake_mastered": mistakes.get("mastered", 0),
        "mistake_pending": mistakes.get("pending", 0),
        "weak_modules": weak_modules[:5],
        "common_errors": common_error_names,
        "speed_sessions": (speed.get("stats") or {}).get("total_sessions", 0),
        "speed_avg_accuracy": (speed.get("stats") or {}).get("avg_accuracy", 0),
        "exam_count": len(exams),
        "latest_exam": latest_exam,
        "checkin_streak": streak,
        "last_refresh_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if province is None:
        profile_updates.pop("province")
    update_profile(user_id, **profile_updates)
    return get_profile(user_id)


def mark_review(user_id: str = DEFAULT_USER_ID, intent_type: str | None = None):
    today = datetime.now().strftime("%Y-%m-%d")
    profile = get_profile(user_id)
    review_count = int(profile.get("review_count", 0) or 0) + 1
    update_profile(
        user_id,
        last_review_date=today,
        last_review_intent=intent_type,
        review_count=review_count,
    )
