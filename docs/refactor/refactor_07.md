
## 修改总览

| # | 问题 | 文件 | 改动性质 |
|---|------|------|---------|
| 1 | 手图片模糊（145×200 从未更新） | `scripts/deploy_resources.py` | 简化部署逻辑 |
| 2 | 笔尖偏移 26px + 手太小 | `remotion-project/src/MaskRevealAnimation.tsx` | 修正 6 个数值 |
| 3 | 转场带手图片（应纯白擦除） | `remotion-project/src/HandWipeTransition.tsx` | 删除手图片 |
| 4 | 转场与绘画时间重叠 | `scripts/compute_timeline.py` | 新增 draw_delay |
| 5 | 元素内绘画乱跳（长度排序） | `scripts/extract_drawing_paths.py` | drawStrategy 6 种策略 |
| 6 | 无 drawStrategy LLM 自动判断 | `scripts/parse_storyboard.py` | 新增 enrich 函数 |
| 7 | Prompt 风格偏机械 | `scripts/generate_prompts.py` | 三处 prompt 替换 |
| 8 | 废弃文件/旧数据 | 多文件 | 删除 + checkpoint 清理 |

---

## 修改 1：手图片部署（deploy_resources.py）

### 问题

第 97 行 `if not hand_dst.exists()` 导致旧的 145×200 图片一直在用，所有后续的尺寸修改从未生效。cv2 缩放还引入质量损失。

### 改法

`scripts/deploy_resources.py` 第 95-108 行，替换整段为：

```python
    # ── 4. Writing hand ──
    hand_dst = remotion_public / "assets" / "writing-hand-small.png"
    hand_src = ENGINE_HAND_PATH
    if hand_src.exists():
        import shutil
        shutil.copy2(str(hand_src), str(hand_dst))
        print(f"  Writing hand: {hand_dst}")
    elif not hand_dst.exists():
        print(f"  [WARN] Hand image not found: {hand_src}")
```

**变化**：删除 `if not exists` 守卫、删除 cv2 缩放。每次 deploy 用原图（872×1200）覆盖。

---

## 修改 2：DrawingHand 渲染参数（MaskRevealAnimation.tsx）

### 问题

笔尖偏移值 `(60, 22)` 是基于错误的 17% 估算，实际像素扫描确认笔尖在原图 `(84, 40)` 即 `(9.6%, 3.3%)`。当前渲染尺寸 350×481 偏小。

### 笔尖位置推导

```
原图尺寸: 872 × 1200
笔尖像素位置: (84, 40)  — alpha 通道扫描，y=38 首个可见像素行，中心 x=84

渲染尺寸: 500 × 688（500/1920 = 26% 画面宽）
笔尖渲染坐标: (500 × 84/872, 688 × 40/1200) = (48, 23)
```

### 改法

`remotion-project/src/MaskRevealAnimation.tsx` 第 179-194 行，替换 DrawingHand 的 return 为：

```typescript
  return (
    <Img
      src={staticFile("assets/writing-hand-small.png")}
      style={{
        position: "absolute",
        left: point.x - 48,
        top: point.y - 23,
        width: 500,
        height: 688,
        transform: `rotate(${smoothedAngle * 0.3}deg)`,
        transformOrigin: "48px 23px",
        zIndex: 100,
        pointerEvents: "none",
      }}
    />
  );
```

**变化**：left `-60→-48`，top `-22→-23`，width `350→500`，height `481→688`，transformOrigin `"60px 22px"→"48px 23px"`。

---

## 修改 3：转场去掉手（HandWipeTransition.tsx）

### 改法

`remotion-project/src/HandWipeTransition.tsx` 全文替换为：

```typescript
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

interface HandWipeTransitionProps {
  startFrame: number;
  durationFrames: number;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const HandWipeTransition: React.FC<HandWipeTransitionProps> = ({
  startFrame,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const progress = Math.max(0, Math.min(1, (frame - startFrame) / durationFrames));
  if (progress <= 0) return null;

  const eased = progress < 0.5
    ? 2 * progress * progress
    : 1 - Math.pow(-2 * progress + 2, 2) / 2;

  return (
    <AbsoluteFill style={{ zIndex: 50, pointerEvents: "none" }}>
      <div style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: CANVAS_W * eased,
        height: CANVAS_H,
        backgroundColor: "#FFFFFF",
      }} />
    </AbsoluteFill>
  );
};

export default HandWipeTransition;
```

**变化**：删除 `Img`/`staticFile` 导入和手图片渲染，只保留白色遮罩左到右扩展。

---

## 修改 4：转场时序分离（compute_timeline.py）

### 问题

第 184 行 `current_frame -= TRANSITION_FRAMES` 让场景重叠 25 帧，新场景在转场未完成时就开始画了。

