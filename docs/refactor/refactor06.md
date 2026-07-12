# 最终实施方案：绘画策略 + 转场时序 + Prompt 画风

> 合并自 06-drawing-order-transition-prompt.md（问题 2、3）+ 07-draw-strategy.md（全部）

---

## 一、drawStrategy 绘画策略系统

### 1-1. 背景

当前元素内路径按长度降序排列，手在元素区域内跳跃式乱画。需要根据元素的语义特征选择合适的绘画顺序。

### 1-2. 字段定义

在 storyboard element 中新增 `drawStrategy` 字段：

```json
{
  "id": "pyramid",
  "description": "金字塔结构图，底层执行、中层管理、顶层决策",
  "bbox": {"x": 460, "y": 80, "w": 1000, "h": 920},
  "drawAt": null,
  "narration": "从执行到管理再到决策...",
  "drawStrategy": "bottom_up"
}
```

### 1-3. 六种策略

| 策略 | 含义 | 适用场景 | 排序逻辑 |
|------|------|---------|---------|
| `spatial_walk` | 空间邻近遍历（默认） | 通用，无明确结构的元素 | 从左上开始，每次画最近的未画路径 |
| `top_down` | 从上到下 | 人物（先头后身体）、悬挂物 | 按路径中心 Y 坐标升序 |
| `bottom_up` | 从下到上 | 金字塔、层级结构、建筑 | 按路径中心 Y 坐标降序 |
| `left_right` | 从左到右 | 时间线、流程图、进度条 | 按路径中心 X 坐标升序 |
| `outline_first` | 先轮廓后细节 | 封闭图形（圆形图标、方框） | 长路径优先，同级按空间邻近 |
| `center_out` | 从中心向外 | 放射性图形、大脑、太阳 | 按路径到元素中心的距离升序 |

### 1-4. 优先级

```
用户手写 drawStrategy  >  LLM 自动生成  >  默认 spatial_walk
```

### 1-5. 代码改动

#### A. `scripts/extract_drawing_paths.py` — 策略排序实现

新增函数，替换当前第 300 行的 `sort(key=length, reverse=True)`：

```python
def _sort_element_paths(elem_paths: list, strategy: str, elem_bbox: dict) -> list:
    """根据 drawStrategy 对元素内路径排序。"""

    if strategy == "top_down":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"])

    elif strategy == "bottom_up":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"], reverse=True)

    elif strategy == "left_right":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["x"])

    elif strategy == "outline_first":
        by_length = sorted(elem_paths, key=lambda x: x[1]["length"], reverse=True)
        split = max(1, len(by_length) // 5)
        outline = _greedy_spatial_walk(by_length[:split], elem_bbox)
        detail = _greedy_spatial_walk(by_length[split:], elem_bbox)
        return outline + detail

    elif strategy == "center_out":
        cx = elem_bbox["x"] + elem_bbox["w"] / 2
        cy = elem_bbox["y"] + elem_bbox["h"] / 2
        return sorted(elem_paths,
            key=lambda x: _path_center_dist(x[1], cx, cy))

    else:  # spatial_walk (default)
        return _greedy_spatial_walk(elem_paths, elem_bbox)


def _greedy_spatial_walk(paths: list, elem_bbox: dict) -> list:
    """空间邻近遍历：从元素左上角开始，每次画最近的未画路径。"""
    if len(paths) <= 1:
        return paths
    remaining = list(range(len(paths)))
    start_x, start_y = elem_bbox["x"], elem_bbox["y"]
    first = min(remaining,
        key=lambda j: _path_center_dist(paths[j][1], start_x, start_y))
    ordered = [first]
    remaining.remove(first)
    while remaining:
        last = paths[ordered[-1]][1]
        lx = last["bbox"]["x"] + last["bbox"]["w"] / 2
        ly = last["bbox"]["y"] + last["bbox"]["h"] / 2
        nearest = min(remaining,
            key=lambda j: _path_center_dist(paths[j][1], lx, ly))
        ordered.append(nearest)
        remaining.remove(nearest)
    return [paths[j] for j in ordered]


def _path_center_dist(rp, x, y):
    cx = rp["bbox"]["x"] + rp["bbox"]["w"] / 2
    cy = rp["bbox"]["y"] + rp["bbox"]["h"] / 2
    return (cx - x) ** 2 + (cy - y) ** 2
```

