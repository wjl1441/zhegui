"""
折桂 — SQLite 数据库模块
处理错题本、速算记录、打卡、模考历史、报告等数据
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

# 数据库路径
DB_DIR = Path(__file__).parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "zhegui.db"


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # 返回字典格式
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    cursor = conn.cursor()

    # 错题本
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            question TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT,
            explanation TEXT,
            user_answer TEXT,
            error_type TEXT,
            status TEXT DEFAULT 'pending',
            wrong_count INTEGER DEFAULT 1,
            attempt_count INTEGER DEFAULT 0,
            last_attempt_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            mastered_at TEXT
        )
    """)

    # 速算记录
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS speed_calc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT (date('now', 'localtime')),
            correct_count INTEGER,
            total_count INTEGER,
            avg_time REAL,
            questions TEXT
        )
    """)

    # 错题作答历史
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mistake_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mistake_id INTEGER,
            is_correct INTEGER,
            time_spent REAL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (mistake_id) REFERENCES mistakes(id)
        )
    """)

    # 对话状态（用于多轮对话）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            flow TEXT,
            step INTEGER DEFAULT 0,
            data TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 打卡（完成速算练习才算打卡）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checkin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE DEFAULT (date('now', 'localtime')),
            duration_minutes INTEGER DEFAULT 0,
            speed_calc_done INTEGER DEFAULT 0,
            notes TEXT
        )
    """)

    # 模考历史
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT (date('now', 'localtime')),
            province TEXT,
            total_score REAL,
            module_scores TEXT
        )
    """)

    # 定制 Agent 报告
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT (date('now', 'localtime')),
            type TEXT DEFAULT 'weekly',
            content TEXT
        )
    """)

    # LLM 调用监控
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            error_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 学情档案
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, key)
        )
    """)

    # 学习计划历史
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            title TEXT,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            progress TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.commit()
    _migrate_database(conn)

    conn.close()


def _migrate_database(conn):
    """数据库迁移：添加新字段"""
    cursor = conn.cursor()

    # 检查 mistakes 表是否有 explanation 字段
    cursor.execute("PRAGMA table_info(mistakes)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'explanation' not in columns:
        cursor.execute("ALTER TABLE mistakes ADD COLUMN explanation TEXT")

    if 'wrong_count' not in columns:
        cursor.execute("ALTER TABLE mistakes ADD COLUMN wrong_count INTEGER DEFAULT 1")

    if 'attempt_count' not in columns:
        cursor.execute("ALTER TABLE mistakes ADD COLUMN attempt_count INTEGER DEFAULT 0")

    if 'last_attempt_at' not in columns:
        cursor.execute("ALTER TABLE mistakes ADD COLUMN last_attempt_at TEXT")

    conn.commit()


# ========== 错题本操作 ==========

def add_mistake(module, question, correct_answer, user_answer=None,
                options=None, explanation=None, error_type=None, source='manual'):
    """添加错题"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO mistakes (module, source, question, options, correct_answer, explanation, user_answer, error_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (module, source, question,
          json.dumps(options, ensure_ascii=False) if options else None,
          correct_answer, explanation, user_answer, error_type))
    mistake_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return mistake_id


def get_mistakes(module=None, status=None, search=None, page=1, page_size=20):
    """查询错题列表（分页 + 搜索）"""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM mistakes WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM mistakes WHERE 1=1"
    params = []

    if module:
        query += " AND module = ?"
        count_query += " AND module = ?"
        params.append(module)
    if status:
        query += " AND status = ?"
        count_query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND question LIKE ?"
        count_query += " AND question LIKE ?"
        params.append(f"%{search}%")

    # 获取总数
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]

    # 分页查询
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


def update_mistake(mistake_id, module=None, question=None, correct_answer=None,
                   options=None, explanation=None, error_type=None, user_answer=None):
    """更新错题内容，用于把占位错因记录补全成可复习题卡。"""
    fields = []
    params = []
    updates = {
        "module": module,
        "question": question,
        "correct_answer": correct_answer,
        "options": json.dumps(options, ensure_ascii=False) if options else None,
        "explanation": explanation,
        "error_type": error_type,
        "user_answer": user_answer,
    }
    for key, value in updates.items():
        if value is not None:
            fields.append(f"{key} = ?")
            params.append(value)

    if not fields:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    params.append(mistake_id)
    cursor.execute(f"UPDATE mistakes SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    cursor.execute("SELECT * FROM mistakes WHERE id = ?", (mistake_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_mistake_status(mistake_id, status):
    """更新错题状态（待重做/已掌握/需复习）"""
    conn = get_connection()
    cursor = conn.cursor()

    mastered_at = None
    if status == 'mastered':
        mastered_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        UPDATE mistakes SET status = ?, mastered_at = ? WHERE id = ?
    """, (status, mastered_at, mistake_id))
    conn.commit()
    conn.close()


