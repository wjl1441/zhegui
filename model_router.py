"""
折桂 — 模型路由器
根据任务类型选择合适的模型
- 图片识别 → mimo-v2.5
- 文本对话 → DeepSeek
"""

import os
import json
from pathlib import Path
import os
from openai import OpenAI

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
from metrics import record_llm_call, usage_from_response
from recovery import with_retry, classify_error

# 自动加载 .env 文件（强制覆盖）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()


def get_deepseek_client():
    """获取 DeepSeek 客户端"""
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com"
    )


def get_mimo_client():
    """获取 mimo-v2.5 客户端（OpenAI 兼容协议）"""
    return OpenAI(
        api_key=os.getenv("MIMO_API_KEY", ""),
        base_url="https://api.xiaomimimo.com/v1"
    )


def _tracked_completion(client, model: str, messages, temperature=None, **kwargs):
    """统一记录模型调用。"""
    import time
    start = time.perf_counter()
    try:
        call_kwargs = {"model": model, "messages": messages, **kwargs}
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        response = with_retry(lambda: client.chat.completions.create(**call_kwargs))
        input_tokens, output_tokens = usage_from_response(response)
        record_llm_call(model, (time.perf_counter() - start) * 1000, input_tokens, output_tokens, "success")
        return response
    except Exception as e:
        error_type = classify_error(e)
        record_llm_call(model, (time.perf_counter() - start) * 1000, 0, 0, "failed", error_type)
        raise


def chat_completion(messages: str, model: str = "deepseek") -> str:
    """文本对话（默认用 DeepSeek）"""
    client = get_deepseek_client()
    response = _tracked_completion(
        client,
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": messages}],
        temperature=0.7
    )
    return response.choices[0].message.content


def image_recognition(image_base64: str, prompt: str = "") -> dict:
    """图片识别（用 mimo-v2.5）

    Args:
        image_base64: 图片的 base64 编码
        prompt: 用户提示词

    Returns:
        {"success": True, "data": {"question": "...", "options": [...], "module": "...", "answer": "..."}}
    """
    default_prompt = "请从这张图片中提取题目内容。返回 JSON 格式：{\"question\": \"题目内容\", \"options\": [\"A. ...\", \"B. ...\", ...], \"module\": \"所属模块\", \"answer\": \"正确答案（如有）\"}"

    full_prompt = prompt if prompt else default_prompt

    try:
        mimo_key = os.getenv("MIMO_API_KEY", "")
        if mimo_key:
            return _call_mimo_vision(image_base64, full_prompt)
        return {"success": False, "error": "未配置 MIMO_API_KEY，无法识别图片"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _call_mimo_vision(image_base64: str, prompt: str) -> dict:
    """调用 mimo-v2.5 进行图片识别（OpenAI 兼容协议）"""
    client = get_mimo_client()

    # base64 需要带 MIME 前缀：data:{MIME_TYPE};base64,$BASE64_IMAGE
    if not image_base64.startswith("data:"):
        image_url = f"data:image/jpeg;base64,{image_base64}"
    else:
        image_url = image_base64

    response = _tracked_completion(
        client,
        model="mimo-v2.5",
        messages=[
            {
                "role": "system",
                "content": "你是一个考公备考助手，擅长从图片中提取题目并结构化。"
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt + "\n\n请直接返回 JSON 格式：{\"question\": \"题目内容\", \"options\": [\"A. ...\", \"B. ...\", ...], \"module\": \"所属模块\", \"answer\": \"正确答案（如有）\"}"
                    }
                ]
            }
        ],
        max_completion_tokens=1024
    )

    content = response.choices[0].message.content

    # 解析 JSON
    try:
        if "{" in content:
            json_str = content[content.index("{"):content.rindex("}") + 1]
            result = json.loads(json_str)
        else:
            result = json.loads(content)
        return {"success": True, "data": result}
    except:
        return {"success": True, "data": {"question": content, "options": [], "module": "", "answer": ""}}