`_assign_paths_to_elements` 第二步改为：

```python
# 第二步：按 elements 顺序分组，每组用对应的 drawStrategy 排序
result = []
for elem in elements:
    eid = elem["id"]
    elem_paths = [(i, rp) for i, rp in enumerate(raw_paths)
                  if path_elem_map[i] == eid]
    if not elem_paths:
        continue

    strategy = elem.get("drawStrategy", "spatial_walk")
    eb = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
    sorted_paths = _sort_element_paths(elem_paths, strategy, eb)

    for i, rp in sorted_paths:
        result.append({"d": rp["d"], "elementId": eid})

return result
```

注意：`_assign_paths_to_elements` 需要接收完整的 `elements` 列表（含 drawStrategy 和 bbox），当前签名已满足。

#### B. `scripts/parse_storyboard.py` — LLM 自动生成 drawStrategy

在 `parse_storyboard` 函数的元素处理阶段新增：

```python
DRAW_STRATEGY_PROMPT = """你是白板手绘视频的动画导演。

给定一个画面元素的描述，请判断最适合的绘画顺序策略。

可选策略：
- spatial_walk: 从左上开始，按空间邻近顺序画。适合没有明确结构的通用元素。
- top_down: 从上往下画。适合人物（先头后身体）、悬挂物、下拉菜单。
- bottom_up: 从下往上画。适合金字塔、建筑、层级结构、堆叠图。
- left_right: 从左到右画。适合时间线、流程图、进度条、对比图。
- outline_first: 先画外轮廓再画内部细节。适合封闭图形（圆形图标、方框图表）。
- center_out: 从中心向外画。适合放射性图形、大脑、太阳、爆炸效果。

元素描述: {description}

只返回策略名称，不要解释。"""


def enrich_draw_strategies(scenes: list[dict]):
    """为缺少 drawStrategy 的元素自动生成。"""
    try:
        from llm_client import call_deepseek
    except (ImportError, RuntimeError):
        return  # 无 LLM 时跳过，extract_drawing_paths 会用默认 spatial_walk

    valid = {"spatial_walk", "top_down", "bottom_up",
             "left_right", "outline_first", "center_out"}

    for scene in scenes:
        for elem in scene.get("elements", []):
            if elem.get("drawStrategy"):
                continue  # 用户已指定，跳过

            desc = elem.get("description", elem.get("id", ""))
            if not desc:
                continue

            try:
                response = call_deepseek(
                    DRAW_STRATEGY_PROMPT.replace("{description}", desc),
                    temperature=0.1, max_tokens=20,
                )
                strategy = response.strip().lower().replace('"', '').replace("'", "")
                elem["drawStrategy"] = strategy if strategy in valid else "spatial_walk"
                print(f"    drawStrategy: {elem['id']} → {elem['drawStrategy']}")
            except Exception:
                elem["drawStrategy"] = "spatial_walk"
```

在 `parse_storyboard()` 主流程中，场景处理完毕后调用：

```python
# 现有的场景处理逻辑之后
enrich_draw_strategies(storyboard["scenes"])
```


#### C. `scripts/validate.py` — drawStrategy 校验（可选）

在元素校验中增加：

```python
VALID_DRAW_STRATEGIES = {
    "spatial_walk", "top_down", "bottom_up",
    "left_right", "outline_first", "center_out"
}

# 在元素校验循环中
ds = elem.get("drawStrategy")
if ds and ds not in VALID_DRAW_STRATEGIES:
    issues.append(f"  [WARN] {scene_id}.{elem_id}: unknown drawStrategy '{ds}'")
```

---