def attempt_mistake(mistake_id, is_correct, time_spent=None):
    """记录一次作答

    Args:
        mistake_id: 错题 ID
        is_correct: 是否答对
        time_spent: 用时（秒）

    Returns:
        更新后的错题信息
    """
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if is_correct:
        cursor.execute("""
            UPDATE mistakes
            SET attempt_count = attempt_count + 1,
                last_attempt_at = ?,
                status = 'mastered',
                mastered_at = ?
            WHERE id = ?
        """, (now, now, mistake_id))
    else:
        cursor.execute("""
            UPDATE mistakes
            SET attempt_count = attempt_count + 1,
                wrong_count = wrong_count + 1,
                last_attempt_at = ?,
                status = 'pending'
            WHERE id = ?
        """, (now, mistake_id))

    # 记录作答历史
    cursor.execute("""
        INSERT INTO mistake_attempts (mistake_id, is_correct, time_spent)
        VALUES (?, ?, ?)
    """, (mistake_id, 1 if is_correct else 0, time_spent))

    conn.commit()

    cursor.execute("SELECT * FROM mistakes WHERE id = ?", (mistake_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_mistake_stats():
    """获取错题统计"""
    conn = get_connection()
    cursor = conn.cursor()

    # 各模块错题数量
    cursor.execute("""
        SELECT module, COUNT(*) as count,
               SUM(CASE WHEN status = 'mastered' THEN 1 ELSE 0 END) as mastered
        FROM mistakes
        GROUP BY module
    """)
    module_stats = [dict(row) for row in cursor.fetchall()]

    # 总计
    cursor.execute("SELECT COUNT(*) as total FROM mistakes")
    total = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) as mastered FROM mistakes WHERE status = 'mastered'")
    mastered = cursor.fetchone()['mastered']

    conn.close()
    return {
        'total': total,
        'mastered': mastered,
        'pending': total - mastered,
        'modules': module_stats
    }


def get_weakness_analysis():
    """获取薄弱点分析"""
    conn = get_connection()
    cursor = conn.cursor()

    # 各模块错误率
    cursor.execute("""
        SELECT
            module,
            COUNT(*) as total,
            SUM(wrong_count) as total_wrong,
            AVG(CASE WHEN status = 'mastered' THEN 1.0 ELSE 0.0 END) as mastery_rate,
            AVG(attempt_count) as avg_attempts
        FROM mistakes
        GROUP BY module
        ORDER BY total_wrong DESC
    """)
    weakness_by_module = [dict(row) for row in cursor.fetchall()]

    # 高频错误类型
    cursor.execute("""
        SELECT error_type, COUNT(*) as count
        FROM mistakes
        WHERE error_type IS NOT NULL
        GROUP BY error_type
        ORDER BY count DESC
        LIMIT 5
    """)
    common_errors = [dict(row) for row in cursor.fetchall()]

    # 平均作答时间（如果有记录）
    cursor.execute("""
        SELECT
            m.module,
            AVG(a.time_spent) as avg_time
        FROM mistake_attempts a
        JOIN mistakes m ON a.mistake_id = m.id
        WHERE a.time_spent IS NOT NULL
        GROUP BY m.module
    """)
    time_by_module = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return {
        'weakness_by_module': weakness_by_module,
        'common_errors': common_errors,
        'time_by_module': time_by_module
    }


# ========== 速算记录操作 ==========

def add_speed_calc(correct_count, total_count, avg_time, questions):
    """添加速算记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO speed_calc (correct_count, total_count, avg_time, questions)
        VALUES (?, ?, ?, ?)
    """, (correct_count, total_count, avg_time,
          json.dumps(questions, ensure_ascii=False)))

    record_id = cursor.lastrowid

    # 自动打卡
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("""
        INSERT OR IGNORE INTO checkin (date, speed_calc_done) VALUES (?, 1)
    """, (today,))
    cursor.execute("""
        UPDATE checkin SET speed_calc_done = 1 WHERE date = ?
    """, (today,))

    conn.commit()
    conn.close()
    return record_id


