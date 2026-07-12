#!/usr/bin/env python3
"""
generate_prompts.py - 两阶段 LLM 驱动 Prompt 生成（带静态降级）。

阶段 A: DeepSeek 生成跨场景视觉风格指南
阶段 B: DeepSeek 逐场景生成详细图片 Prompt

当 DEEPSEEK_API_KEY 未设置时使用增强版静态模版。输出 prompts.json + prompts.md。
"""

import json
import os
import sys
from pathlib import Path

from config import PROJECT_ROOT, get_image_filename

# ── iPad 手绘简笔画静态模版（降级方案）──
IPAD_SKETCH_TEMPLATE = {
    "prefix": (
        "Professional hand-drawn sketch on pure white background, "
        "drawn with iPad Apple Pencil in Procreate, "
        "natural pressure-sensitive ink strokes with varying line weight "
        "(thin at start/end, thick in middle), "
        "loose organic lines with slight hand-drawn wobble, "
        "simple but expressive cartoon style, "
    ),
    "suffix": (
        "Absolutely no text, no letters, no numbers in the image. "
        "Pure white background #FFFFFF, no grid, no texture. "
        "Black ink lines as primary medium, "
        "natural line weight variation from pressure sensitivity (1-5px range). "
        "Key outlines slightly bolder, detail lines thinner. "
        "No cross-hatching or dense shading, but allow slight line-doubling "
        "on key contours for emphasis. "
        "Simple cartoon characters with round faces and basic expressions "
        "(not stick figures, not realistic). "
        "Elements well-separated with generous white space. "
        "Each element is 10-25 confident strokes, "
        "capturing essence with minimal but expressive lines. "
        "16:9 aspect ratio, balanced composition."
    ),
    "negative": (
        "text, words, letters, numbers, "
        "realistic photo, 3D render, vector art, clip art, "
        "complex shading, cross-hatching, dense hatching, stippling, "
        "gradient background, colored background, "
        "mechanical lines, ruler-straight lines, uniform line weight, "
        "stick figures, wireframe, flowchart style, "
        "photorealistic, fine detail, intricate patterns"
    ),
}

# 兼容旧版 style templates
STYLE_TEMPLATES = {
    "whiteboard": {
        "description": "Whiteboard illustration style",
        "prefix": "Whiteboard drawing style, clean line art on light background, ",
        "suffix": "Simple flat vector illustration, educational diagram style, no shading, no realistic details.",
    },
    "blackboard": {
        "description": "Blackboard chalk style",
        "prefix": "Blackboard chalk drawing style, dark green background, white and colored chalk lines, ",
        "suffix": "Chalk texture, hand-drawn look, educational diagram, slightly rough edges.",
    },
    "notebook": {
        "description": "Notebook paper style",
        "prefix": "Notebook paper style, blue grid lines on white background, ",
        "suffix": "Simple sketch, pen drawing style, clean lines, educational diagram.",
    },
    "refined_illustration": {
        "description": "Refined illustration style (deprecated)",
        "prefix": IPAD_SKETCH_TEMPLATE["prefix"],
        "suffix": IPAD_SKETCH_TEMPLATE["suffix"],
    },
    "ipad_sketch": {
        "description": "iPad hand-drawn sketch style",
        "prefix": IPAD_SKETCH_TEMPLATE["prefix"],
        "suffix": IPAD_SKETCH_TEMPLATE["suffix"],
    },
}

# ── System prompts for LLM ──