### 改法

**4a.** `compute_timeline_entry` 函数签名新增 `draw_delay` 参数，第 93 行起：

```python
def compute_timeline_entry(
    scene: dict,
    scene_start_frame: int,
    tts_segments: list[dict] | None = None,
    fps: int = 30,
    draw_delay: int = 0,
) -> dict:
```

**4b.** 第 130 行 `current_frame = 0` 改为：

```python
    current_frame = draw_delay
```

**4c.** `compute_timeline` 函数内调用处（第 174 行附近）改为：

```python
        delay = TRANSITION_FRAMES if i > 0 else 0
        entry = compute_timeline_entry(
            scene,
            current_frame,
            tts_segments=tts_segments,
            fps=fps,
            draw_delay=delay,
        )
```

---

## 修改 5：drawStrategy 绘画策略（extract_drawing_paths.py）

### 问题

第 300 行 `elem_paths.sort(key=lambda x: x[1]["length"], reverse=True)` 按长度降序导致手在元素内空间上乱跳。

### 改法

**5a.** 删除第 292-303 行（当前的第二步排序逻辑），替换为：

```python
    # 第二步：按 elements 顺序分组，每组用 drawStrategy 决定绘画顺序
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

**5b.** 在 `_assign_paths_to_elements` 之前新增三个函数：

```python
def _path_center_dist(rp: dict, x: float, y: float) -> float:
    cx = rp["bbox"]["x"] + rp["bbox"]["w"] / 2
    cy = rp["bbox"]["y"] + rp["bbox"]["h"] / 2
    return (cx - x) ** 2 + (cy - y) ** 2


def _greedy_spatial_walk(paths: list, elem_bbox: dict) -> list:
    """从元素左上角开始，每次画离当前位置最近的未画路径。"""
    if len(paths) <= 1:
        return list(paths)
    remaining = list(range(len(paths)))
    sx, sy = elem_bbox.get("x", 0), elem_bbox.get("y", 0)
    first = min(remaining, key=lambda j: _path_center_dist(paths[j][1], sx, sy))
    ordered = [first]
    remaining.remove(first)
    while remaining:
        last_rp = paths[ordered[-1]][1]
        lx = last_rp["bbox"]["x"] + last_rp["bbox"]["w"] / 2
        ly = last_rp["bbox"]["y"] + last_rp["bbox"]["h"] / 2
        nearest = min(remaining, key=lambda j: _path_center_dist(paths[j][1], lx, ly))
        ordered.append(nearest)
        remaining.remove(nearest)
    return [paths[j] for j in ordered]


