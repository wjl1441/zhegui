"""Token 预算与低产出检测。

折桂当前不是无限循环 Agent，所以这里做轻量预算：
- 按 session 记录估算 token 累计
- 单轮/累计超阈值给出状态
- 最近 3 轮输出过短，标记低产出
"""

from __future__ import annotations

from dataclasses import dataclass, field


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文场景按 1 字≈1 token 保守估计。"""
    if not text:
        return 0
    return max(1, len(str(text)))


@dataclass
class TokenBudget:
    soft_cap: int = 10_000
    hard_cap: int = 20_000
    accumulated: int = 0
    turn_outputs: list[int] = field(default_factory=list)
    last_status: str = "continue"

    def check(self, turn_tokens: int, output_tokens: int = 0) -> str:
        self.accumulated += max(0, int(turn_tokens or 0))
        self.turn_outputs.append(max(0, int(output_tokens or 0)))
        self.turn_outputs = self.turn_outputs[-5:]

        if turn_tokens >= self.hard_cap:
            self.last_status = "stop_overflow"
        elif self.accumulated >= self.hard_cap:
            self.last_status = "stop_exhausted"
        elif self.accumulated >= self.soft_cap:
            self.last_status = "warn_soft_cap"
        elif len(self.turn_outputs) >= 3 and sum(self.turn_outputs[-3:]) / 3 < 50:
            self.last_status = "warn_diminishing"
        else:
            self.last_status = "continue"
        return self.last_status

    def reset(self):
        self.accumulated = 0
        self.turn_outputs = []
        self.last_status = "continue"

    def summary(self) -> dict:
        return {
            "soft_cap": self.soft_cap,
            "hard_cap": self.hard_cap,
            "accumulated": self.accumulated,
            "last_status": self.last_status,
            "recent_outputs": list(self.turn_outputs),
        }


class BudgetRegistry:
    def __init__(self):
        self._budgets: dict[str, TokenBudget] = {}

    def get(self, session_id: str) -> TokenBudget:
        if session_id not in self._budgets:
            self._budgets[session_id] = TokenBudget()
        return self._budgets[session_id]

    def check_turn(self, session_id: str, user_text: str, response_text: str) -> dict:
        budget = self.get(session_id)
        input_tokens = estimate_tokens(user_text)
        output_tokens = estimate_tokens(response_text)
        status = budget.check(input_tokens + output_tokens, output_tokens)
        return {
            "status": status,
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "turn_tokens_est": input_tokens + output_tokens,
            **budget.summary(),
        }

    def reset(self, session_id: str | None = None):
        if session_id:
            self._budgets.pop(session_id, None)
        else:
            self._budgets.clear()

    def summary(self) -> dict:
        return {
            "session_count": len(self._budgets),
            "sessions": {sid: budget.summary() for sid, budget in list(self._budgets.items())[:20]},
        }
