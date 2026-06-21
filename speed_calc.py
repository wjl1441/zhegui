"""
折桂 — 每日速算练习模块
参考花生十三速算题型：截位直除 / 分数比较 / 假设分配 / 加减乘除
"""

import random
from typing import Optional


def generate_question(question_type: Optional[str] = None) -> dict:
    """生成一道速算题

    Args:
        question_type: 题型，None 则随机选择

    Returns:
        {
            "type": "题型",
            "question": "题目描述",
            "answer": "正确答案",
            "options": ["选项A", "选项B", "选项C", "选项D"]  # 选择题
        }
    """
    types = ['truncated_division', 'fraction_compare', 'hypothetical_allocation', 'basic_arithmetic']
    if question_type is None:
        question_type = random.choice(types)

    generators = {
        'truncated_division': _gen_truncated_division,
        'fraction_compare': _gen_fraction_compare,
        'hypothetical_allocation': _gen_hypothetical_allocation,
        'basic_arithmetic': _gen_basic_arithmetic,
    }

    return generators[question_type]()


def generate_session(count: int = 10) -> list:
    """生成一组速算练习题

    Args:
        count: 题目数量

    Returns:
        题目列表
    """
    # 确保每种题型至少有 2 道
    questions = []
    types = ['truncated_division', 'fraction_compare', 'hypothetical_allocation', 'basic_arithmetic']

    # 每种题型 2 道
    for t in types:
        for _ in range(2):
            questions.append(generate_question(t))

    # 剩余随机
    for _ in range(count - 8):
        questions.append(generate_question())

    random.shuffle(questions)

    # 添加题号
    for i, q in enumerate(questions):
        q['id'] = i + 1

    return questions


def check_answer(question: dict, user_answer: str) -> bool:
    """检查答案是否正确

    Args:
        question: 题目
        user_answer: 用户答案

    Returns:
        是否正确
    """
    return user_answer.strip() == question['answer'].strip()


# ========== 题目生成器 ==========

def _gen_truncated_division() -> dict:
    """截位直除：给算式，估算结果

    示例：2847 ÷ 63 ≈ ?
    """
    a = random.randint(1000, 9999)
    b = random.randint(10, 99)

    # 计算精确值
    exact = a / b

    # 截位直除：保留前两位有效数字
    a_truncated = int(str(a)[:2])
    b_truncated = int(str(b)[:1]) if b < 50 else int(str(b)[:2])

    if b < 50:
        # 除数截一位
        estimate = a_truncated * 10 / b_truncated
    else:
        # 除数截两位
        estimate = a_truncated * 100 / b_truncated

    # 生成选项（正确答案 ± 随机偏移）
    correct = round(exact, 1)
    options = [correct]
    for _ in range(3):
        offset = random.uniform(-5, 5)
        options.append(round(correct + offset, 1))

    options = sorted(set(options))[:4]
    random.shuffle(options)

    # 确保正确答案在选项中
    if correct not in options:
        options[0] = correct
        random.shuffle(options)

    answer_label = chr(65 + options.index(correct))  # A/B/C/D

    return {
        'type': '截位直除',
        'question': f'{a} ÷ {b} ≈ ?',
        'answer': answer_label,
        'options': [f'{opt}' for opt in options],
        'explanation': f'精确值：{a} ÷ {b} = {round(exact, 2)}'
    }


def _gen_fraction_compare() -> dict:
    """分数比较：给两个分数，比大小

    示例：比较 3567/7821 和 4289/9135
    """
    a1 = random.randint(1000, 9999)
    b1 = random.randint(2000, 9999)
    a2 = random.randint(1000, 9999)
    b2 = random.randint(2000, 9999)

    val1 = a1 / b1
    val2 = a2 / b2

    if abs(val1 - val2) < 0.02:
        # 差距太小，重新生成
        return _gen_fraction_compare()

    if val1 > val2:
        answer = 'A'
        explanation = f'{a1}/{b1} ≈ {round(val1, 3)} > {a2}/{b2} ≈ {round(val2, 3)}'
    else:
        answer = 'B'
        explanation = f'{a2}/{b2} ≈ {round(val2, 3)} > {a1}/{b1} ≈ {round(val1, 3)}'

    return {
        'type': '分数比较',
        'question': f'比较大小：{a1}/{b1} ○ {a2}/{b2}',
        'answer': answer,
        'options': [f'{a1}/{b1} 更大', f'{a2}/{b2} 更大', '两者相等', '无法比较'],
        'explanation': explanation
    }


def _gen_hypothetical_allocation() -> dict:
    """假设分配/415份数法：给基期和增长率，算现期

    示例：基期 2847，增长率 12.5%，现期约为？
    """
    base = random.randint(1000, 9999)
    rate = random.choice([12.5, 15, 17.5, 20, 22.5, 25, 30, 35, 40])

    # 精确值
    exact = base * (1 + rate / 100)

    # 415 份数法：基期 = 100 份，增长 = rate 份
    # 现期 = 100 + rate 份
    parts = rate / 100
    one_part = base / 100
    increase = one_part * rate

    correct = round(exact)
    options = [correct]
    for _ in range(3):
        offset = random.randint(-100, 100)
        options.append(correct + offset)

    options = sorted(set(options))[:4]
    random.shuffle(options)

    if correct not in options:
        options[0] = correct
        random.shuffle(options)

    answer_label = chr(65 + options.index(correct))

    return {
        'type': '假设分配',
        'question': f'基期 {base}，增长率 {rate}%，现期约为？',
        'answer': answer_label,
        'options': [f'{opt}' for opt in options],
        'explanation': f'精确值：{base} × (1+{rate}%) = {round(exact, 2)}'
    }


def _gen_basic_arithmetic() -> dict:
    """加减乘除基础：多位数的加减乘除

    示例：3847 + 2659 = ?
    """
    ops = ['+', '-', '×', '÷']
    op = random.choice(ops)

    if op == '+':
        a = random.randint(1000, 9999)
        b = random.randint(1000, 9999)
        correct = a + b
    elif op == '-':
        a = random.randint(5000, 9999)
        b = random.randint(1000, a)
        correct = a - b
    elif op == '×':
        a = random.randint(10, 99)
        b = random.randint(10, 99)
        correct = a * b
    else:  # ÷
        b = random.randint(2, 20)
        correct = random.randint(10, 99)
        a = b * correct

    options = [correct]
    for _ in range(3):
        offset = random.randint(-50, 50)
        if offset != 0:
            options.append(correct + offset)

    options = sorted(set(options))[:4]
    random.shuffle(options)

    if correct not in options:
        options[0] = correct
        random.shuffle(options)

    answer_label = chr(65 + options.index(correct))

    return {
        'type': '加减乘除',
        'question': f'{a} {op} {b} = ?',
        'answer': answer_label,
        'options': [f'{opt}' for opt in options],
        'explanation': f'{a} {op} {b} = {correct}'
    }


if __name__ == "__main__":
    # 测试生成题目
    session = generate_session(10)
    for q in session:
        print(f"[{q['id']}] {q['type']}: {q['question']}")
        for i, opt in enumerate(q['options']):
            print(f"  {chr(65+i)}. {opt}")
        print(f"  答案: {q['answer']}")
        print()