STYLE_GUIDE_SYSTEM_PROMPT = """你是一位专业的知识讲解视频视觉总监。
你的任务：基于视频的所有场景内容，制定一份统一的视觉风格指南，确保所有场景的插画在视觉上
高度一致，像出自同一位插画师之手。

画风定位：iPad 专业手绘速写
- 像用 Apple Pencil 在 Procreate 上画的专业速写
- 纯黑色墨水线条，有自然的压感粗细变化（起笔细 1px → 行笔粗 4px → 收笔细 1px）
- 关键轮廓线略粗（3-5px），辅助细节线略细（1-2px），形成视觉层次
- 线条松散有机，有轻微的手绘抖动，不死板不机械
- 人物用简化卡通形象（圆脸、简单表情、有体态特征），不是火柴人也不是写实人像
- 物体有简单的透视体积感，不是纯正面线框
- 每个元素用 10-25 笔自信的笔画，追求"以少量笔画传达神韵"
- 不画密集交叉阴影，但允许在关键轮廓处用轻微的线条加重表达立体感
- 纯白背景 #FFFFFF
- 图片中绝对不出现任何文字、字母、数字、标点

技术约束 — 路径提取兼容：
- 图片会经过骨架化提取绘画路径
- 线条必须与白色背景有强烈黑白对比
- 禁止：交叉阴影（cross-hatching）、密集填充、多笔重叠描边（这些会产生数百条碎片路径）
- 允许：自然的压感粗细变化、关键轮廓处轻微加重

构图约束：
- 元素间留足空白（至少 15% 画布宽度间隔），每个元素是一个视觉上独立的"岛"
- 元素绝不接触、不重叠
- 16:9 横版

输出 JSON 格式：
{
  "colorPalette": ["#hex1", "#hex2", ...],
  "lineStyle": "线条风格描述",
  "characterStyle": "人物造型描述（如适用）",
  "iconStyle": "图标/符号风格描述",
  "compositionRules": "构图规则",
  "moodAndTone": "整体氛围描述",
  "consistencyNotes": "跨场景一致性要点"
}"""

SCENE_PROMPT_SYSTEM_PROMPT = """你是一位专业的 AI 图片生成 prompt 工程师，擅长为知识讲解视频生成 iPad 专业手绘速写风格的图片 prompt。

你需要将简短的场景描述扩展为详细、富有想象力的图片生成 prompt，同时严格遵循以下规则：

【画风定位 — iPad 专业手绘速写】
1. 像用 Apple Pencil 在 Procreate 上画的专业速写
2. 纯黑色墨水线条，有自然的压感粗细变化（起笔细 1px → 行笔粗 4px → 收笔细 1px）
3. 关键轮廓线略粗（3-5px），辅助细节线略细（1-2px），形成视觉层次
4. 线条松散有机，有轻微的手绘抖动，不死板不机械
5. 人物用简化卡通形象（圆脸、简单表情、有体态特征），不是火柴人也不是写实人像
6. 物体有简单的透视体积感，不是纯正面线框
7. 每个元素用 10-25 笔自信的笔画，追求"以少量笔画传达神韵"
8. 不画密集交叉阴影，但允许在关键轮廓处用轻微的线条加重表达立体感
9. 纯白背景 #FFFFFF
10. 图片中绝对不出现任何文字、字母、数字、标点

【技术约束 — 路径提取兼容】
- 图片会经过骨架化提取绘画路径
- 线条必须与白色背景有强烈黑白对比
- 禁止：交叉阴影（cross-hatching）、密集填充、多笔重叠描边（这些会产生数百条碎片路径）
- 允许：自然的压感粗细变化、关键轮廓处轻微加重

【构图约束】
- 画面比例: 16:9（横版）
- 元素空间分布: 按场景描述中的位置关系布局，元素间留足空白
- 每个元素应该是一个视觉上独立的"岛"，不与其他元素粘连

输出严格的 JSON 格式：
{
  "imagePrompt": "完整的正面 prompt，200-400 字，详细描述画面内容、风格、构图",
  "negativePrompt": "需要避免的内容，如文字、写实风、复杂背景等",
  "compositionNotes": "给生图者的构图提示，说明各元素的空间位置关系",
  "imageName": "sceneX.png"
}"""


# ── 生成风格指南（阶段 A）──
def generate_style_guide(storyboard: dict) -> dict:
    """阶段 A：通过 DeepSeek 生成跨场景风格指南。"""
    from llm_client import call_deepseek_json

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])

    scene_descriptions = []
    for i, scene in enumerate(scenes):
        sid = scene.get("id", f"scene{i+1}")
        image_prompt = scene.get("imagePrompt", "") or scene.get("description", "")
        voice_text = scene.get("voiceText", "")
        scene_descriptions.append(
            f"场景 {i+1} ({sid}):\n"
            f"  画面描述: {image_prompt}\n"
            f"  旁白: {voice_text}\n"
        )

    user_prompt = (
        f"视频标题: {meta.get('title', 'Untitled')}\n"
        f"共 {len(scenes)} 个场景:\n\n"
        + "\n".join(scene_descriptions)
        + "\n请为这组场景制定统一的精致插画风风格指南。"
    )

    print(f"  [LLM] 生成风格指南 ({len(scenes)} 场景)...")
    result = call_deepseek_json(STYLE_GUIDE_SYSTEM_PROMPT, user_prompt,
                                 temperature=0.5, max_tokens=2000)
    print(f"  [LLM] 风格指南完成: {result.get('colorPalette', [])}")
    return result