def _sort_element_paths(elem_paths: list, strategy: str, elem_bbox: dict) -> list:
    """根据 drawStrategy 对元素内路径排序。

    策略说明:
      spatial_walk  — 空间邻近遍历（默认），手平滑移动
      top_down      — 从上到下，适合人物
      bottom_up     — 从下到上，适合金字塔/层级结构
      left_right    — 从左到右，适合时间线/流程图
      outline_first — 先长路径（轮廓）后短路径（细节），各组内空间邻近
      center_out    — 从元素中心向外
    """
    if strategy == "top_down":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"])

    if strategy == "bottom_up":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"], reverse=True)

    if strategy == "left_right":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["x"])

    if strategy == "outline_first":
        by_length = sorted(elem_paths, key=lambda x: x[1]["length"], reverse=True)
        split = max(1, len(by_length) // 5)
        return _greedy_spatial_walk(by_length[:split], elem_bbox) + \
               _greedy_spatial_walk(by_length[split:], elem_bbox)

    if strategy == "center_out":
        cx = elem_bbox.get("x", 0) + elem_bbox.get("w", 1920) / 2
        cy = elem_bbox.get("y", 0) + elem_bbox.get("h", 1080) / 2
        return sorted(elem_paths, key=lambda x: _path_center_dist(x[1], cx, cy))

    # default: spatial_walk
    return _greedy_spatial_walk(elem_paths, elem_bbox)
```

---

## 修改 6：LLM 自动判断 drawStrategy（parse_storyboard.py）

### 改法

在 `parse_storyboard.py` 文件末尾（`if __name__` 之前）新增：

```python
DRAW_STRATEGY_PROMPT = """给定一个画面元素的描述，判断最适合的绘画顺序策略。

可选策略：
- spatial_walk: 从左上开始，按空间邻近顺序画。适合没有明确结构的通用元素。
- top_down: 从上往下画。适合人物（先头后身体）、悬挂物。
- bottom_up: 从下往上画。适合金字塔、建筑、层级结构、堆叠图。
- left_right: 从左到右画。适合时间线、流程图、进度条。
- outline_first: 先画外轮廓再画内部细节。适合封闭图形（圆形图标、方框）。
- center_out: 从中心向外画。适合放射性图形、大脑、太阳。

元素描述: {description}

只返回策略名称，不要任何解释。"""

VALID_STRATEGIES = {"spatial_walk", "top_down", "bottom_up",
                    "left_right", "outline_first", "center_out"}


def enrich_draw_strategies(scenes: list[dict]):
    """为缺少 drawStrategy 的元素通过 LLM 自动生成绘画策略。"""
    try:
        from llm_client import call_deepseek
    except (ImportError, RuntimeError):
        print("  [SKIP] LLM unavailable, using default spatial_walk for all elements")
        return

    for scene in scenes:
        for elem in scene.get("elements", []):
            if elem.get("drawStrategy"):
                continue
            desc = elem.get("description", elem.get("id", ""))
            if not desc:
                continue
            try:
                resp = call_deepseek(
                    DRAW_STRATEGY_PROMPT.replace("{description}", desc),
                    temperature=0.1, max_tokens=20,
                )
                strategy = resp.strip().lower().replace('"', '').replace("'", "")
                elem["drawStrategy"] = strategy if strategy in VALID_STRATEGIES else "spatial_walk"
                print(f"    drawStrategy: {elem['id']} → {elem['drawStrategy']}")
            except Exception:
                elem["drawStrategy"] = "spatial_walk"
```

然后在 `parse_storyboard()` 函数中，第 82 行 `auto_generate_single_element(scene)` 之后加一行：

```python
    enrich_draw_strategies(storyboard["scenes"])
```

---

## 修改 7：Prompt 风格定型（generate_prompts.py）

### 问题

当前是"白板马克笔"风格（均匀线条、火柴人、最多 10 笔），生成图像像 PPT 线框。

### 改法

**7a.** 第 19-43 行 `IPAD_SKETCH_TEMPLATE` 全部替换为：

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

**7b.** 第 76-116 行 `STYLE_GUIDE_SYSTEM_PROMPT` 中画风定位段落（第 80-100 行）替换为：

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
- 图片中绝对不出现任何文字、字母、数字、标点

技术约束 — 路径提取兼容：
- 图片会经过骨架化提取绘画路径
- 线条必须与白色背景有强烈黑白对比
- 禁止：交叉阴影（cross-hatching）、密集填充、多笔重叠描边（这些会产生数百条碎片路径）
- 允许：自然的压感粗细变化、关键轮廓处轻微加重
```

**7c.** 第 118-155 行 `SCENE_PROMPT_SYSTEM_PROMPT` 中【画风定位】和【元素表达规则】段落做同样替换，内容与 7b 一致。

---

## 修改 8：清理废弃文件 + 刷新旧数据

### 8a. 删除废弃文件

```bash
rm -f remotion-project/src/SVGDrawAnimation.tsx
rm -f remotion-project/src/PaperPullTransition.tsx
rm -f remotion-project/src/svg-data.json
```

### 8b. 删除旧手图片（强制 deploy 重新生成）

```bash
rm -f remotion-project/public/assets/writing-hand-small.png
```

### 8c. 清除需要重新生成的 checkpoint

```bash
python3 -c "
import json
cp_path = 'output/ai-asset-20260710/.checkpoint.json'
with open(cp_path) as f:
    cp = json.load(f)
for step in ['drawing_paths', 'timeline', 'subtitles', 'remotion']:
    cp.pop(step, None)
with open(cp_path, 'w') as f:
    json.dump(cp, f, indent=2)
print('Cleared:', ['drawing_paths', 'timeline', 'subtitles', 'remotion'])
"
```

---

## 实施顺序与验证

```
Step 1  deploy_resources.py + 删除旧手图片
        → 运行 deploy → 检查 writing-hand-small.png 为 872×1200

Step 2  MaskRevealAnimation.tsx (DrawingHand 参数)
        → 渲染单帧 → 笔尖应精确对准路径点

Step 3  HandWipeTransition.tsx (删除手图片)
        → 渲染转场帧 → 纯白色左右擦除

Step 4  compute_timeline.py (draw_delay)
        → 重新计算 timeline → 检查 scene2 elements[0].drawAtFrame = 25

Step 5  extract_drawing_paths.py (drawStrategy 排序)
      + parse_storyboard.py (LLM enrich)
        → 重新 parse + 提取路径 → 检查路径不再乱跳

Step 6  generate_prompts.py (prompt 风格)
        → 重新生成 prompts.md → 检查 prompt 描述有压感/卡通人

Step 7  清除 checkpoint → 完整管线跑一遍 → 渲染视频 → 目视检查
```