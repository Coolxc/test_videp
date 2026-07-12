#!/usr/bin/env python3
"""
parse_markdown_script.py - Markdown 脚本 → storyboard 骨架 JSON。

用户写 Markdown 分镜脚本 → 调用 DeepSeek 转为 storyboard JSON（无 bbox）。
输出 storyboard-skeleton.json，后续由 detect_elements.py 补全 bbox 字段。

与旧版 parse_storyboard.py 的关系：
  - parse_storyboard.py: 处理 JSON 输入（保持兼容）
  - parse_markdown_script.py: 处理 .md 输入（新增）

用法:
    python scripts/parse_markdown_script.py --input script.md --output output/dir/
"""

import json
import os
import re
import sys
from pathlib import Path

from config import PROJECT_ROOT, get_image_filename

# ── System Prompt for Markdown → storyboard JSON ──

MARKDOWN_SYSTEM_PROMPT = """你是一位专业的白板动画视频分镜解析专家。

你的任务：将用户编写的 Markdown 分镜脚本解析为结构化的 storyboard JSON。

【输入格式说明】
用户写的 Markdown 分镜脚本包含：
- # 标题 = 视频标题
- ## 场景一/二/三 = 场景分隔
- 画面：场景画面描述（用于后续 AI 生图）
- 旁白：配音文案
- 绘制顺序：元素绘制顺序（可选）
- 动画：后画动画类型（可选）

【输出 JSON Schema】
```json
{
  "meta": {
    "title": "视频标题",
    "topic": "英文topic-slug",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "style": "ipad_sketch",
    "penStyle": "marker",
    "pipeline": { "mode": "video_first" },
    "subtitle": { "enabled": true, "fontSize": 36 },
    "transition": { "type": "pen_wipe", "durationFrames": 25 }
  },
  "scenes": [
    {
      "id": "scene1",
      "imagePrompt": "详细的 AI 生图 prompt，iPad 手绘风格描述",
      "voiceText": "旁白文案",
      "elements": [
        {
          "id": "element_id",
          "description": "元素描述",
          "narration": "此元素对应的旁白片段",
          "drawOrder": 1,
          "postAnimation": { "type": "pulse", "speed": "normal" }
        }
      ]
    }
  ]
}
```

【严格规则】
1. 不要生成 bbox 字段（后续由 Vision AI 自动检测）
2. 每个场景必须有 elements[]，至少一个元素
3. element.id 用英文小写蛇形命名（如 "seesaw", "office_worker"）
4. element.description 是元素的简短文字描述
5. element.narration 是此元素对应的旁白片段（可从 voiceText 拆分）
6. element.drawOrder 是绘制顺序编号（从 1 开始），仅当用户指定时才包含
7. element.postAnimation 仅当用户指定动画时才包含
8. 动画类型: pulse, breathe, rotate, seesaw, bounce, shake, float, emphasis, wave
9. 动画速度: slow, normal, fast
10. 图片中绝对不包含任何文字、字母、数字、标点
11. 所有时长相关字段不要在 scene 级别设置

【动画语法解析】
用户在 Markdown 中写 `动画：` 行，格式为：
- `动画：心跳` → {"type": "pulse", "speed": "normal"}
- `动画：旋转(慢)` → {"type": "rotate", "speed": "slow"}
- `动画：跷跷板-摆动` → {"type": "seesaw", "speed": "normal"}
- `动画：心-心跳` → {"type": "pulse", "speed": "normal"}

【绘制顺序解析】
用户在 Markdown 中写 `绘制顺序：` 行，格式为：
- `绘制顺序：跷跷板 → 上班族 → 金币`
  按此顺序设置 elements 的 drawOrder 字段（1, 2, 3...）

【场景 imagePrompt 生成规则】
根据画面描述生成详细的 AI 生图 prompt，需包含：
- iPad 专业手绘速写风格（Apple Pencil 线条）
- 纯黑色线条，白底
- 元素布局描述
- 绝对不出现文字
"""


# ── Schema definition for validation ──

