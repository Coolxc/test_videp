#!/usr/bin/env python3
"""
generate_prompts.py - Generate image prompts from storyboard.json.

Includes spatial separation guidance for multi-element scenes and
cross-scene style consistency instructions.
"""

import json
import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# Style templates
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
}

SPATIAL_GUIDANCE = (
    "Ensure each element has clear blank space separation from others. "
    "Do NOT overlap elements. Leave at least 10% of the canvas width between distinct elements. "
    "Composition should be well-balanced with elements distributed across the canvas."
)

CONSISTENCY_GUIDANCE = (
    "Keep the whole series visually consistent. "
    "Use the same line thickness, character proportions, and color palette across all scenes. "
    "Maintain consistent perspective and visual style."
)


def generate_prompts(storyboard: dict, output_path: str = None) -> str:
    """Generate prompts.md from storyboard.json."""
    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])
    style_name = meta.get("imageStyle", "whiteboard")
    style = STYLE_TEMPLATES.get(style_name, STYLE_TEMPLATES["whiteboard"])
    topic = meta.get("topic", "untitled")

    lines = []
    lines.append(f"# Image Prompts: {meta.get('title', 'Untitled')}")
    lines.append(f"")
    lines.append(f"**Style:** {style['description']}")
    lines.append(f"**Total Scenes:** {len(scenes)}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    for i, scene in enumerate(scenes):
        lines.append(f"## Scene {i + 1}: {scene.get('id', f'scene{i+1}')}")
        lines.append(f"")

        elements = scene.get("elements", [])
        if len(elements) > 1:
            lines.append(f"### Image Prompt (with spatial separation)")
            lines.append(f"")
            lines.append(f"{style['prefix']}{scene.get('imagePrompt', '')}")
            lines.append(f"")
            lines.append(f"**Spatial arrangement hints:**")
            lines.append(f"{SPATIAL_GUIDANCE}")
            for j, elem in enumerate(elements):
                desc = elem.get("description", f"Element {j+1}")
                bbox = elem.get("bbox", {})
                pos_hint = _position_hint(bbox)
                lines.append(f"  - {desc} ({pos_hint})")
            lines.append(f"")
            lines.append(f"{style['suffix']}")
        else:
            lines.append(f"### Image Prompt")
            lines.append(f"")
            lines.append(f"{style['prefix']}{scene.get('imagePrompt', '')}")
            lines.append(f"")
            lines.append(f"{style['suffix']}")

        if scene.get("voiceText"):
            lines.append(f"")
            lines.append(f"**Voiceover:** {scene['voiceText']}")

        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    # Cross-scene consistency
    lines.append(f"## Cross-Scene Consistency")
    lines.append(f"")
    lines.append(f"{CONSISTENCY_GUIDANCE}")
    lines.append(f"")
    lines.append(f"**For image generation tools:** If the tool supports reference images, "
                 f"upload the generated image from Scene 1 as a style reference for subsequent scenes.")
    lines.append(f"")

    # Tool-specific instructions
    lines.append(f"## Tool-Specific Tips")
    lines.append(f"")
    lines.append(f"- **Midjourney:** Use `--iw 2 --s 50` for style consistency")
    lines.append(f"- **DALL-E:** Include 'keep visual style consistent across series' in each prompt")
    lines.append(f"- **Stable Diffusion:** Use same seed and CFG scale (~7) for all scenes")
    lines.append(f"- **GPT-4o / Claude:** Reference the previous image when generating the next")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"**Important:** No text/characters in the generated images. "
                 f"All text overlays are added in post-production.")

    prompt_text = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        print(f"  Wrote prompts: {output_path}")

    return prompt_text


def _position_hint(bbox: dict) -> str:
    """Generate a human-readable position hint from bbox coordinates."""
    if not bbox:
        return "center"
    cx = bbox.get("x", 0) + bbox.get("w", 0) / 2
    cy = bbox.get("y", 0) + bbox.get("h", 0) / 2

    h_pos = "center" if abs(cx - 960) < 320 else ("left" if cx < 640 else "right")
    v_pos = "center" if abs(cy - 540) < 180 else ("top" if cy < 360 else "bottom")
    return f"{v_pos}-{h_pos}" if v_pos != "center" or h_pos != "center" else "center"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate image prompts from storyboard.json")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output", "-o", help="Output prompts.md path")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    if not args.output:
        args.output = str(_PROJECT_ROOT / "output" / topic / "prompts.md")

    generate_prompts(storyboard, args.output)
