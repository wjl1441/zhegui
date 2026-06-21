"""失败恢复与降级。"""

from __future__ import annotations

import asyncio


def classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "rate" in text and "limit" in text:
        return "rate_limit"
    if "json" in text:
        return "invalid_json"
    return "model_error"


async def with_retry_async(func, max_retries=3, base_delay=1.0):
    """异步指数退避重试。"""
    last = None
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            last = e
            if attempt == max_retries - 1:
                break
            delay = 10 if classify_error(e) == "rate_limit" else base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
    raise last


def with_retry(func, max_retries=3, base_delay=1.0):
    """同步指数退避重试。"""
    import time
    last = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last = e
            if attempt == max_retries - 1:
                break
            delay = 10 if classify_error(e) == "rate_limit" else base_delay * (2 ** attempt)
            time.sleep(delay)
    raise last


def fallback_response(error_type: str) -> dict:
    responses = {
        "timeout": {"reply": "系统响应超时，请稍后重试。", "code": 503},
        "rate_limit": {"reply": "请求过于频繁，请稍后再试。", "code": 429},
        "invalid_json": {"reply": "模型返回格式异常，已使用备用解析方案。", "code": 200},
        "model_error": {"reply": "模型暂时不可用，已切换备用方案。", "code": 200},
    }
    return responses.get(error_type, responses["model_error"])