# ── 生成场景 Prompt（阶段 B）──
def generate_scene_prompt(
    scene: dict,
    scene_index: int,
    total_scenes: int,
    style_guide: dict,
    previous_scenes: list[dict],
) -> dict:
    """阶段 B：通过 DeepSeek 为单个场景生成详细 prompt。"""
    from llm_client import call_deepseek_json

    scene_id = scene.get("id", f"scene{scene_index+1}")
    image_prompt = scene.get("imagePrompt", "") or scene.get("description", "")
    voice_text = scene.get("voiceText", "")
    elements = scene.get("elements", [])

    # 前序场景摘要
    prev_summaries = []
    for ps in previous_scenes:
        ps_id = ps.get("id", "?")
        ps_prompt = ps.get("imagePrompt", "") or ps.get("description", "")
        prev_summaries.append(f"  场景 {ps_id}: {ps_prompt[:100]}")

    user_prompt = (
        f"【风格指南】\n{json.dumps(style_guide, ensure_ascii=False, indent=2)}\n\n"
        f"【当前场景】\n"
        f"场景 ID: {scene_id}\n"
        f"场景序号: 第 {scene_index+1}/{total_scenes} 场景\n"
        f"画面描述: {image_prompt}\n"
        f"旁白文案: {voice_text}\n"
        f"元素列表: {[e.get('description', e.get('id', '?')) for e in elements]}\n\n"
        f"【前序场景摘要】（保持一致性参考）\n"
        + "\n".join(prev_summaries) + "\n\n"
        f"请生成精致插画风的详细图片 prompt。\n"
        f"文件名必须为: {get_image_filename(scene_id)}"
    )

    print(f"  [LLM] 场景 {scene_index+1}/{total_scenes}: {scene_id}...")
    result = call_deepseek_json(SCENE_PROMPT_SYSTEM_PROMPT, user_prompt,
                                 temperature=0.7, max_tokens=3000)
    # 确保 imageName 正确
    result.setdefault("imageName", get_image_filename(scene_id))
    return result


# ── 静态降级方案 ──
def _fallback_static_prompt(scene: dict, style_name: str = "ipad_sketch") -> dict:
    """无 LLM 时的降级方案：增强版静态模版。"""
    scene_id = scene.get("id", "scene?")
    image_prompt = scene.get("imagePrompt", "") or scene.get("description", "")
    style = STYLE_TEMPLATES.get(style_name, IPAD_SKETCH_TEMPLATE)
    negative = style.get("negative", IPAD_SKETCH_TEMPLATE.get("negative", ""))

    return {
        "imagePrompt": f"{style['prefix']}{image_prompt} {style['suffix']}",
        "negativePrompt": negative,
        "compositionNotes": "元素均匀分布在 16:9 画布上，留足空白",
        "imageName": get_image_filename(scene_id),
    }


