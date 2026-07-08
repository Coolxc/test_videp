#!/usr/bin/env python3
"""
generate-image-gemini.py

使用 Google Gemini API (Imagen 3) 生成图片。
支持单张和批量生成模式。

用法:
python3 generate-image-gemini.py "<提示词>" "<宽高比>" "<输出目录>"
"""

import asyncio
import base64
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banana_prompt_template import whiteboard_prompt_template

# --- Config ---
API_BASE = 'https://generativelanguage.googleapis.com/v1beta'
MODEL_NAME = 'imagen-4.0-generate-001'
BATCH_CONCURRENCY = 5  # Gemini API 的吞吐量通常较低，建议调小

MAX_RETRIES = 3
RETRY_BASE_DELAY_S = 3.0

SCRIPT_DIR = Path(__file__).resolve().parent

# --- Load .env from skill directory ---
def load_env():
    if os.environ.get('GEMINI_API_KEY'):
        return
    env_path = SCRIPT_DIR.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            trimmed = line.strip()
            if not trimmed or trimmed.startswith('#'):
                continue
            eq_index = trimmed.find('=')
            if eq_index == -1:
                continue
            key = trimmed[:eq_index].strip()
            value = trimmed[eq_index + 1:].strip()
            if key == 'GEMINI_API_KEY' and value:
                os.environ['GEMINI_API_KEY'] = value
                return

class FatalError(Exception):
    pass

class RetryableError(Exception):
    def __init__(self, message, is_rate_limit=False):
        super().__init__(message)
        self.is_rate_limit = is_rate_limit

def request_sync(method, url_path, body):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise FatalError('GEMINI_API_KEY not found. Set it in environment variable or .env file.')

    url = f"{API_BASE}{url_path}?key={api_key}"
    payload = json.dumps(body).encode('utf-8')
    req = Request(url, data=payload, method=method)
    req.add_header('Content-Type', 'application/json')

    try:
        with urlopen(req, timeout=60) as resp:
            data = resp.read().decode('utf-8')
            return json.loads(data)
    except HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')
        if e.code == 400 or e.code == 401 or e.code == 403:
            raise FatalError(f'HTTP {e.code}: {body_text}')
        if e.code == 429:
            raise RetryableError(f'HTTP 429 (rate limited)', is_rate_limit=True)
        raise RetryableError(f'HTTP {e.code}: {body_text}')
    except Exception as e:
        raise RetryableError(str(e))

def calc_backoff(attempt, is_rate_limit=False):
    multiplier = 5.0 if is_rate_limit else 1.0
    delay = RETRY_BASE_DELAY_S * (2 ** (attempt - 1)) * multiplier
    jitter = random.uniform(0.5, 1.5)
    return delay * jitter

async def with_retry(fn, context=''):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await fn()
        except FatalError:
            raise
        except RetryableError as e:
            if attempt == MAX_RETRIES:
                raise
            delay = calc_backoff(attempt, is_rate_limit=e.is_rate_limit)
            print(f'{context}Attempt {attempt}/{MAX_RETRIES} failed: {e}. Retrying in {delay:.1f}s...')
            await asyncio.sleep(delay)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            delay = calc_backoff(attempt)
            print(f'{context}Attempt {attempt}/{MAX_RETRIES} unexpected error: {e}. Retrying...')
            await asyncio.sleep(delay)

async def generate_single(prompt, aspect_ratio, output_dir, index, total):
    tag = f'[{index + 1}/{total}] ' if total > 1 else ''
    
    # 构造 Gemini 请求体
    body = {
        "instances": [
            {
                "prompt": whiteboard_prompt_template + prompt
            }
        ],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio
        }
    }

    async def _do_gen():
        print(f'{tag}Generating image with Gemini...')
        res = await asyncio.to_thread(
            request_sync, 'POST', f'/models/{MODEL_NAME}:predict', body
        )
        
        predictions = res.get('predictions')
        if not predictions or len(predictions) == 0:
            raise RetryableError(f'No predictions in response: {json.dumps(res)}')
        
        # 提取 Base64 图片数据
        # 兼容两种可能的 key: bytesBase64Encoded 或 structValue 等
        pred = predictions[0]
        b64_data = None
        if isinstance(pred, dict):
            b64_data = pred.get('bytesBase64Encoded')
        
        if not b64_data:
            raise FatalError(f'Cannot find image data in response: {json.dumps(res)}')

        # 保存图片
        timestamp = int(time.time() * 1000)
        suffix = f'_{str(index + 1).zfill(len(str(total)))}' if total > 1 else ''
        filename = f'gemini_{timestamp}{suffix}.png'
        filepath = str(Path(output_dir) / filename)
        
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(b64_data))
        
        print(f'{tag}Image saved: {filepath}')
        return filepath

    return await with_retry(_do_gen, context=tag)

async def run_batch(tasks, concurrency):
    semaphore = asyncio.Semaphore(concurrency)
    results = [None] * len(tasks)

    async def worker(i, task):
        async with semaphore:
            try:
                results[i] = await generate_single(
                    task['prompt'], task['aspectRatio'],
                    task['outputDir'], task['index'], task['total']
                )
            except Exception as e:
                results[i] = {'error': str(e)}

    await asyncio.gather(*(worker(i, t) for i, t in enumerate(tasks)))
    return results

async def main():
    load_env()
    args = sys.argv[1:]
    prompt_arg = args[0] if len(args) > 0 else ''
    aspect_ratio = args[1] if len(args) > 1 else '16:9'
    output_dir = args[2] if len(args) > 2 else os.getcwd()

    if not prompt_arg.strip():
        print('Error: prompt is required.')
        sys.exit(1)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    prompts = None
    try:
        parsed = json.loads(prompt_arg)
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], str):
            prompts = parsed
    except:
        pass
    if not prompts:
        prompts = [prompt_arg]

    total = len(prompts)
    tasks = [
        {
            'prompt': p,
            'aspectRatio': aspect_ratio,
            'outputDir': output_dir,
            'index': i,
            'total': total,
        }
        for i, p in enumerate(prompts)
    ]

    print(f'Using Gemini Engine (Model: {MODEL_NAME})')
    results = await run_batch(tasks, BATCH_CONCURRENCY)
    
    # 汇总
    succeeded = [r for r in results if isinstance(r, str)]
    failed = [r for r in results if isinstance(r, dict)]
    if total > 1:
        print(f'\nComplete: {len(succeeded)} succeeded, {len(failed)} failed.')

    # 输出结果
    print(f'\n__RESULTS__{json.dumps(results)}')

if __name__ == '__main__':
    asyncio.run(main())
