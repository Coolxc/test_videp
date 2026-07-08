#!/usr/bin/env python3
"""DeepSeek API 客户端。所有 LLM 调用通过此模块。"""

import json
import os
import time
import re
from typing import Optional

import requests


# ── 模块加载时优先从 .env 读取 ──
def _try_load_dotenv():
    """尝试从项目根目录加载 .env 文件（优先 .env，fallback .env.example）。"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        from dotenv import load_dotenv
        for name in (".env", ".env.example"):
            env_path = os.path.join(project_root, name)
            if os.path.exists(env_path):
                load_dotenv(env_path)
                return
        return  # 无 .env 文件
    except ImportError:
        pass  # dotenv 未安装，走手动解析 fallback

    # ── Fallback: 手动解析 .env（不依赖 python-dotenv）──
    for name in (".env", ".env.example"):
        env_path = os.path.join(project_root, name)
        if not os.path.exists(env_path):
            continue
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key and not os.environ.get(key):
                    os.environ[key] = val
        return  # 只处理第一个找到的文件


_try_load_dotenv()

DEEPSEEK_API_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 环境变量未设置。\n"
            "请设置: export DEEPSEEK_API_KEY=your-key-here\n"
            "或在 .env 文件中添加 DEEPSEEK_API_KEY=your-key-here"
        )
    return key


def call_deepseek(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> str:
    """调用 DeepSeek API，返回响应文本。"""
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(3):
        try:
            resp = requests.post(
                DEEPSEEK_API_URL, json=payload, headers=headers, timeout=90
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            if attempt < 2:
                wait = 2 ** attempt
                print(f"  [LLM] 请求失败, {wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                raise

    # Should not reach here
    raise RuntimeError("DeepSeek API call failed after 3 retries")


def call_deepseek_json(
    system_prompt: str, user_prompt: str, **kwargs
) -> dict:
    """调用 DeepSeek 并解析 JSON 响应。带容错的 JSON 提取。"""
    text = call_deepseek(system_prompt, user_prompt, **kwargs)
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 块
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # 尝试提取第一个 { ... } 块
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"无法从 LLM 响应中提取 JSON:\n{text[:500]}")