STORYBOARD_SCHEMA = {
    "type": "object",
    "required": ["meta", "scenes"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "topic": {"type": "string"},
                "fps": {"type": "integer", "minimum": 1, "maximum": 60},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "style": {"type": "string"},
                "penStyle": {"type": "string"},
                "pipeline": {"type": "object"},
                "subtitle": {"type": "object"},
                "transition": {"type": "object"},
            },
        },
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "imagePrompt", "voiceText", "elements"],
                "properties": {
                    "id": {"type": "string"},
                    "imagePrompt": {"type": "string"},
                    "voiceText": {"type": "string"},
                    "elements": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["id", "description", "narration"],
                            "properties": {
                                "id": {"type": "string"},
                                "description": {"type": "string"},
                                "narration": {"type": "string"},
                                "drawOrder": {"type": "integer"},
                                "postAnimation": {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": [
                                                "pulse", "breathe", "rotate",
                                                "seesaw", "bounce", "shake",
                                                "float", "emphasis", "wave",
                                            ],
                                        },
                                        "speed": {
                                            "type": "string",
                                            "enum": ["slow", "normal", "fast"],
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def validate_storyboard(storyboard: dict) -> list[str]:
    """Validate storyboard JSON against schema. Returns list of error messages."""
    try:
        import jsonschema
        errors = list(jsonschema.iter_validate(storyboard, STORYBOARD_SCHEMA))
        return [str(e) for e in errors]
    except ImportError:
        # jsonschema not installed — fallback to basic checks
        errors = []
        if "meta" not in storyboard:
            errors.append("Missing 'meta'")
        if "scenes" not in storyboard or not storyboard["scenes"]:
            errors.append("Missing or empty 'scenes'")
        for scene in storyboard.get("scenes", []):
            if "id" not in scene:
                errors.append("Scene missing 'id'")
            if "elements" not in scene or not scene["elements"]:
                errors.append(f"Scene {scene.get('id', '?')} missing 'elements'")
        return errors


def _patch_defaults(storyboard: dict) -> dict:
    """填充 meta 区所有缺省字段（复用 parse_storyboard 逻辑）。"""
    # ── meta defaults ──
    meta = storyboard.setdefault("meta", {})
    meta.setdefault("title", "Untitled")
    meta.setdefault("topic", meta["title"].lower().replace(" ", "-"))
    meta.setdefault("fps", 30)
    meta.setdefault("width", 1920)
    meta.setdefault("height", 1080)
    meta.setdefault("style", "ipad_sketch")
    meta.setdefault("penStyle", "marker")
    meta.setdefault("pipeline", {"mode": "video_first"})
    meta.setdefault("subtitle", {"enabled": True, "fontSize": 36})
    meta.setdefault("transition", {"type": "pen_wipe", "durationFrames": 25})

    # ── scene defaults ──
    for i, scene in enumerate(storyboard.get("scenes", [])):
        scene.setdefault("id", f"scene{i+1}")
        scene.setdefault("voiceText", "")
        scene.setdefault("imagePrompt", "")

        # elements: ensure narration exists
        for elem in scene.get("elements", []):
            elem.setdefault("narration", "")

    return storyboard


def _sort_by_draw_order(storyboard: dict) -> dict:
    """如果 elements 有 drawOrder 字段，按 drawOrder 排序。"""
    for scene in storyboard.get("scenes", []):
        elements = scene.get("elements", [])
        if elements and all(e.get("drawOrder") for e in elements):
            scene["elements"] = sorted(elements, key=lambda e: e["drawOrder"])
            # 移除 drawOrder 字段（只在排序中使用）
            for e in scene["elements"]:
                e.pop("drawOrder", None)
    return storyboard


def parse_markdown_script(
    markdown_path: str,
    output_path: str,
    max_retries: int = 3,
) -> dict:
    """读取 Markdown 脚本，解析为 storyboard 骨架 JSON。

    Args:
        markdown_path: .md 文件路径
        output_path: 输出目录路径（输出文件为 storyboard-skeleton.json）
        max_retries: LLM 重试次数

    Returns:
        storyboard dict
    """
    from llm_client import call_deepseek_json

    # 1. 读取 Markdown
    with open(markdown_path, "r", encoding="utf-8") as f:
        markdown_text = f.read()

    print(f"\n  解析 Markdown: {markdown_path} ({len(markdown_text)} chars)")

    # 2. 调用 LLM 解析
    user_prompt = (
        "请将以下 Markdown 分镜脚本解析为 storyboard JSON：\n\n"
        + markdown_text
    )

    storyboard = None
    last_error = ""

    for attempt in range(max_retries):
        try:
            print(f"  [LLM] Markdown 解析尝试 {attempt + 1}/{max_retries}...")
            result = call_deepseek_json(
                MARKDOWN_SYSTEM_PROMPT,
                user_prompt,
                temperature=0.3,
                max_tokens=6000,
            )

            # 3. 程序修补
            result = _patch_defaults(result)

            # 4. 按 drawOrder 排序
            result = _sort_by_draw_order(result)

            # 5. 校验
            errors = validate_storyboard(result)
            if errors:
                last_error = "; ".join(errors[:5])
                print(f"  [WARN] 校验失败: {last_error}")
                # 将错误信息拼入 prompt 重新调用
                user_prompt = (
                    f"之前解析有误，请修正以下问题：\n{last_error}\n\n"
                    f"原 Markdown：\n{markdown_text}"
                )
                continue

            storyboard = result
            print(f"  [OK] 解析成功: {len(storyboard['scenes'])} 场景")
            break

        except Exception as e:
            last_error = str(e)
            print(f"  [WARN] 第 {attempt+1} 次尝试失败: {e}")
            if attempt < max_retries - 1:
                user_prompt = (
                    f"之前解析出错：{e}\n"
                    f"请重新解析并确保输出严格的 JSON 格式：\n\n{markdown_text}"
                )

    if storyboard is None:
        print(f"  [ERR] Markdown 解析失败（{max_retries} 次尝试后）")
        print(f"  最后错误: {last_error}")
        print(f"  将使用简化 storyboard（单场景全画布）")
        storyboard = _create_fallback(markdown_text)

    # 6. 写输出
    os.makedirs(output_path, exist_ok=True)
    skeleton_path = os.path.join(output_path, "storyboard-skeleton.json")
    with open(skeleton_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  输出: {skeleton_path}")

    return storyboard


def _create_fallback(markdown_text: str) -> dict:
    """当 LLM 解析完全失败时的降级方案。"""
    # 尝试提取标题
    title_match = re.search(r"^#\s+(.+)$", markdown_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    # 尝试提取场景标题
    scene_matches = re.findall(
        r"^##\s+(.+)$", markdown_text, re.MULTILINE
    )

    if not scene_matches:
        scene_matches = ["场景一"]

    scenes = []
    for i, scene_title in enumerate(scene_matches):
        scene_id = f"scene{i+1}"
        scenes.append({
            "id": scene_id,
            "imagePrompt": f"iPad 手绘简笔画: {scene_title}",
            "voiceText": "",
            "elements": [
                {
                    "id": "full",
                    "description": f"全画布内容: {scene_title}",
                    "narration": "",
                }
            ],
        })

    storyboard = {
        "meta": {
            "title": title,
            "topic": title.lower().replace(" ", "-"),
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "style": "ipad_sketch",
            "penStyle": "marker",
            "pipeline": {"mode": "video_first"},
            "subtitle": {"enabled": True, "fontSize": 36},
            "transition": {"type": "pen_wipe", "durationFrames": 25},
        },
        "scenes": scenes,
    }

    return _patch_defaults(storyboard)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Markdown → storyboard 骨架 JSON")
    parser.add_argument("--input", "-i", required=True, help="Markdown 脚本路径")
    parser.add_argument("--output", "-o", help="输出目录（默认: output/{topic}/）")
    args = parser.parse_args()

    if not args.output:
        # 从 Markdown 文件推测 topic
        topic = "untitled"
        try:
            with open(args.input, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("# ") and not line.startswith("## "):
                        topic = line[2:].strip().lower().replace(" ", "-")
                        break
        except Exception:
            pass
        args.output = str(PROJECT_ROOT / "output" / topic)

    parse_markdown_script(args.input, args.output)


if __name__ == "__main__":
    main()