def get_speed_calc_history(days=30):
    """获取速算历史记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM speed_calc
        WHERE date >= date('now', 'localtime', ?)
        ORDER BY date DESC
    """, (f'-{days} days',))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_speed_calc_stats():
    """获取速算统计"""
    conn = get_connection()
    cursor = conn.cursor()

    # 今日记录
    cursor.execute("""
        SELECT * FROM speed_calc WHERE date = date('now', 'localtime')
    """)
    today = cursor.fetchall()

    # 总体统计
    cursor.execute("""
        SELECT
            COUNT(*) as total_sessions,
            AVG(CAST(correct_count AS REAL) / total_count * 100) as avg_accuracy,
            AVG(avg_time) as avg_time
        FROM speed_calc
    """)
    stats = dict(cursor.fetchone())

    # 最近 7 天趋势
    cursor.execute("""
        SELECT date,
               CAST(correct_count AS REAL) / total_count * 100 as accuracy,
               avg_time
        FROM speed_calc
        WHERE date >= date('now', 'localtime', '-7 days')
        ORDER BY date
    """)
    trend = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return {
        'today': [dict(r) for r in today],
        'stats': stats,
        'trend': trend
    }


# ========== 打卡操作 ==========

def checkin_today():
    """今日打卡"""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO checkin (date) VALUES (?)
    """, (today,))
    conn.commit()
    conn.close()


def get_checkin_streak():
    """获取连续打卡天数"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date FROM checkin ORDER BY date DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return 0

    # 计算连续天数
    streak = 0
    today = datetime.now().date()
    for row in rows:
        checkin_date = datetime.strptime(row['date'], '%Y-%m-%d').date()
        expected = today - __import__('datetime').timedelta(days=streak)
        if checkin_date == expected:
            streak += 1
        else:
            break

    return streak


def get_checkin_history(days=30):
    """获取打卡历史"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM checkin
        WHERE date >= date('now', 'localtime', ?)
        ORDER BY date DESC
    """, (f'-{days} days',))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ========== 模考历史操作 ==========

def add_exam(province, total_score, module_scores):
    """添加模考记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO exam_history (province, total_score, module_scores)
        VALUES (?, ?, ?)
    """, (province, total_score,
          json.dumps(module_scores, ensure_ascii=False)))
    exam_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return exam_id


def get_exam_history(limit=10):
    """获取模考历史"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM exam_history ORDER BY date DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ========== 报告操作 ==========

def add_report(content, report_type='weekly'):
    """添加报告"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (type, content) VALUES (?, ?)
    """, (report_type, content))
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id


def get_reports(limit=10):
    """获取报告列表"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reports ORDER BY date DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ========== 对话状态管理 ==========

def get_conversation_state(session_id):
    """获取对话状态"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversation_state WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        result['data'] = json.loads(result['data']) if result['data'] else {}
        return result
    return None


def save_conversation_state(session_id, flow, step, data):
    """保存对话状态"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
        INSERT INTO conversation_state (session_id, flow, step, data, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            flow = excluded.flow,
            step = excluded.step,
            data = excluded.data,
            updated_at = excluded.updated_at
    """, (session_id, flow, step, json.dumps(data, ensure_ascii=False), now))
    conn.commit()
    conn.close()


def clear_conversation_state(session_id):
    """清除对话状态"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversation_state WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


# ========== 初始化 ==========
init_db()