## 二、转场和绘画时序分离

### 2-1. 问题

`compute_timeline.py` 中场景间有 25 帧重叠（`current_frame -= TRANSITION_FRAMES`），导致手擦除转场还没播完，新场景就开始画了。

### 2-2. 改动

**文件**: `scripts/compute_timeline.py`

`compute_timeline_entry` 新增 `draw_delay` 参数：

```python
def compute_timeline_entry(
    scene: dict,
    scene_start_frame: int,
    tts_segments: list[dict] | None = None,
    fps: int = 30,
    draw_delay: int = 0,       # 新增
) -> dict:
    ...
    timeline_elements = []
    current_frame = draw_delay  # ← 改这里，原来是 0
    for i, elem in enumerate(elements):
        timeline_elements.append({
            "id": elem["id"],
            "drawAtFrame": current_frame,
            "drawDurationFrames": elem_draw_frames[i],
            "narration": elem.get("narration", ""),
        })
        current_frame += elem_draw_frames[i]
        if i < n - 1:
            current_frame += ELEMENT_GAP_FRAMES
    ...
```

调用处（`compute_timeline` 函数内循环）：

```python
for i, scene in enumerate(scenes):
    delay = TRANSITION_FRAMES if i > 0 else 0
    entry = compute_timeline_entry(
        scene, current_frame,
        tts_segments=tts_segments, fps=fps,
        draw_delay=delay,
    )
```

**效果**：

```
修复前:
  场景1 转场帧 281-306 ──擦除中──
  场景2 帧 281 ──────────── 立即开始画 ← 混乱

修复后:
  场景1 转场帧 281-306 ──擦除中──
  场景2 帧 281 ── 等 25 帧 ── 帧 306 开始画 ← 干净白板上起笔
```

---

## 三、Prompt 画风恢复 iPad 专业手绘

### 3-1. 问题

上一轮将 prompt 从"iPad 手绘"改成"白板马克笔"，导致生成的图片线条粗细均匀无变化，像 PPT 线框图。

### 3-2. 改动

**文件**: `scripts/generate_prompts.py`

#### A. 静态模板

```python
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
```

#### B. STYLE_GUIDE_SYSTEM_PROMPT

画风定位段落替换为：

```
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
- 图片中绝对不出现任何文字
```

#### C. SCENE_PROMPT_SYSTEM_PROMPT

【画风定位】段落做同样替换。

**删除的过度约束**：
- ❌ "线条粗细均匀一致（约 3px）"
- ❌ "每个元素只画外轮廓线，不画任何内部填充"
- ❌ "每条线只画一笔"
- ❌ "每个元素最多 10 笔"
- ❌ "人 = 火柴人（圆头 + 直线身体四肢）"

---

## 四、改动清单汇总

| 文件 | 改动内容 | 行数 |
|------|---------|------|
| `scripts/extract_drawing_paths.py` | 新增 `_sort_element_paths` + 6 种策略 + `_greedy_spatial_walk` + `_path_center_dist`；`_assign_paths_to_elements` 调用策略排序 | ~80 行 |
| `scripts/parse_storyboard.py` | 新增 `enrich_draw_strategies` + `DRAW_STRATEGY_PROMPT`；主流程中调用 | ~30 行 |
| `scripts/compute_timeline.py` | `compute_timeline_entry` 新增 `draw_delay` 参数；非首场景传入 `TRANSITION_FRAMES` | ~5 行 |
| `scripts/generate_prompts.py` | `IPAD_SKETCH_TEMPLATE` 重写；`STYLE_GUIDE_SYSTEM_PROMPT` 画风段落替换；`SCENE_PROMPT_SYSTEM_PROMPT` 画风段落替换 | ~40 行 |
| `scripts/validate.py` | drawStrategy 枚举校验（可选） | ~5 行 |

**不需要改动**：Remotion 侧所有文件（`MaskRevealAnimation.tsx`、`WhiteboardVideo.tsx`、`HandWipeTransition.tsx`）。