# ── 格式化输出 ──
def _format_prompts_md(prompts_data: dict, meta: dict) -> str:
    """格式化为人类友好的 Markdown，含醒目文件名指引。"""
    lines = []
    title = meta.get("title", "Untitled")
    lines.append(f"# 图片生成指南: {title}")
    lines.append("")
    lines.append(f"**画风**: iPad 手绘简笔画风")
    scenes_data = prompts_data.get("scenes", [])
    lines.append(f"**场景数**: {len(scenes_data)}")
    style_guide = prompts_data.get("styleGuide", {})
    if style_guide.get("colorPalette"):
        lines.append(f"**配色方案**: {', '.join(style_guide['colorPalette'])}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 文件名汇总表
    lines.append("## 文件名清单")
    lines.append("")
    lines.append("| 场景 | 文件名 | 保存到 |")
    lines.append("|------|--------|--------|")
    topic = meta.get("topic", "untitled")
    for s in scenes_data:
        lines.append(f"| {s.get('sceneId', '?')} | {s.get('imageName', '?')} | output/{topic}/images/ |")
    lines.append("")
    lines.append("**注意：文件名必须精确匹配（小写，.png 后缀）**")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, s in enumerate(scenes_data):
        lines.append(f"## 场景 {i+1}: {s.get('sceneId', f'scene{i+1}')}")
        lines.append("")
        lines.append("### ============================================")
        lines.append(f"###   请保存为: {s.get('imageName', f'scene{i+1}.png')}")
        lines.append("### ============================================")
        lines.append("")
        lines.append("**Prompt (复制到 Seedream):**")
        lines.append("")
        lines.append(s.get("imagePrompt", ""))
        lines.append("")
        if s.get("negativePrompt"):
            lines.append("**负面提示词:**")
            lines.append(s["negativePrompt"])
            lines.append("")
        if s.get("compositionNotes"):
            lines.append("**构图说明:**")
            lines.append(s["compositionNotes"])
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ── 主入口 ──
def generate_prompts(
    storyboard: dict,
    output_dir: str = None,
    use_llm: bool = True,
) -> tuple[dict, str]:
    """主入口。生成 prompts.json + prompts.md。

    Args:
        storyboard: 解析后的 storyboard dict
        output_dir: 输出目录（存放 prompts.json 和 prompts.md）
        use_llm: 是否使用 LLM（False = 静态降级）

    Returns:
        (prompts_data, prompts_md_text)
    """
    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])
    style_name = meta.get("style", meta.get("imageStyle", "refined_illustration"))

    prompts_data = {"styleGuide": {}, "scenes": []}

    if use_llm:
        try:
            from llm_client import call_deepseek_json
            # 先检查 API key
            _ = call_deepseek_json  # trigger import check

            # 阶段 A: 风格指南
            style_guide = generate_style_guide(storyboard)
            prompts_data["styleGuide"] = style_guide

            # 阶段 B: 逐场景 Prompt
            previous_scenes = []
            for i, scene in enumerate(scenes):
                scene_id = scene.get("id", f"scene{i+1}")
                result = generate_scene_prompt(
                    scene, i, len(scenes), style_guide, previous_scenes
                )
                prompts_data["scenes"].append({
                    "sceneId": scene_id,
                    "imageName": result.get("imageName", get_image_filename(scene_id)),
                    "imagePrompt": result.get("imagePrompt", ""),
                    "negativePrompt": result.get("negativePrompt", ""),
                    "compositionNotes": result.get("compositionNotes", ""),
                })
                previous_scenes.append(scene)

            print(f"\n  [LLM] 所有 {len(scenes)} 个场景的 prompt 生成完成！")

        except (ImportError, RuntimeError, Exception) as e:
            print(f"\n  [WARN] LLM 不可用，使用静态降级模版: {e}")
            use_llm = False

    if not use_llm:
        print(f"\n  [STATIC] 使用 {style_name} 风格静态模版生成 prompts...")
        for i, scene in enumerate(scenes):
            scene_id = scene.get("id", f"scene{i+1}")
            result = _fallback_static_prompt(scene, style_name)
            prompts_data["scenes"].append({
                "sceneId": scene_id,
                "imageName": result["imageName"],
                "imagePrompt": result["imagePrompt"],
                "negativePrompt": result["negativePrompt"],
                "compositionNotes": result["compositionNotes"],
            })

    # 生成 prompts.md
    prompts_md = _format_prompts_md(prompts_data, meta)

    # 写文件
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

        # prompts.json
        json_path = os.path.join(output_dir, "prompts.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(prompts_data, f, ensure_ascii=False, indent=2)
        print(f"  Wrote: {json_path}")

        # prompts.md
        md_path = os.path.join(output_dir, "prompts.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(prompts_md)
        print(f"  Wrote: {md_path}")

    return prompts_data, prompts_md


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate image prompts with LLM")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    parser.add_argument("--no-llm", action="store_true", help="Force static template (no LLM)")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    if not args.output_dir:
        topic = storyboard.get("meta", {}).get("topic", "untitled")
        args.output_dir = str(PROJECT_ROOT / "output" / topic)

    generate_prompts(storyboard, args.output_dir, use_llm=not args.no_llm)
