# V2 重构方案：商业级知识讲解手绘视频管线

## 一句话目标

用户提供结构化分镜 JSON → DeepSeek 生成精致插画风 Prompt → 用户在 Seedream 手动生图 → 管线自动输出流畅专业的商业级手绘动画视频。

---

## 当前致命问题

| # | 问题 | 影响 | 根因 |
|---|------|------|------|
| 1 | 生图 Prompt 是固定字符串拼接 | 生成的图基本不可用，无创意、无一致性 | `generate_prompts.py` 只做 `prefix + imagePrompt + suffix`，零 LLM 参与 |
| 2 | 图片文件名隐式约定 | 渲染时找不到图，管线静默跳过 | 多处独立拼接 `{scene_id}.png`，从不告知用户该存什么名 |
| 3 | 手绘动画只画一部分 | 画面不完整，内容缺失 | bbox 在图生成前定义、`filter_draw_order_for_bbox` 无 padding、背景修复误伤浅色内容 |
| 4 | 多处代码 Bug | 管线无法正确跑通 | 帧号计算单位错误、条件重复、路径不存在、数据丢失 |

## 技术栈

- **LLM**: DeepSeek API（文本生成，prompt 创作 + 风格一致性）
- **图片生成**: Seedream 网页平台（手动操作）
- **动画引擎**: [whiteboard-video-workflow](https://github.com/liekkasfc/whiteboard-video-workflow.git)（外部依赖，不修改）
- **视频合成**: Remotion 4.0
- **画风**: 精致插画风（非白板简笔画）

## 关键约束

1. **不修改动画引擎** `generate_whiteboard.py` 的任何代码，所有适配在 wrapper 层完成
2. 引擎使用 `cv2.adaptiveThreshold(gray, 255, ADAPTIVE_THRESH_GAUSSIAN_C, THRESH_BINARY, 15, 10)` 检测内容 → 图片必须在浅色背景上有可检测的边缘
3. 精致插画风的色彩丰富度远高于白板简笔画，但只要有清晰边缘就能被引擎正确处理
4. 图片在 Seedream 手动生成，管线必须给出明确的文件名指引

## 改动优先级

| 优先级 | 内容 | 文件数 | 商业影响 |
|--------|------|--------|----------|
| **P0** | Bug 修复 + 路径集中管理 | 6 文件 | 管线能跑通 |
| **P1** | DeepSeek 驱动 Prompt 生成 | 3 新/改文件 | 生图质量根本性提升 |
| **P2** | 修复"只画一部分" | 4 文件 | 动画完整性 |
| **P3** | 图片命名显式化 + 快速失败 | 3 文件 | 用户体验 |
| **P4** | Remotion 修复 + Schema 演进 | 4 文件 | 成片质量 |

## 文档索引

- [01-bug-fixes.md](01-bug-fixes.md) — P0: Bug 修复与路径集中管理
- [02-llm-prompt-generation.md](02-llm-prompt-generation.md) — P1: DeepSeek 驱动的 Prompt 生成
- [03-fix-partial-drawing.md](03-fix-partial-drawing.md) — P2: 修复"只画一部分"
- [04-image-naming.md](04-image-naming.md) — P3: 图片命名显式化 + 快速失败
- [05-remotion-and-schema.md](05-remotion-and-schema.md) — P4: Remotion 修复 + Schema 演进
- [06-implementation-sequence.md](06-implementation-sequence.md) — 实施顺序与验证方法


# P0: Bug 修复与路径集中管理

所有改动都是小范围、定点修复，互不依赖，可并行实施。

---

## 0-1. 新建 `scripts/config.py` — 路径集中管理

**问题**: 多个脚本各自硬编码路径 `_PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-animation"`，该路径在项目目录内不存在（引擎是独立仓库）。`deploy_resources.py` 引用 `_PROJECT_ROOT / "whiteboard-video"` 也不存在。路径散落在 5 个文件中，改动困难。

**方案**: 新建集中配置模块，所有脚本从此导入。

```python
# scripts/config.py
"""项目级配置：路径解析、常量、工具函数。所有脚本从此导入。"""

import os
from pathlib import Path

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 外部引擎路径（优先读环境变量，便于不同部署环境适配）──
ENGINE_DIR = Path(os.environ.get(
    "WHITEBOARD_ENGINE_DIR",
    str(PROJECT_ROOT.parent / "whiteboard-video-workflow" / "whiteboard-animation")
))
ENGINE_SCRIPTS_DIR = ENGINE_DIR / "scripts"
ENGINE_HAND_PATH = ENGINE_DIR / "assets" / "drawing-hand.png"

# ── Prompt 模版仓库路径 ──
WORKFLOW_DIR = Path(os.environ.get(
    "WHITEBOARD_WORKFLOW_DIR",
    str(PROJECT_ROOT.parent / "whiteboard-video-workflow" / "whiteboard-video-workflow")
))

# ── 视觉常量 ──
BACKGROUND_HEX = "#F6F1E3"
BACKGROUND_BGR = (227, 241, 246)  # OpenCV BGR 格式
BACKGROUND_RGB = (246, 241, 227)

# ── 图片命名 ──
def get_image_filename(scene_id: str) -> str:
    """标准图片文件名。全管线唯一命名规则。"""
    return f"{scene_id}.png"

def get_output_dir(storyboard: dict) -> Path:
    """从 storyboard meta 计算输出目录。"""
    import time
    topic = storyboard.get("meta", {}).get("topic", "untitled")
    # 清理不安全字符
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic)
    return PROJECT_ROOT / "output" / f"{safe_topic}-{time.strftime('%Y%m%d')}"

def validate_engine():
    """启动时检查引擎是否可用。"""
    errors = []
    if not ENGINE_DIR.exists():
        errors.append(f"动画引擎目录不存在: {ENGINE_DIR}")
    if not (ENGINE_SCRIPTS_DIR / "generate_whiteboard.py").exists():
        errors.append(f"引擎脚本不存在: {ENGINE_SCRIPTS_DIR / 'generate_whiteboard.py'}")
    if not ENGINE_HAND_PATH.exists():
        errors.append(f"画手素材不存在: {ENGINE_HAND_PATH}")
    return errors
```

**受影响文件及改动**:

| 文件 | 当前路径代码 | 改为 |
|------|-------------|------|
| `generate_scene_animation.py:31` | `_ENGINE_DIR = _PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-animation"` | `from config import ENGINE_DIR, ENGINE_SCRIPTS_DIR, ENGINE_HAND_PATH` |
| `generate_scene_animation.py:32` | `sys.path.insert(0, str(_ENGINE_DIR / "scripts"))` | `sys.path.insert(0, str(ENGINE_SCRIPTS_DIR))` |
| `generate_scene_animation.py:34-35` | 两个 `assert` | 删除，改用 `config.validate_engine()` |
| `validate.py:22` | 内联路径检查 | `from config import validate_engine` |
| `deploy_resources.py:67` | `_PROJECT_ROOT / "whiteboard-video" / ...` | `from config import WORKFLOW_DIR` 或直接检查资源是否在 remotion-project 中 |
| `deploy_resources.py:85-86` | `_PROJECT_ROOT / "whiteboard-video-workflow" / ...` | `from config import ENGINE_HAND_PATH` |
| `tts_pipeline.py:46` | `_PROJECT_ROOT / "whiteboard-video" / "scripts" / "tts_tencent.py"` | `from config import WORKFLOW_DIR; TTS_SCRIPT = WORKFLOW_DIR / "scripts" / "tts_tencent.py"` |
| `make_video.py:44-45` | `_get_output_dir` 内联实现 | `from config import get_output_dir` |

---

## 0-2. `scripts/make_video.py` 第 185 行 — 重复条件

**问题**: `if mode == "full" or mode == "full":` 条件重复，第二个分支可能本应是其他 mode。

**修复**:
```python
# 修复前 (line 185)
if mode == "full" or mode == "full":

# 修复后
if mode == "full":
```

---

## 0-3. `scripts/compute_timeline.py` — sequential 模式帧号计算错误

**问题**: `current_time` 变量单位是秒（通过 `transition_s` 和 `elem["durationMs"] / 1000.0` 累加），但帧号转换公式 `current_time * anim_fps / 1000` 多除了一个 1000，把秒当成了毫秒。

**影响**: sequential 模式下所有元素的 `sketchAtFrame` 和 `colorizeAtFrame` 会偏小 1000 倍，导致动画时序完全错误。

**修复位置**: `compute_timeline.py` 约第 171 行和第 173 行

```python
# ── 修复前 ──
"sketchAtFrame": round(current_time * anim_fps / 1000),
"colorizeAtFrame": round((current_time + sketch_frames / anim_fps) * anim_fps / 1000),

# ── 修复后 ──
"sketchAtFrame": round(current_time * anim_fps),
"colorizeAtFrame": round(current_time * anim_fps + sketch_frames),
```

---

## 0-4. `scripts/compute_timeline.py` — sketch_first 阶段过渡时长

**问题**: 第 139 行（或附近）的阶段过渡时长计算：`1.5 * transition_ms * 1.5` = `2.25 * transition_ms`。根据 plan.md 设计文档，阶段过渡应为标准过渡的 1.5 倍，即 `1.5 * transition_ms`。

**修复**:
```python
# 修复前
colorize_start = (... + 1.5 * transition_ms * 1.5)

# 修复后
colorize_start = (... + 1.5 * transition_ms)
```

---

## 0-5. `scripts/deploy_resources.py` — 两个数据传递问题

### 问题 A: scene-config.json 丢弃 elements 数据

`_update_scene_config` 函数在构建 `scenes_out` 时只复制了 `id`、`imagePrompt`、`voiceText`、`duration`、`textOverlay`，**丢弃了 `elements` 字段**。Remotion 侧 `WhiteboardVideo.tsx` 需要通过 `scene.elements` 获取旁白文本。

**修复**（约第 119 行）:
```python
# 在 scene_out dict 中增加：
"elements": scene.get("elements", []),
```

### 问题 B: timeline.json 部署路径错误

当前逻辑试图从 `remotion_public / "timeline.json"` 拷贝到 `src/`，但管线把 timeline.json 写在 output 目录，不在 public/ 下。

**修复**: `deploy_resources` 函数接收 `output_dir` 参数，从 `output_dir / "timeline.json"` 拷贝到 `remotion-project/public/timeline.json` 和 `remotion-project/src/timeline.json`。

```python
def deploy_resources(storyboard_path, output_dir, ..., timeline_path=None):
    # ...
    if timeline_path and os.path.exists(timeline_path):
        shutil.copy2(timeline_path, remotion_public / "timeline.json")
        shutil.copy2(timeline_path, remotion_src / "timeline.json")
```

同步修改 `make_video.py` 中调用 `deploy_resources` 时传入 `timeline_path=str(timeline_path)`。


# P1: DeepSeek 驱动的 Prompt 生成

**这是提升成片质量的最关键改动。** 当前 `generate_prompts.py` 仅做字符串拼接，零 LLM 参与，生成的图「基本不可用」。

---

## 问题分析

### 当前 Prompt 生成流程

```
imagePrompt (storyboard.json 中用户手写)
    ↓
"Whiteboard drawing style, clean line art..." + imagePrompt + "Simple flat vector illustration..."
    ↓
prompts.md (用户拿这段文本去手动生图)
```

**致命缺陷**:
1. **无创意扩展**: 用户在 storyboard 中写的 `imagePrompt` 通常很简短（如「火柴人坐在电脑前」），prompt 长度和细节完全不足以驱动高质量出图
2. **无风格一致性**: 每个场景的 prompt 独立生成，没有跨场景的角色设计、配色方案、构图规则约束
3. **固定白板风格**: prefix/suffix 锁死了「Whiteboard drawing style」，而目标是「精致插画风」
4. **无负面提示词**: 商业级生图严重依赖 negative prompt 来抑制不需要的元素
5. **无构图指导**: 只有粗糙的位置提示（"top-left"），缺乏专业的构图建议
6. **无空间分离保障**: 当前 `SPATIAL_GUIDANCE` 是静态英文文本，AI 生图工具对此理解不稳定

### 目标 Prompt 生成流程

```
scene.imagePrompt + scene.voiceText + 全局上下文
    ↓ DeepSeek API
风格指南 (跨场景一致性)
    ↓ DeepSeek API × N 场景
每场景: imagePrompt + negativePrompt + compositionNotes + imageName
    ↓
prompts.json (结构化) + prompts.md (人类友好，含醒目文件名)
```

---

## 新建文件

### `scripts/llm_client.py` — DeepSeek API 封装

```python
"""DeepSeek API 客户端。所有 LLM 调用通过此模块。"""

import json
import os
import time
import requests
from typing import Optional

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
    import re
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # 尝试提取第一个 { ... } 块
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"无法从 LLM 响应中提取 JSON:\n{text[:500]}")
```

---

## 重写 `scripts/generate_prompts.py`

### 核心设计：两阶段 LLM 生成

#### 阶段 A: 风格指南生成（一次调用 / 整个 storyboard）

将所有场景的描述和旁白发给 DeepSeek，生成统一的视觉风格指南，确保跨场景一致性。

**系统提示**:
```
你是一位专业的知识讲解视频视觉总监。
你的任务：基于视频的所有场景内容，制定一份统一的视觉风格指南，确保所有场景的插画在视觉上
高度一致，像出自同一位插画师之手。

画风定位：精致插画风
- 清晰精确的线条，一致的线宽
- 丰富和谐的配色，不超过 5-7 种主色
- 细腻的层次感，不要硬渐变
- 专业矢量插画质感，类似高端信息图/商业演示
- 浅色/奶油色背景（#F6F1E3 或相近色）
- 图片中绝对不出现任何文字

输出 JSON 格式：
{
  "colorPalette": ["#hex1", "#hex2", ...],  // 5-7 种主色
  "lineStyle": "线条风格描述",
  "characterStyle": "人物造型描述（如适用）",
  "iconStyle": "图标/符号风格描述",
  "compositionRules": "构图规则",
  "moodAndTone": "整体氛围描述",
  "consistencyNotes": "跨场景一致性要点"
}
```

**用户提示**:
```
视频标题: {title}
共 {n} 个场景:

场景 1 ({scene_id}):
  画面描述: {imagePrompt 或 description}
  旁白: {voiceText}

场景 2 ({scene_id}):
  ...

请为这组场景制定统一的精致插画风风格指南。
```

#### 阶段 B: 逐场景 Prompt 生成（每场景一次调用）

将单个场景的描述 + 风格指南 + 前序场景摘要发给 DeepSeek，生成详细的图片生成 prompt。

**系统提示**:
```
你是一位专业的 AI 图片生成 prompt 工程师，擅长为知识讲解视频生成精致插画风的图片 prompt。

你需要将简短的场景描述扩展为详细、富有想象力的图片生成 prompt，同时严格遵循以下规则：

【画风规则 — 精致插画风】
1. 清晰精确的线条，一致的 2-3px 线宽，轻微手绘质感
2. 色彩丰富但和谐，使用指定的配色方案
3. 细腻的阴影和层次感，不要照片级写实
4. 专业矢量插画质感，类似高端商业信息图
5. 浅色/奶油色背景（#F6F1E3）——这是强制要求，不可更改
6. 图片中绝对不出现任何文字、字母、数字、标点——文字全部在后期视频合成时叠加
7. 各元素之间必须有清晰的空白分离（至少 10% 画布宽度），用于动画分区检测

【技术约束 — 动画引擎兼容】
- 图片会经过灰度转换 + 自适应阈值处理来检测内容边缘
- 因此：所有绘制内容的边缘必须与背景有明显色差/对比度
- 避免：大面积纯渐变（无法检测边缘）、内容与背景融为一体的设计
- 建议：用清晰的轮廓线包围每个元素，即使是柔和的插画风也要有可辨识的边界

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
}
```

**用户提示**:
```
【风格指南】
{style_guide_json}

【当前场景】
场景 ID: {scene_id}
场景序号: 第 {i+1}/{total} 场景
画面描述: {imagePrompt 或 description}
旁白文案: {voiceText}
元素列表: {elements 描述，如果有的话}

【前序场景摘要】（保持一致性参考）
场景 1: {scene1 的 imagePrompt 摘要}
场景 2: ...

请生成精致插画风的详细图片 prompt。
文件名必须为: {scene_id}.png
```

### 输出格式

#### `prompts.json` — 程序可读

```json
{
  "styleGuide": {
    "colorPalette": ["#2D3748", "#C05050", "#4299E1", "#48BB78", "#ECC94B"],
    "lineStyle": "2-3px 一致线宽，轻微手绘质感的矢量线条",
    "characterStyle": "简约人物，圆润头部，不画五官细节，用肢体语言表达",
    "iconStyle": "扁平化图标，圆角矩形，轻微阴影",
    "compositionRules": "16:9 横版，元素占画面 60-80%，元素间留 10%+ 空白",
    "moodAndTone": "专业、温暖、易于理解",
    "consistencyNotes": "所有场景使用相同的线宽、人物比例和配色"
  },
  "scenes": [
    {
      "sceneId": "scene1",
      "imageName": "scene1.png",
      "imagePrompt": "精致矢量插画，浅米色背景(#F6F1E3)。画面左侧...",
      "negativePrompt": "文字, 字母, 数字, 写实照片, 3D渲染, 复杂背景, 渐变背景",
      "compositionNotes": "人物占据画面左三分之一，时钟在右上方，纸币散落在右下方"
    }
  ]
}
```

#### `prompts.md` — 人类友好

```markdown
# 图片生成指南: {title}

**画风**: 精致插画风
**场景数**: {n}
**配色方案**: {colorPalette}

---

## 场景 1: scene1

### ============================================
###   请保存为: scene1.png
### ============================================

**Prompt (复制到 Seedream):**

精致矢量插画，浅米色背景(#F6F1E3)。画面左侧一个简约风格的人物坐在
现代简洁的办公桌前，低头专注于电脑屏幕，头顶三颗汗珠表示紧张忙碌。
人物采用圆润头部设计，不画五官细节，用弯曲的肩膀和低垂的头部表达
疲惫感。右上方一个精致的复古闹钟，时针呈旋转模糊效果暗示时间飞逝，
表盘边缘有轻微阴影增加立体感。右下角散落 3-4 张纸币，采用简洁的
矩形加对角线设计...

**负面提示词:**
文字, 字母, 数字, 写实照片, 3D渲染, 复杂背景, 渐变背景, 水彩质感

**构图说明:**
人物占据画面左三分之一区域（x: 50-550），时钟在右上方（x: 700-1100, y: 50-450），
纸币散落在右下方（x: 750-1100, y: 550-850）。三个元素之间有清晰的空白间隔。

---
```

### 关键函数签名

```python
# scripts/generate_prompts.py（完全重写）

def generate_style_guide(storyboard: dict) -> dict:
    """阶段 A：通过 DeepSeek 生成跨场景风格指南。"""

def generate_scene_prompt(
    scene: dict,
    scene_index: int,
    total_scenes: int,
    style_guide: dict,
    previous_scenes: list[dict],
) -> dict:
    """阶段 B：通过 DeepSeek 为单个场景生成详细 prompt。"""

def generate_prompts(
    storyboard: dict,
    output_dir: str,
    use_llm: bool = True,
) -> tuple[dict, str]:
    """主入口。返回 (prompts_data, prompts_md_text)。
    use_llm=False 时 fallback 到增强版静态模版。"""

def _fallback_static_prompt(scene: dict, style: str) -> dict:
    """无 LLM 时的降级方案：增强版静态模版（含精致插画风模版）。"""

def _format_prompts_md(prompts_data: dict, meta: dict) -> str:
    """格式化为人类友好的 Markdown。"""
```

### Fallback 策略

当 `DEEPSEEK_API_KEY` 未设置时：
1. 打印醒目警告：`[WARN] DEEPSEEK_API_KEY 未设置，使用静态模版（质量显著降低）`
2. 使用增强版静态模版（比当前版本好，但远不如 LLM 版本）
3. 增强版模版包含精致插画风的 prefix/suffix，比当前 whiteboard 风格更适合目标画风

增强版精致插画风静态模版：
```python
REFINED_ILLUSTRATION_TEMPLATE = {
    "prefix": (
        "Refined vector illustration, clean precise linework with consistent 2-3px weight, "
        "rich harmonious colors, subtle shadows and depth, professional infographic aesthetic, "
        "light cream background (#F6F1E3), "
    ),
    "suffix": (
        "No text, no letters, no numbers, no typography whatsoever. "
        "Clear outlines around every element. "
        "Elements well-separated with clear blank space between them. "
        "16:9 aspect ratio, balanced composition. "
        "Consistent visual style suitable for educational video series."
    ),
    "negative": (
        "text, words, letters, numbers, typography, realistic photo, 3D render, "
        "complex background, gradient background, watercolor texture, "
        "painterly style, high saturation, busy composition"
    ),
}
```

### 更新 `scripts/validate.py`

新增 DeepSeek API key 检查（非强制，缺失时打印警告而非报错）：

```python
def check_llm_keys() -> list[str]:
    warnings = []
    if not os.environ.get("DEEPSEEK_API_KEY"):
        warnings.append(
            "DEEPSEEK_API_KEY 未设置，prompt 生成将使用静态模版（质量降低）"
        )
    return warnings
```

# P2: 修复"只画一部分"问题

**表现**: 手绘动画中部分元素只画出了一半，或者某些图片内容完全没有被动画引擎绘制。

---

## 根因分析

"只画一部分"有三个独立根因，需要分别修复：

### 根因 1: bbox 过滤无 padding

`generate_scene_animation.py` 的 `filter_draw_order_for_bbox`（第 324-335 行）按 bbox 严格过滤 draw order：

```python
def filter_draw_order_for_bbox(full_draw_order, scaled_bbox):
    x_min = scaled_bbox["x"] // SPLIT_LEN
    y_min = scaled_bbox["y"] // SPLIT_LEN
    x_max = (scaled_bbox["x"] + scaled_bbox["w"]) // SPLIT_LEN
    y_max = (scaled_bbox["y"] + scaled_bbox["h"]) // SPLIT_LEN
    filtered = [
        cell for cell in full_draw_order
        if y_min <= cell[0] <= y_max and x_min <= cell[1] <= x_max
    ]
    return filtered
```

**问题**: 零 padding。如果用户定义的 bbox 比实际图片内容稍小（很常见，因为 bbox 在生图前预估），边缘的 grid cell 被排除在外，导致内容被截断。

### 根因 2: 背景修复误伤内容

`validate_images.py` 的 `fix_background_color`（约第 96-112 行）：

```python
mask = cv2.inRange(img, (200, 210, 220), (255, 255, 255))
img[mask > 0] = np.array([227, 241, 246], dtype=np.uint8)
```

**问题**: 所有 BGR 在 `(200-255, 210-255, 220-255)` 范围的像素都被替换为背景色。这会覆盖：
- 浅蓝色元素（如天空、水面）
- 浅黄色元素（如灯光、金币高光）
- 浅粉色元素
- 任何浅色绘制内容

被替换为背景色后，这些内容对引擎的自适应阈值处理完全不可见 → 不产生 active grid cell → 不被绘制。

### 根因 3: bbox 预估与实际不匹配

用户在 storyboard.json 中预定义 `elements[].bbox`，但图片尚未生成。当用户在 Seedream 生成图片后，实际元素位置和尺寸可能与预估差异显著 → bbox 范围外的内容不被绘制。

---

## 修复方案

### 2-1. `scripts/generate_scene_animation.py` — bbox 过滤加 padding

给 `filter_draw_order_for_bbox` 加入可配置的 padding，默认 10% bbox 尺寸（最少 2 个 grid cell）：

```python
def filter_draw_order_for_bbox(full_draw_order, scaled_bbox, padding_ratio=0.10):
    """过滤 draw order 到 bbox 内的 cell，带 padding 防止边缘截断。

    padding_ratio: bbox 尺寸的百分比作为额外边距，默认 10%。
    最小 padding 为 2 个 grid cell（20px at SPLIT_LEN=10）。
    """
    pad_x = max(2, int(scaled_bbox["w"] * padding_ratio / SPLIT_LEN))
    pad_y = max(2, int(scaled_bbox["h"] * padding_ratio / SPLIT_LEN))

    x_min = max(0, scaled_bbox["x"] // SPLIT_LEN - pad_x)
    y_min = max(0, scaled_bbox["y"] // SPLIT_LEN - pad_y)
    x_max = (scaled_bbox["x"] + scaled_bbox["w"]) // SPLIT_LEN + pad_x
    y_max = (scaled_bbox["y"] + scaled_bbox["h"]) // SPLIT_LEN + pad_y

    return [
        cell for cell in full_draw_order
        if y_min <= cell[0] <= y_max and x_min <= cell[1] <= x_max
    ]
```

**影响分析**: padding 扩大了每个元素的绘制范围。在多元素场景中，相邻元素的 padding 区域可能重叠 → 重叠 cell 被两个元素各画一次 → sketch 阶段没问题（同一 cell 画两次视觉一样），colorize 阶段也没问题（第二次 alpha blend 会覆盖第一次的颜色）。因此 padding 是安全的。

### 2-2. `scripts/validate_images.py` — 内容感知的背景修复

完全重写 `fix_background_color`，从「全局颜色范围替换」改为「边缘连通区域泛洪填充」：

```python
def fix_background_color(images_dir: str, target_bgr=(227, 241, 246),
                          tolerance: int = 30):
    """内容感知的背景色修复。仅替换与图片边缘连通的近白色区域。

    原理：真正的背景区域与图片边缘连通（可以从边缘泛洪到达），
    而画面内的浅色内容被其他内容包围，不与边缘连通。
    """
    for filename in os.listdir(images_dir):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        img_path = os.path.join(images_dir, filename)
        img = cv2.imread(img_path)
        if img is None:
            continue

        bg_mask = _detect_background_mask(img, tolerance)
        if bg_mask is None or bg_mask.sum() == 0:
            continue

        # 形态学腐蚀：防止侵蚀到内容边缘
        kernel = np.ones((3, 3), np.uint8)
        bg_mask = cv2.erode(bg_mask, kernel, iterations=2)

        # 仅替换确认的背景像素
        changed = bg_mask.sum() > 0
        if changed:
            img[bg_mask > 0] = np.array(target_bgr, dtype=np.uint8)
            cv2.imwrite(img_path, img)

    return changed


def _detect_background_mask(img, tolerance=30):
    """通过边缘泛洪检测背景区域。

    1. 采样图片四角的颜色，取中位数作为疑似背景色
    2. 创建颜色接近度掩码（与背景色差异 < tolerance 的像素）
    3. 从四个角开始泛洪填充，只标记与边缘连通的近背景色像素
    """
    h, w = img.shape[:2]

    # 采样四角 5x5 区域的平均色
    corners = [
        img[0:5, 0:5],          # 左上
        img[0:5, w-5:w],        # 右上
        img[h-5:h, 0:5],        # 左下
        img[h-5:h, w-5:w],      # 右下
    ]
    corner_colors = [c.reshape(-1, 3).mean(axis=0) for c in corners]
    bg_color = np.median(corner_colors, axis=0).astype(np.uint8)

    # 检查四角是否一致（如果差异过大，可能不是纯色背景）
    diffs = [np.linalg.norm(c - bg_color) for c in corner_colors]
    if max(diffs) > tolerance * 2:
        return None  # 非纯色背景，不做修复

    # 颜色接近度掩码
    lower = np.clip(bg_color.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(bg_color.astype(int) + tolerance, 0, 255).astype(np.uint8)
    color_mask = cv2.inRange(img, lower, upper)

    # 从四角泛洪填充
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    seed_points = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for seed in seed_points:
        # 只在 color_mask 为 255 的区域泛洪
        if color_mask[seed[1], seed[0]] > 0:
            cv2.floodFill(
                color_mask, flood_mask, seed,
                newVal=128,  # 标记已访问
                loDiff=(tolerance,) * 3,
                upDiff=(tolerance,) * 3,
                flags=cv2.FLOODFILL_MASK_ONLY | (255 << 8),
            )

    # flood_mask 的有效区域（去掉 1px 边框）
    result = flood_mask[1:-1, 1:-1]
    return (result > 0).astype(np.uint8) * 255
```

### 2-3. `scripts/detect_regions.py` — 增强检测

在当前 Canny 边缘检测基础上，增加引擎同款自适应阈值路径和全内容 bbox 检测：

```python
def detect_full_content_bbox(image_path: str, bg_color_bgr=(227, 241, 246),
                              tolerance: int = 35, margin: int = 10) -> dict:
    """检测整图中所有非背景内容的最紧包围框。
    作为 bbox 预估失败时的 fallback。
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    # 用自适应阈值（与引擎一致）检测内容
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
    )

    # 反转（内容为白色）
    content_mask = 255 - thresh

    # 也加入颜色差异检测（补充阈值方法的盲区）
    bg = np.array(bg_color_bgr, dtype=np.float32)
    diff = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    color_mask = (diff > tolerance * 3).astype(np.uint8) * 255

    # 合并两种检测
    combined = cv2.bitwise_or(content_mask, color_mask)

    # 形态学操作：去噪 + 连接
    kernel = np.ones((5, 5), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

    # 查找包围框
    coords = cv2.findNonZero(combined)
    if coords is None:
        return {"x": 0, "y": 0, "w": w, "h": h}

    x, y, bw, bh = cv2.boundingRect(coords)

    # 加 margin
    x = max(0, x - margin)
    y = max(0, y - margin)
    bw = min(w - x, bw + 2 * margin)
    bh = min(h - y, bh + 2 * margin)

    return {"x": x, "y": y, "w": bw, "h": bh}
```

同时改进现有 `detect_regions` 函数：
- `margin` 默认值 15 → 25
- `merge_distance` 默认值 50 → 80
- 新增自适应阈值作为辅助检测路径（与 Canny 结果取并集）

### 2-4. `scripts/generate_animations.py` — 全画布场景优化

当场景无显式 elements 且自动生成了全画布单元素时，使用 `detect_full_content_bbox` 裁剪到实际内容区域：

```python
# 在 generate_animations() 中，约第 86-96 行后追加：
if not scene_regions:
    img = cv2.imread(img_path)
    if img is not None:
        h, w = img.shape[:2]
        # 自动检测实际内容区域，而非使用整个画布
        from detect_regions import detect_full_content_bbox
        content_bbox = detect_full_content_bbox(img_path)
        scene_regions = [{
            "id": "full",
            "bbox": content_bbox,
            "drawAt": 0,
            "durationMs": 3000,
            "narration": scene.get("voiceText", ""),
        }]
```

**效果**: 避免在大片空白背景上执行无意义的动画遍历（引擎仍会为背景区域的 inactive cell 消耗帧数，但不绘制任何内容）。更重要的是，`compute_element_viewport` 会根据实际内容 bbox 计算更合适的镜头视口。

---

## 验证方法

### 测试 bbox padding (2-1)

1. 准备一个多元素场景，故意把某个元素的 bbox 设得比实际内容小 10%
2. 修复前：该元素边缘被截断
3. 修复后：padding 补偿了 10% 偏差，完整绘制

### 测试背景修复 (2-2)

1. 准备一张包含浅蓝色元素（如水滴、天空背景块）的精致插画
2. 修复前：`fix_background_color` 把浅蓝色替换为背景色，元素消失
3. 修复后：泛洪填充只替换与边缘连通的背景区域，浅蓝色内容保留

### 测试全内容检测 (2-3)

1. 准备一张内容偏向右下角的单元素图片（左上角大片空白）
2. `detect_full_content_bbox` 应返回紧贴内容的 bbox（而非整个画布）
3. 镜头视口应聚焦在内容区域而非画面中心


# P3: 图片命名显式化 + 快速失败

**表现**: 用户在 Seedream 生图后不知道该存什么文件名，或保存了错误的文件名（大小写、后缀、空格），管线静默跳过该场景，最终视频缺少画面但无报错。

---

## 问题分析

### 当前行为

1. `generate_prompts.py` 输出的 `prompts.md` **不包含文件名指引**
2. `validate_images.py` 找不到图时打印 `[WARN]` 然后继续
3. `generate_animations.py` 找不到图时打印 `[SKIP]` 然后继续
4. 多个脚本各自拼接文件路径：
   - `validate_images.py:33` — `f"{scene_id}.png"` 或 `f"{scene_id}.jpg"`
   - `generate_animations.py:72` — 同上
   - `deploy_resources.py` — `f"animations/{scene_id}_final.mp4"`
5. 不支持大小写不敏感匹配，不支持 `.webp`/`.jpeg` 后缀

### 后果

用户在 Seedream 上生成 5 张图，保存为 `Scene1.png` / `场景二.png` / `scene3.jpg` 等，管线找不到任何一张 → 输出空视频 → 用户困惑。

---

## 修复方案

### 3-1. `scripts/validate_images.py` — 智能文件查找 + 严格校验

新增 `find_and_normalize_image` 函数和严格模式：

```python
def find_and_normalize_image(images_dir: str, scene_id: str) -> str | None:
    """查找场景图片，支持大小写不敏感、多后缀、自动重命名。

    查找优先级：
    1. 精确匹配: {scene_id}.png
    2. 大小写不敏感匹配: {Scene_ID}.png, {SCENE_ID}.PNG 等
    3. 替代后缀: .jpg, .jpeg, .webp
    4. 包含 scene_id 的文件（如 "scene1_seedream.png"）

    找到后自动转换为标准格式 {scene_id}.png 并返回路径。
    """
    from config import get_image_filename
    canonical = get_image_filename(scene_id)  # "scene1.png"
    canonical_path = os.path.join(images_dir, canonical)

    # 1. 精确匹配
    if os.path.exists(canonical_path):
        return canonical_path

    # 2-4. 搜索目录
    if not os.path.isdir(images_dir):
        return None

    candidates = []
    for f in os.listdir(images_dir):
        fname_lower = f.lower()
        sid_lower = scene_id.lower()

        # 大小写不敏感的精确匹配
        if fname_lower == canonical.lower():
            candidates.insert(0, f)  # 最高优先级
            continue

        # 替代后缀
        name_part = os.path.splitext(fname_lower)[0]
        if name_part == sid_lower and fname_lower.endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            candidates.append(f)
            continue

        # 包含 scene_id 的文件
        if sid_lower in fname_lower and fname_lower.endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            candidates.append(f)

    if not candidates:
        return None

    source_file = candidates[0]
    source_path = os.path.join(images_dir, source_file)

    # 自动转换并重命名
    if source_file != canonical:
        ext = os.path.splitext(source_file)[1].lower()
        if ext in (".webp", ".jpg", ".jpeg"):
            img = cv2.imread(source_path)
            if img is not None:
                cv2.imwrite(canonical_path, img)
                print(f"  [AUTO] 转换 {source_file} -> {canonical}")
                return canonical_path
        else:
            os.rename(source_path, canonical_path)
            print(f"  [AUTO] 重命名 {source_file} -> {canonical}")
            return canonical_path

    return canonical_path


def validate_images(storyboard: dict, images_dir: str,
                     strict: bool = True) -> list[str]:
    """校验所有场景图片。strict=True 时缺图直接报错。

    返回发现的问题列表。
    """
    scenes = storyboard.get("scenes", [])
    issues = []
    missing = []

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        img_path = find_and_normalize_image(images_dir, scene_id)

        if img_path is None:
            missing.append(scene_id)
            issues.append(f"[MISSING] {scene_id}: 未找到图片文件")
            continue

        # ... 其余检查（尺寸、背景色、直方图一致性）保持不变 ...

    if missing and strict:
        from config import get_image_filename
        expected = [get_image_filename(sid) for sid in missing]
        raise FileNotFoundError(
            f"\n{'='*60}\n"
            f"  缺少 {len(missing)} 个场景的图片！\n"
            f"  缺失场景: {missing}\n"
            f"  期望文件: {expected}\n"
            f"  图片目录: {images_dir}\n"
            f"\n"
            f"  请根据 prompts.md 中的指引生成图片，\n"
            f"  并保存为上述文件名放入图片目录。\n"
            f"{'='*60}"
        )

    return issues
```

### 3-2. `scripts/generate_animations.py` — 缺图即报错

替换静默跳过为明确报错：

```python
# 修复前 (line 73-77)
if not os.path.exists(img_path):
    img_path = os.path.join(images_dir, f"{scene_id}.jpg")
if not os.path.exists(img_path):
    print(f"  [SKIP] Scene '{scene_id}': no image found")
    continue

# 修复后
from validate_images import find_and_normalize_image
img_path = find_and_normalize_image(images_dir, scene_id)
if img_path is None:
    from config import get_image_filename
    raise FileNotFoundError(
        f"场景 '{scene_id}' 图片未找到。\n"
        f"期望文件名: {get_image_filename(scene_id)}\n"
        f"图片目录: {images_dir}"
    )
```

### 3-3. Prompt 输出中的文件名指引

在 P1 (02-llm-prompt-generation.md) 的 `_format_prompts_md` 中已设计了醒目的文件名显示。关键补充：在 `prompts.md` 最顶部增加汇总表：

```markdown
# 文件名清单

| 场景 | 文件名 | 保存到 |
|------|--------|--------|
| scene1 | scene1.png | output/{topic}/images/ |
| scene2 | scene2.png | output/{topic}/images/ |
| scene3 | scene3.png | output/{topic}/images/ |

**注意：文件名必须精确匹配（小写，.png 后缀）**
```

### 3-4. 统一图片路径解析

所有涉及图片路径构造的脚本，统一使用 `config.get_image_filename(scene_id)` 替代内联的 `f"{scene_id}.png"`。

受影响文件：
- `validate_images.py` — 已在 3-1 中处理
- `generate_animations.py` — 已在 3-2 中处理
- `detect_regions.py` — CLI 入口中的文件名处理
- `deploy_resources.py` — 资源拷贝时的文件名


# P4: Remotion 修复 + Schema 演进

---

## Remotion 修复

### 4-1. `remotion-project/src/WhiteboardVideo.tsx` — BGM 条件化

**问题**: 第 418 行 `<Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />` 无条件播放 BGM。在 `full` 模式下，BGM 应由 `audio_mixer.py` 混入语音轨道（以便控制相对音量），Remotion 侧不应再叠加一层 BGM。

**修复**:
```tsx
// 修复前
<Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />

// 修复后：仅在非 full 模式播放（full 模式由 audio_mixer 处理）
{storyboard.meta.pipeline.mode !== "full" && (
  <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />
)}
```

### 4-2. `remotion-project/src/WhiteboardVideo.tsx` — 场景匹配用 ID

**问题**: 第 422 行 `const scene = storyboard.scenes[i]` 用位置索引匹配场景，如果 timeline 和 storyboard 的场景顺序不一致（如某个场景被跳过），会匹配到错误的场景数据。

**修复**:
```tsx
// 修复前
{timeline.scenes.map((tScene, i) => {
  const scene = storyboard.scenes[i];
  // ...

// 修复后
{timeline.scenes.map((tScene) => {
  const scene = storyboard.scenes.find(
    (s: StoryboardScene) => s.id === tScene.id
  );
  if (!scene) return null;
  // ...
```

### 4-3. `remotion-project/src/WhiteboardVideo.tsx` — 字幕字号可配置

**问题**: `Subtitle` 组件中 `fontSize: 36` 硬编码，未读取 `storyboard.meta.subtitle.fontSize`。

**修复**: 将 `storyboard.meta.subtitle` 传入 `Subtitle` 组件并使用其 `fontSize`。

```tsx
// Subtitle 组件签名修改
const Subtitle: React.FC<{
  segments: SubtitleSegment[];
  fontSize?: number;
}> = ({ segments, fontSize = 36 }) => {
  // ...在 style 中使用 fontSize
};

// 调用处
<Subtitle
  segments={subSegs}
  fontSize={storyboard.meta.subtitle?.fontSize}
/>
```

---

## Schema 演进

### 4-4. `scripts/parse_storyboard.py` — 新增字段

在默认值填充中新增以下字段：

```python
def parse_storyboard(input_path, output_path, ...):
    # ... 现有代码 ...

    # 新增 meta 级字段
    meta.setdefault("style", "refined_illustration")  # 画风模版
    meta.setdefault("styleGuide", None)  # LLM 生成后回写

    # 每个场景：新增 imageName 字段
    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        scene.setdefault("imageName", get_image_filename(scene_id))
        # imagePrompt 不再是必填 — 可从 description 由 LLM 生成
        # 但至少需要 imagePrompt 或 voiceText 之一
```

新增 `meta.style` 可选值：
| 值 | 说明 | 对应 prompt 模版 |
|---|---|---|
| `"refined_illustration"` | 精致插画风（新默认值） | DeepSeek 精致插画风系统提示 |
| `"whiteboard"` | 白板简笔画（旧默认值） | 保持旧版 whiteboard 模版 |
| `"blackboard"` | 黑板粉笔风 | 保持旧版 blackboard 模版 |
| `"custom"` | 自定义 | 用户在 styleGuide 中指定 |

### 4-5. `remotion-project/src/types.ts` — 新增类型

```typescript
// 在现有类型基础上新增

export interface StyleGuide {
  colorPalette: string[];
  lineStyle: string;
  characterStyle?: string;
  iconStyle?: string;
  compositionRules?: string;
  moodAndTone?: string;
  consistencyNotes?: string;
}

// 修改 Storyboard.meta
export interface Storyboard {
  meta: {
    // ... 现有字段 ...
    style?: "whiteboard" | "blackboard" | "notebook" | "refined_illustration" | "custom";
    styleGuide?: StyleGuide | null;
  };
  scenes: StoryboardScene[];
}

// 修改 StoryboardScene
export interface StoryboardScene {
  id: string;
  imagePrompt?: string;     // 改为可选（LLM 可从 description 生成）
  description?: string;      // 新增：场景描述（LLM 输入）
  voiceText: string;
  duration: number | null;
  imageName?: string;        // 新增：显式图片文件名
  elements?: StoryboardElement[];
  textOverlay?: TextOverlayConfig;
}
```

### 4-6. `scripts/validate.py` — Schema 校验更新

```python
def validate_scene_schema(scene, index):
    errors = []
    prefix = f"scenes[{index}]"

    # imagePrompt 或 voiceText 至少有一个
    if not scene.get("imagePrompt") and not scene.get("voiceText"):
        errors.append(f"{prefix}: 至少需要 imagePrompt 或 voiceText")

    # 验证 imageName 格式（如果指定）
    if scene.get("imageName"):
        name = scene["imageName"]
        if not name.endswith(".png"):
            errors.append(f"{prefix}: imageName 必须以 .png 结尾, 当前: {name}")

    # ... 现有的 elements/bbox 校验 ...
    return errors
```

---

## Storyboard JSON 新版示例

```json
{
  "meta": {
    "title": "AI时代资产蓝图",
    "topic": "ai-asset",
    "style": "refined_illustration",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "drawMode": "sketch_first",
    "pipeline": { "mode": "video_first" },
    "camera": { "enabled": true, "maxZoom": 2.5, "transitionMs": 800 },
    "tts": { "provider": "tencent", "voice": 602005, "speed": 1.1 },
    "subtitle": { "enabled": true, "fontSize": 40 },
    "transition": { "type": "fade", "durationFrames": 15 }
  },
  "scenes": [
    {
      "id": "scene1",
      "imageName": "scene1.png",
      "imagePrompt": "画面左侧一个人坐在电脑前低头工作，头上冒汗珠；右上方一个巨大的闹钟；右下角散落几张纸币",
      "voiceText": "还在单纯靠出卖劳动时间，来换取那点微薄的工资吗？",
      "duration": null,
      "elements": [
        {
          "id": "person",
          "description": "坐在电脑前低头工作的人，头上冒汗珠",
          "bbox": {"x": 80, "y": 250, "w": 500, "h": 550},
          "drawAt": null,
          "narration": "还在单纯靠出卖劳动时间，"
        },
        {
          "id": "clock",
          "description": "巨大的闹钟，时针飞速旋转",
          "bbox": {"x": 700, "y": 50, "w": 400, "h": 400},
          "drawAt": null,
          "narration": "来换取那点微薄的工资吗？"
        }
      ]
    }
  ]
}
```

向后兼容：`style` 不填默认 `"refined_illustration"`，`imageName` 不填自动从 `id` 生成，`imagePrompt` 和 `description` 至少有一个即可。


# 实施顺序与验证方法

---

## 实施顺序

```
Phase 1: 基础设施 + Bug 修复 (P0)
│
│  1. 新建 scripts/config.py
│  2. 修复 make_video.py 重复条件 (line 185)
│  3. 修复 compute_timeline.py 帧号 bug (line 171, 173)
│  4. 修复 compute_timeline.py 阶段过渡时长 (line ~139)
│  5. 修复 deploy_resources.py (elements 传递 + timeline 路径)
│  6. 所有脚本改用 config.py 路径
│
├── Phase 2: Prompt 生成重构 (P1) ← 最高商业价值
│
│  7. 新建 scripts/llm_client.py
│  8. 重写 scripts/generate_prompts.py (两阶段 LLM)
│  9. 更新 scripts/validate.py (DEEPSEEK_API_KEY)
│
├── Phase 3: 修复部分绘制 (P2) ← 最影响动画质量
│
│  10. generate_scene_animation.py: filter_draw_order_for_bbox 加 padding
│  11. validate_images.py: fix_background_color 改为泛洪填充
│  12. detect_regions.py: 新增 detect_full_content_bbox + 增强检测
│  13. generate_animations.py: 全画布 fallback 优化
│
├── Phase 4: 命名 + 校验 (P3)
│
│  14. validate_images.py: find_and_normalize_image + strict 模式
│  15. generate_animations.py: 缺图报错
│  16. 统一 config.get_image_filename 调用
│
└── Phase 5: Remotion + Schema (P4)

   17. WhiteboardVideo.tsx: BGM 条件化 + ID 匹配 + 字幕字号
   18. parse_storyboard.py: 新字段 (style, styleGuide, imageName)
   19. types.ts: 新类型 (StyleGuide, 可选字段)
   20. validate.py: schema 校验更新
```

---

## 文件变更清单

### 新建文件 (2)

| 文件 | 说明 |
|------|------|
| `scripts/config.py` | 项目级配置：路径、常量、工具函数 |
| `scripts/llm_client.py` | DeepSeek API 封装 |

### 重写文件 (1)

| 文件 | 说明 |
|------|------|
| `scripts/generate_prompts.py` | 完全重写为两阶段 LLM 生成 |

### 修改文件 (10)

| 文件 | 改动范围 |
|------|----------|
| `scripts/make_video.py` | 修复 line 185; deploy 调用传 timeline_path |
| `scripts/compute_timeline.py` | 修复帧号 bug (2 处); 修复阶段过渡时长 |
| `scripts/deploy_resources.py` | elements 传递; timeline 路径; 路径改用 config |
| `scripts/generate_scene_animation.py` | filter_draw_order_for_bbox 加 padding; 路径改用 config |
| `scripts/validate_images.py` | 重写 fix_background_color; 新增 find_and_normalize_image; strict 模式 |
| `scripts/validate.py` | 路径改用 config; 新增 LLM key 检查; schema 更新 |
| `scripts/generate_animations.py` | 缺图报错; 全画布 fallback 优化 |
| `scripts/detect_regions.py` | 新增 detect_full_content_bbox; 增强参数 |
| `scripts/parse_storyboard.py` | 新增 style/styleGuide/imageName 字段 |
| `scripts/tts_pipeline.py` | 路径改用 config |

### Remotion 修改 (2)

| 文件 | 改动范围 |
|------|----------|
| `remotion-project/src/WhiteboardVideo.tsx` | BGM 条件化; ID 匹配; 字幕字号 |
| `remotion-project/src/types.ts` | 新增 StyleGuide; 字段改为可选 |

---

## 验证方法

### V1: 基础功能验证

```bash
# 确认引擎可用
python -c "from scripts.config import validate_engine; print(validate_engine())"

# 确认路径解析正确
python -c "from scripts.config import ENGINE_DIR; print(ENGINE_DIR, ENGINE_DIR.exists())"
```

### V2: Prompt 生成质量验证

```bash
# 设置 API key
export DEEPSEEK_API_KEY=your-key

# 生成 prompts
python scripts/make_video.py --storyboard storyboard.json --mode video-first

# 检查输出
cat output/*/prompts.md    # 检查文件名指引是否醒目
cat output/*/prompts.json  # 检查结构化数据是否完整
```

**人工评估**:
- [ ] 每个场景的 prompt 长度 ≥ 200 字（vs 旧版 ~50 字）
- [ ] prompt 包含具体的构图描述（元素位置、大小比例）
- [ ] prompt 包含风格关键词（精致插画风特征）
- [ ] 跨场景的风格一致性指南存在且合理
- [ ] 负面提示词覆盖了文字、写实、复杂背景等
- [ ] 每个场景有明确的 `imageName: sceneX.png`

### V3: 图片命名验证

```bash
mkdir -p output/test/images

# 测试大小写不敏感
touch output/test/images/Scene1.PNG
python -c "
from scripts.validate_images import find_and_normalize_image
result = find_and_normalize_image('output/test/images', 'scene1')
print(f'Found: {result}')
# 期望: 自动重命名为 scene1.png
"

# 测试缺图报错
python -c "
from scripts.validate_images import validate_images
storyboard = {'scenes': [{'id': 'scene1'}, {'id': 'scene_missing'}]}
try:
    validate_images(storyboard, 'output/test/images', strict=True)
except FileNotFoundError as e:
    print(f'正确报错: {e}')
"
```

### V4: 部分绘制修复验证

1. **bbox padding 测试**:
   - 准备测试图：元素实际范围比 bbox 大 5-15%
   - 修复前：边缘截断，未完整绘制
   - 修复后：10% padding 补偿，完整绘制

2. **背景修复测试**:
   - 准备测试图：包含浅蓝色元素 + 白色/米色背景
   - 修复前：`fix_background_color` 把浅蓝色也替换了
   - 修复后：只替换与边缘连通的背景区域

3. **全内容检测测试**:
   ```bash
   python -c "
   from scripts.detect_regions import detect_full_content_bbox
   bbox = detect_full_content_bbox('test_image.png')
   print(f'Content bbox: {bbox}')
   # 期望: bbox 紧贴实际绘制内容，不包含大面积空白
   "
   ```

### V5: 端到端验证

```bash
# 完整流程
python scripts/make_video.py -s storyboard.json --mode video-first
# → 输出 prompts.md + prompts.json，暂停

# 用户根据 prompts.md 在 Seedream 生成图片，保存到 output/*/images/

python scripts/make_video.py -s storyboard.json --mode video-first --skip-prompts
# → 校验图片 → 生成动画 → Remotion 渲染 → 输出 video_silent.mp4

# 检查清单：
# [ ] 所有场景的图片都被找到（无 SKIP/跳过）
# [ ] 动画完整绘制（无截断/缺失内容）
# [ ] 字幕同步正确（与 sketch 阶段对齐）
# [ ] 场景过渡自然（dip/breathe 无黑帧）
# [ ] BGM 正常播放（video_first 模式）
# [ ] 视频时长合理（无异常长/短场景）
```

### V6: 回归验证

- [ ] 不修改 `whiteboard-video-workflow` 仓库的任何文件
- [ ] 旧版 storyboard.json（不含新字段）仍能正常运行
- [ ] 无 `DEEPSEEK_API_KEY` 时 fallback 到静态模版并打印警告
- [ ] 单元素场景（无 elements）行为不变
- [ ] sequential draw mode 仍正常工作
