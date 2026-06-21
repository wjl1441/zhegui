"""
终稿 API 全量测试
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)
results = []


def test(name, func):
    """运行测试并记录结果"""
    try:
        func()
        results.append({"name": name, "status": "PASS"})
        print(f"  [PASS] {name}")
    except Exception as e:
        results.append({"name": name, "status": "FAIL", "error": str(e)})
        print(f"  [FAIL] {name}: {e}")


# ========== 1. 对话 API ==========
print("\n=== 对话 API ===")

def test_chat():
    r = client.post("/api/chat", json={"message": "你好"})
    assert r.status_code == 200
    data = r.json()
    assert "response" in data
    assert "flow_log" in data
    assert "stats" in data

test("POST /api/chat", test_chat)

def test_stats():
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert "code_calls" in r.json()

test("GET /api/stats", test_stats)

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

test("GET /api/health", test_health)


# ========== 2. 错题本 API ==========
print("\n=== 错题本 API ===")

def test_add_mistake():
    r = client.post("/api/mistakes", json={
        "module": "言语理解",
        "question": "下列词语中没有错别字的一组是",
        "correct_answer": "A",
        "user_answer": "B",
        "error_type": "粗心"
    })
    assert r.status_code == 200
    assert r.json()["id"] > 0

test("POST /api/mistakes", test_add_mistake)

def test_list_mistakes():
    r = client.get("/api/mistakes")
    assert r.status_code == 200
    data = r.json()
    assert "mistakes" in data
    assert data["total"] > 0

test("GET /api/mistakes", test_list_mistakes)

def test_list_mistakes_filter():
    r = client.get("/api/mistakes?module=言语理解&status=pending")
    assert r.status_code == 200
    assert r.json()["total"] > 0

test("GET /api/mistakes (filtered)", test_list_mistakes_filter)

def test_update_mistake():
    r = client.put("/api/mistakes/1/status", json={"status": "mastered"})
    assert r.status_code == 200

test("PUT /api/mistakes/1/status", test_update_mistake)

def test_mistake_stats():
    r = client.get("/api/mistakes/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "mastered" in data
    assert "modules" in data

test("GET /api/mistakes/stats", test_mistake_stats)


# ========== 3. 速算练习 API ==========
print("\n=== 速算练习 API ===")

def test_generate_speed():
    r = client.get("/api/speed-calc/generate?count=10")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 8  # 最少 8 道（每种题型 2 道）
    assert len(data["questions"]) >= 8
    # 检查题目结构
    q = data["questions"][0]
    assert "type" in q
    assert "question" in q
    assert "answer" in q
    assert "options" in q

test("GET /api/speed-calc/generate", test_generate_speed)

def test_submit_speed():
    r = client.post("/api/speed-calc", json={
        "correct_count": 8,
        "total_count": 10,
        "avg_time": 25.5,
        "questions": [{"id": 1, "type": "test"}]
    })
    assert r.status_code == 200
    assert r.json()["id"] > 0

test("POST /api/speed-calc", test_submit_speed)

def test_speed_stats():
    r = client.get("/api/speed-calc/stats")
    assert r.status_code == 200
    data = r.json()
    assert "today" in data
    assert "stats" in data
    assert "trend" in data

test("GET /api/speed-calc/stats", test_speed_stats)

def test_speed_history():
    r = client.get("/api/speed-calc/history?days=7")
    assert r.status_code == 200
    assert "history" in r.json()

test("GET /api/speed-calc/history", test_speed_history)


# ========== 4. 打卡 API ==========
print("\n=== 打卡 API ===")

def test_streak():
    r = client.get("/api/checkin/streak")
    assert r.status_code == 200
    assert "streak" in r.json()

test("GET /api/checkin/streak", test_streak)

def test_checkin_history():
    r = client.get("/api/checkin/history?days=7")
    assert r.status_code == 200
    assert "history" in r.json()

test("GET /api/checkin/history", test_checkin_history)


# ========== 5. 模考历史 API ==========
print("\n=== 模考历史 API ===")

def test_add_exam():
    r = client.post("/api/exams", json={
        "province": "贵州",
        "total_score": 65.5,
        "module_scores": {
            "言语理解": 70,
            "数量关系": 50,
            "判断推理": 65,
            "资料分析": 80,
            "常识判断": 60
        }
    })
    assert r.status_code == 200
    assert r.json()["id"] > 0

test("POST /api/exams", test_add_exam)

def test_list_exams():
    r = client.get("/api/exams?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert "exams" in data
    assert len(data["exams"]) > 0

test("GET /api/exams", test_list_exams)


# ========== 6. 报告 API ==========
print("\n=== 报告 API ===")

def test_generate_report():
    r = client.post("/api/reports/generate")
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert "content" in data
    assert len(data["content"]) > 100

test("POST /api/reports/generate", test_generate_report)

def test_latest_report():
    r = client.get("/api/reports/latest")
    assert r.status_code == 200
    data = r.json()
    assert data["report"] is not None

test("GET /api/reports/latest", test_latest_report)

def test_list_reports():
    r = client.get("/api/reports?limit=5")
    assert r.status_code == 200
    assert "reports" in r.json()

test("GET /api/reports", test_list_reports)


# ========== 7. 政治理论 API ==========
print("\n=== 政治理论 API ===")

def test_categories():
    r = client.get("/api/political-theory/categories")
    assert r.status_code == 200
    data = r.json()
    assert len(data["categories"]) == 8

test("GET /api/political-theory/categories", test_categories)

def test_topics_all():
    r = client.get("/api/political-theory/topics")
    assert r.status_code == 200
    data = r.json()
    assert len(data["topics"]) > 10

test("GET /api/political-theory/topics", test_topics_all)

def test_topics_by_category():
    r = client.get("/api/political-theory/topics?category_id=marxism")
    assert r.status_code == 200
    data = r.json()
    assert data["category"] == "马克思主义基本原理"
    assert len(data["topics"]) == 3

test("GET /api/political-theory/topics?category_id", test_topics_by_category)

def test_search():
    r = client.get("/api/political-theory/search?q=矛盾")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] > 0

test("GET /api/political-theory/search", test_search)

def test_random():
    r = client.get("/api/political-theory/random")
    assert r.status_code == 200
    data = r.json()
    assert "topic" in data
    assert "title" in data["topic"]

test("GET /api/political-theory/random", test_random)


# ========== 8. 数据看板 API ==========
print("\n=== 数据看板 API ===")

def test_dashboard():
    r = client.get("/api/dashboard?province=贵州&exam_date=2026-07-15")
    assert r.status_code == 200
    data = r.json()
    assert "exam" in data
    assert data["exam"]["days_left"] > 0
    assert "streak" in data
    assert "mistakes" in data
    assert "speed_calc" in data
    assert "exams" in data
    assert "today" in data

test("GET /api/dashboard", test_dashboard)

def test_dashboard_no_params():
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["exam"]["days_left"] is None

test("GET /api/dashboard (no params)", test_dashboard_no_params)


# ========== 汇总 ==========
print("\n" + "=" * 50)
passed = sum(1 for r in results if r["status"] == "PASS")
failed = sum(1 for r in results if r["status"] == "FAIL")
print(f"Total: {len(results)} | Pass: {passed} | Fail: {failed}")

if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r["status"] == "FAIL":
            print(f"  - {r['name']}: {r['error']}")
