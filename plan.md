
## 一句话定位

用户提供故事板脚本 → 管线输出图片生成 Prompt（用户用任意工具生成插画）→ 自动检测元素区域 → 插画按叙事顺序"先描后涂"逐元素画出，虚拟镜头智能跟随聚焦 → 可选 TTS 配音 + 三层混音 → Remotion 合成字幕/音效/文字动画 → 输出成片。全程 CLI，纯算法驱动，不依赖图生视频 AI 服务。

---

## 设计原则

1. **不修改 `generate_whiteboard.py` 一行代码。** 所有能力通过 Python import 该模块的函数、在上层包装实现。
2. **人机协作而非全自动。** 图片生成、区域标注是可审阅的检查点，其余步骤全自动。
3. **纯算法引擎，零边际成本。** 手绘动画、镜头运动、音效均本地生成，不依赖图生视频 API。
4. **视觉真实感优先于功能堆砌。** 每项设计都要通过"观众是否会觉得这是真人在画"的检验。
5. **数据驱动，单一事实源。** `storyboard.json` 驱动全部下游产物；`timeline.json` 是派生文件。

---

## 核心架构

```
用户输入: 故事板脚本 (自然语言文本)
    │
    ▼
Step 1  解析脚本 → storyboard.json
        （场景 + 元素 + 画面描述 + 配音文案；无 elements 的场景自动生成全画布单元素）
    │
    ▼
Step 2  生成 Prompt → prompts.md（含空间分离引导 + 跨场景风格一致性指引）
    │   ⏸ 用户用任意文生图工具生成插画，放入 images/ 目录
    ▼
Step 3  校验图片（齐全性 + 尺寸 + 背景色 + 风格一致性）
    │
    ▼
Step 4  检测元素区域 → regions_preview.png + regions_detected.json
    │   ⏸ 用户审阅预览图，在 storyboard.json 中确认/调整 elements[].bbox
    │
    ├── [mode=full] Step 5  TTS 语音合成 → 整段 WAV + 静音检测切割 → per-element 时长
    │
    ▼
Step 6  时间轴编排 → drawAt 自动分配 + per-element durationMs
    │
    ▼
Step 7  生成合成音效（首次自动生成 pen_sketch.mp3 + marker_color.mp3）
    │
    ▼
Step 8  【核心】镜头驱动手绘动画引擎
    │   generate_scene_animation.py：
    │   ├─ 先描后涂双程绘制（Pass 1 全部线稿 → Pass 2 全部上色）
    │   ├─ 虚拟镜头：呼吸式缩放 / 背景淡出 自适应过渡
    │   ├─ 自适应笔刷半径（按缩放反向补偿）+ 上色加速
    │   ├─ 绘制路径连续性检查 + 条件性重排
    │   ├─ 画手一次加载 + 多尺寸缓存
    │   └─ Hold 阶段 Ken Burns 微运镜
    │   → 每场景一个 1920×1080 H.264 MP4
    │
    ▼
Step 9  计算最终时间轴（ffprobe 校正）+ 生成字幕 SRT
    │
    ├── [mode=full] Step 10  三层混音（语音 + 环境音 + 音效）
    │
    ▼
Step 11  Remotion 合成
    │   <Video> 手绘动画 + per-element 字幕 + DrawingSFX（分 sketch/colorize）
    │   + HandwrittenText 手写文字 + 场景过渡 + 进度条
    │   [mode=full]        → video.mp4（含语音+BGM+字幕+音效）
    │   [mode=video_first] → video_silent.mp4 + subtitles.srt（仍含绘画音效）
    ▼
Step 12  生成发布文案 → publish.md
    │
    ▼
输出: output/{topic}-{date}/
```

每步完成写 `.checkpoint.json`，支持断点续跑。

---

## 视觉真实感设计

白板手绘视频的核心可信度来自四个观感维度：**运镜自然、绘制状态一致、笔触尺度合理、路径不跳跃**。以下是针对这四点的具体设计。

### 1. 虚拟镜头系统

10px 网格逐格显示本身有机械感。镜头 2x 缩放聚焦某元素时，10px 网格在屏幕上放大为 20px，像素揭示视觉上更接近笔触描绘；同时镜头聚焦隐藏了全局遍历的机械感——这是整套方案里性价比最高的一项改动。

**CameraVideoWriter 包装器**：`draw_masked_object` 和 `colorize_animation` 都通过 `variables["video_object"].write(frame)` 写帧。用包装器替换 `video_object`，对每帧裁剪指定视口区域后缩放输出，引擎函数完全无感知：

```python
class CameraVideoWriter:
    """包装 cv2.VideoWriter，对每帧应用视口裁剪+缩放。"""
    def __init__(self, real_writer, canvas_w, canvas_h, output_w=1920, output_h=1080):
        self.writer = real_writer
        self.canvas_w, self.canvas_h = canvas_w, canvas_h
        self.output_w, self.output_h = output_w, output_h
        self.viewport = None  # None = 全画布

    def set_viewport(self, vp):
        self.viewport = vp  # {"x", "y", "w", "h"}

    def write(self, frame):
        if self.viewport:
            vp = self.viewport
            cropped = frame[vp["y"]:vp["y"] + vp["h"], vp["x"]:vp["x"] + vp["w"]]
            frame = cv2.resize(cropped, (self.output_w, self.output_h),
                               interpolation=cv2.INTER_LANCZOS4)
        elif frame.shape[1] != self.output_w or frame.shape[0] != self.output_h:
            frame = cv2.resize(frame, (self.output_w, self.output_h),
                               interpolation=cv2.INTER_LANCZOS4)
        self.writer.write(frame)

    def release(self):
        self.writer.release()
```

**统一分辨率策略：** 所有场景统一 `max_dim=1920`（不采用引擎默认的 `MAX_1080P` 限制），画布 ~1920×1080，网格 192×108 = 20,736 cells。2x 缩放显示 960×540 放大到 1920×1080，LANCZOS4 插值质量可接受；单场景渲染时间 ~25s，离线管线可接受。输出固定 1920×1080，无需 ffmpeg pad 后处理。

**自适应视口 padding：** 大元素（占画布 30%+）加更多 padding 以和全画布区分；小元素（占画布 <5%）减少 padding 突出主体：

```python
def compute_adaptive_padding(bbox_area, canvas_area):
    area_ratio = bbox_area / canvas_area
    # ~0.01 → padding ~0.20；~0.10 → ~0.35；~0.30 → ~0.50
    return 0.20 + 0.30 * min(1.0, area_ratio / 0.30)

def compute_element_viewport(scaled_bbox, canvas_w, canvas_h, max_zoom=2.5):
    """以 bbox 为中心，自适应 padding，强制 16:9，限制缩放范围。"""
    cx = scaled_bbox["x"] + scaled_bbox["w"] / 2
    cy = scaled_bbox["y"] + scaled_bbox["h"] / 2
    bbox_area = scaled_bbox["w"] * scaled_bbox["h"]
    padding = compute_adaptive_padding(bbox_area, canvas_w * canvas_h)

    vw = scaled_bbox["w"] * (1 + 2 * padding)
    vh = scaled_bbox["h"] * (1 + 2 * padding)
    if vw / vh > 16 / 9:
        vh = vw / (16 / 9)
    else:
        vw = vh * (16 / 9)

    vw = max(canvas_w / max_zoom, min(vw, canvas_w))
    vh = max(canvas_h / max_zoom, min(vh, canvas_h))

    vx = int(max(0, min(cx - vw / 2, canvas_w - vw)))
    vy = int(max(0, min(cy - vh / 2, canvas_h - vh)))
    return {"x": vx, "y": vy, "w": int(vw), "h": int(vh)}

def ease_in_out(t):
    return t * t * (3 - 2 * t)  # smoothstep

def interpolate_viewport(vp1, vp2, t):
    t = ease_in_out(max(0.0, min(1.0, t)))
    return {k: int(vp1[k] + (vp2[k] - vp1[k]) * t) for k in ("x", "y", "w", "h")}
```

**画手尺寸反向缩放：** 镜头缩放会放大画手（2x 缩放下 493px 手变 ~1000px），按 viewport/canvas 比例反向补偿，保证画手在最终输出中始终 ~250px 高：

```python
zoom_ratio = viewport["w"] / canvas_w  # 1.0=全画布, 0.4=2.5x缩放
hand_target_ht = max(100, int(HAND_TARGET_HT * zoom_ratio))
```

> **实现注意：** 引擎的 `preprocess_hand_image(hand_path, variables)` 不接受自定义目标高度参数（固定使用 `HAND_TARGET_HT=493`）。因此不能直接传参缩放，需用「一次性加载 + 多尺寸缓存」方案（见下方"性能优化"章节）替代。

**统一代码路径：** 无 `elements` 的场景自动生成全画布单元素，viewport 计算结果即全画布（无缩放效果），行为与不使用镜头系统时一致，但代码路径和输出分辨率统一：

```python
if not scene.get("elements"):
    scene["elements"] = [{
        "id": "full",
        "bbox": {"x": 0, "y": 0, "w": img_w, "h": img_h},
        "drawAt": 0,
        "narration": scene.get("voiceText", "")
    }]
```


### 2. 智能镜头过渡：消除"暴露空白画布"

**问题场景：** 镜头从元素 A 直线平移到元素 B 时，途中必然扫过尚未绘制的空白画布区域，直接告诉观众"这里还什么都没有"，打破手绘错觉。元素间距越大（prompt 的"空间分离引导"正是鼓励此），暴露越明显。

**解决方案：** 两种过渡策略按场景自适应选择，核心思想是**永远不让镜头运动过程暴露未绘制区域**。

| 策略 | 触发条件 | 效果 |
|------|---------|------|
| **背景淡出（dip）** | Pass 1（线稿）的元素间过渡；或视口距离超过画布对角线 40% | 当前内容淡出到纯背景色 → 视口跳转 → 在干净背景上开始绘制，无需淡入 |
| **呼吸式缩放（breathe）** | Pass 2（上色）的元素间过渡，且视口距离较近 | 缩出到包含两个元素的中间视口（展示已画内容作为上下文）→ 缩入新元素 |

```python
def choose_transition_strategy(current_vp, target_vp, canvas_w, canvas_h, phase):
    """sketch 阶段始终用 dip：后续元素未绘制，任何缩出都会暴露空白。
    colorize 阶段按距离选择：近则 breathe 展示上下文，远则 dip。"""
    if phase == "sketch":
        return "dip"

    cx1, cy1 = current_vp["x"] + current_vp["w"] / 2, current_vp["y"] + current_vp["h"] / 2
    cx2, cy2 = target_vp["x"] + target_vp["w"] / 2, target_vp["y"] + target_vp["h"] / 2
    distance = ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) ** 0.5
    canvas_diag = (canvas_w ** 2 + canvas_h ** 2) ** 0.5
    return "dip" if distance / canvas_diag > 0.4 else "breathe"


BACKGROUND_BGR = (227, 241, 246)  # #F6F1E3 in BGR

def write_dip_transition(camera_writer, drawn_frame, current_vp, target_vp, dip_frames):
    """当前内容淡出到背景色 → 跳转视口 → 在干净背景上停留，随后直接开始绘制。"""
    frame = drawn_frame if drawn_frame.dtype == np.uint8 else drawn_frame.astype(np.uint8)
    bg = np.full_like(frame, BACKGROUND_BGR, dtype=np.uint8)

    fade_out_frames = dip_frames * 2 // 3
    for f in range(fade_out_frames):
        t = ((f + 1) / fade_out_frames) ** 2  # ease-in：慢开始快结束
        blended = cv2.addWeighted(frame, 1 - t, bg, t, 0)
        camera_writer.set_viewport(current_vp)
        camera_writer.write(blended)

    camera_writer.set_viewport(target_vp)
    for _ in range(dip_frames - fade_out_frames):
        camera_writer.write(bg)
    # dip 结束即为干净背景，第一个 cell 直接出现——视觉上就是"落笔"


def compute_breathe_viewport(current_vp, target_vp, canvas_w, canvas_h):
    """计算包含两个视口的中间"呼吸"视口。"""
    x_min = min(current_vp["x"], target_vp["x"])
    y_min = min(current_vp["y"], target_vp["y"])
    x_max = max(current_vp["x"] + current_vp["w"], target_vp["x"] + target_vp["w"])
    y_max = max(current_vp["y"] + current_vp["h"], target_vp["y"] + target_vp["h"])

    pad = 0.15
    w = (x_max - x_min) * (1 + 2 * pad)
    h = (y_max - y_min) * (1 + 2 * pad)
    if w / h > 16 / 9:
        h = w / (16 / 9)
    else:
        w = h * (16 / 9)
    w, h = min(w, canvas_w), min(h, canvas_h)

    cx, cy = (x_min + x_max) / 2, (y_min + y_max) / 2
    x = int(max(0, min(cx - w / 2, canvas_w - w)))
    y = int(max(0, min(cy - h / 2, canvas_h - h)))
    return {"x": x, "y": y, "w": int(w), "h": int(h)}


def write_breathe_transition(camera_writer, drawn_frame, current_vp, target_vp,
                              canvas_w, canvas_h, breathe_frames):
    """缩出到中间视口（展示上下文）→ 缩入到目标视口。"""
    frame = drawn_frame if drawn_frame.dtype == np.uint8 else drawn_frame.astype(np.uint8)
    breathe_vp = compute_breathe_viewport(current_vp, target_vp, canvas_w, canvas_h)
    half = breathe_frames // 2

    for f in range(half):  # 缩出：ease-out 快启动
        t = (f + 1) / half
        camera_writer.set_viewport(interpolate_viewport(current_vp, breathe_vp, t))
        camera_writer.write(frame)
    for f in range(breathe_frames - half):  # 缩入：ease-in 慢启动
        t = (f + 1) / (breathe_frames - half)
        camera_writer.set_viewport(interpolate_viewport(breathe_vp, target_vp, t))
        camera_writer.write(frame)
```

**为什么 sketch 用 dip、colorize 用 breathe：** Sketch 阶段后续元素尚未绘制，画布是空白的，任何缩出都会暴露；dip 完全绕开这个问题。Colorize 阶段所有元素都已有线稿，缩出时观众看到的是"全幅线稿画面"，已上色元素与未上色线稿的对比本身就是自然的绘制过程展示。

### 3. 先描后涂绘制模式：消除视觉状态不一致

**问题场景：** 若逐元素完整完成（元素 A 线稿+上色全部做完才开始元素 B），当镜头视野同时覆盖两个元素时（元素间距不够大或缩放不够），观众会同时看到"全彩色"和"黑白线稿/空白"，非常不自然。

**解决方案：** 全部元素分两个 pass 处理：

```
Pass 1（sketch）：元素1线稿 → dip → 元素2线稿 → dip → 元素3线稿
                       │ 阶段过渡（长 dip，标记"从画到涂"的转折）
Pass 2（colorize）：元素1上色 → breathe → 元素2上色 → breathe → 元素3上色
                       │ 结束过渡：alpha blend + zoom-out
                  Hold：完整原图 + Ken Burns 微运镜
```

任意时刻的视觉状态都是自洽的：Pass 1 期间所有已处理元素是线稿、未处理元素被 dip 完全遮蔽；Pass 1 结束时全部元素统一为线稿状态；Pass 2 期间已上色元素与线稿元素并存——这正是真实画师"先勾线再上色"的自然过程。

**关键实现细节（基于引擎源码约束）：**

- `draw_masked_object` 直接在 `variables["drawn_frame"]`（uint8）上写入墨迹像素，不改变 dtype
- `colorize_animation` 在第一次调用时将 `variables["drawn_frame"]` 转换为 float32（用于 alpha 混合），此后一直是 float32
- 因此 sketch-first 模式下，Pass 2 中**每个元素 colorize 完成后必须显式转回 uint8**，否则下一次镜头过渡写帧（要求 uint8）会出错：

```python
colorize_animation(variables, color_target, skip_rate=colorize_skip, brush_radius=adjusted_radius)
if variables["drawn_frame"].dtype != np.uint8:
    variables["drawn_frame"] = variables["drawn_frame"].astype(np.uint8)
```

**单元素场景**自动使用 sequential 行为（sketch→colorize 紧邻，无跨元素过渡），因为没有"跨元素状态不一致"的问题。

**用户可选** `meta.drawMode`：

| 值 | 行为 | 适用 |
|----|------|------|
| `"sketch_first"`（默认） | 双程绘制 | 多元素知识讲解视频 |
| `"sequential"` | 逐元素完成后再下一个 | 单元素场景 / 追求最短时长 |

### 4. 自适应笔刷 + 上色加速：消除"盖章感"

**问题场景：** `colorize_animation` 使用 `COLOR_BRUSH_RADIUS=50` 的圆形高斯羽化笔刷。原始 1x 视角下 50px 笔刷在 1920×1080 画面上不显眼；但 2x 镜头缩放后，这个笔刷在屏幕上显示为 ~100px 直径的色块，逐个"盖章"般出现，破坏"涂色"的流畅感。

**解决方案 A — 笔刷半径按缩放反向补偿：**

`colorize_animation(variables, target_cells, skip_rate, brush_radius)` 本身接受 `brush_radius` 参数，无需修改引擎：

```python
def compute_adjusted_brush_radius(viewport_w, canvas_w, base_radius=COLOR_BRUSH_RADIUS):
    """按缩放比反向补偿笔刷半径，使屏幕上的视觉尺寸恒定在 ~50px。
    2x 缩放（viewport_w = canvas_w/2）→ radius = 25 → 屏幕显示仍 ~50px。"""
    zoom_ratio = viewport_w / canvas_w
    return max(15, int(base_radius * zoom_ratio))  # 下限 15px 防止留白
```

**解决方案 B — 上色阶段加速：**

同样帧数内处理更多 cells，多个笔刷同时活跃，视觉上呈现"色彩洗刷"而非逐个显现：

```python
COLOR_SKIP_MULTIPLIER = 1.5  # 4 → 6，每帧上色 cell 数提升 50%
colorize_skip = int(SKIP_RATE * COLOR_SKIP_MULTIPLIER)
```

两者叠加：笔刷更小（视觉尺度合理）+ 出现更快（洗刷感），共同消除盖章感。


### 5. 绘制路径连续性修复：消除跳跃

**问题场景：** 全局 `build_draw_order` 按 `layout_blocks` 组织，每类 block 有精心设计的遍历策略（`organic_walk` / `text_segments` / `structured_bands`）。按 bbox 过滤到单元素后，若该元素的 cells 原本跨越了多个 layout_block 的边界交错区域（元素间距不够大导致 block 划分交错），过滤后的顺序会在空间上跳跃。2x 镜头缩放会放大这种跳跃感——笔触从一处瞬间跳到另一处。

**解决方案：保守的连续性检查，仅在必要时修复。** 绝大多数情况下元素间有足够间距，cells 天然落在独立 block 内，过滤结果本身连续，不应破坏引擎精心设计的遍历策略：

```python
def check_path_coherence(cells):
    """计算路径平均步长。organic_walk/text_segments 的正常值 ~1.5-2.0。"""
    if len(cells) <= 1:
        return 0.0
    total = sum(
        ((cells[i][0] - cells[i-1][0]) ** 2 + (cells[i][1] - cells[i-1][1]) ** 2) ** 0.5
        for i in range(1, len(cells))
    )
    return total / (len(cells) - 1)


def reorder_nearest_neighbor(cells):
    """最近邻贪心重排（KDTree 加速，O(n log n)），仅在检测到跳跃时调用。"""
    if len(cells) <= 2:
        return cells
    from scipy.spatial import KDTree
    coords = np.array(cells)
    tree = KDTree(coords)
    start_idx = np.argmin(coords[:, 0] * 1000 + coords[:, 1])  # 最靠左上角的 cell

    visited = np.zeros(len(cells), dtype=bool)
    result = [start_idx]
    visited[start_idx] = True
    for _ in range(len(cells) - 1):
        _, indices = tree.query(coords[result[-1]], k=min(20, len(cells)))
        next_idx = next((i for i in indices if not visited[i]), None)
        if next_idx is None:
            next_idx = next(i for i in range(len(cells)) if not visited[i])
        result.append(next_idx)
        visited[next_idx] = True
    return [cells[i] for i in result]


def ensure_path_coherence(cells, threshold=3.0):
    """仅当 avg_step 超过阈值时才重排，否则保留引擎原始遍历策略。"""
    if len(cells) <= 2:
        return cells
    avg_step = check_path_coherence(cells)
    if avg_step <= threshold:
        return cells
    print(f"    路径连续性修复: avg_step={avg_step:.1f} > {threshold}，"
          f"对 {len(cells)} cells 执行最近邻重排")
    return reorder_nearest_neighbor(cells)
```

若运行环境缺少 `scipy`，重排功能自动跳过（打印警告，使用原始顺序），不影响主流程。

### 6. Hold 阶段 Ken Burns 微运镜

结束过渡（alpha blend + zoom-out）完成后展示完整原图。静止的 hold 帧略显死板，添加极轻微的缩放动效（97% → 100%，肉眼几乎不可察觉但画面"活"起来）：

```python
HOLD_KEN_BURNS_START_ZOOM = 0.97

def write_hold_with_ken_burns(camera_writer, img_resized, canvas_w, canvas_h, hold_frames):
    for f in range(hold_frames):
        t = ease_in_out(f / max(1, hold_frames - 1))
        zoom = HOLD_KEN_BURNS_START_ZOOM + (1.0 - HOLD_KEN_BURNS_START_ZOOM) * t
        w, h = int(canvas_w * zoom), int(canvas_h * zoom)
        x, y = (canvas_w - w) // 2, (canvas_h - h) // 2
        camera_writer.set_viewport({"x": x, "y": y, "w": w, "h": h})
        camera_writer.write(img_resized)
```

### 7. 结束过渡：alpha blend + zoom-out 同步

最后一个元素 colorize 完成后，bbox 外区域仍是空白背景。若直接切到完整原图会有跳变。blend（内容补全）与 zoom-out（镜头拉远）用不同缓动同步进行：blend 先快后慢（观众先看到内容补全），zoom 先慢后快（给 blend 时间先完成）：

```python
blend_zoom_frames = 90  # ~1.5s @ 60fps
for f in range(blend_zoom_frames):
    t = (f + 1) / blend_zoom_frames
    blend_t = t ** 0.5   # ease-out
    zoom_t = t ** 2       # ease-in
    blended = cv2.addWeighted(drawn_frame_uint8, 1 - blend_t, img_resized, blend_t, 0)
    vp = interpolate_viewport(current_viewport, full_viewport, zoom_t)
    camera_writer.set_viewport(vp)
    camera_writer.write(blended)
```

### 8. 文字手写动画

`banana_prompt_template` 明确禁止画面中出现文字（"Absolutely no text"），但脚本常需要画面文字（如"判断"二字）。方案：**不在 AI 生成图片中包含文字，改在 Remotion 层叠加逐字手写动画**，不依赖 AI 是否遵守指令，视觉效果精确可控。

不采用 SVG 笔画路径动画（对 CJK 字符过于复杂），而是用 spring 动画逐字弹出 + 手部 PNG 跟随书写位置——在镜头缩放已建立的"手绘"语境下，这个简化足够可信：

```tsx
const HandwrittenText: React.FC<Props> = ({ text, startFrame, durationFrames, x, y, fontSize, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const chars = [...text];  // 正确拆分 CJK
  const framesPerChar = durationFrames / chars.length;

  return (
    <div style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", display: "flex" }}>
      {chars.map((char, i) => {
        const charStart = startFrame + i * framesPerChar;
        const age = frame - charStart;
        const opacity = age < 0 ? 0 : interpolate(age, [0, 4], [0, 1], { extrapolateRight: "clamp" });
        const scale = age < 0 ? 0 : spring({ frame: Math.max(0, age), fps, config: { stiffness: 300, damping: 20 } });
        return (
          <span key={i} style={{
            fontFamily: "'ZCOOL KuaiLe'", fontSize, color,
            visibility: age < 0 ? "hidden" : "visible",
            opacity, transform: `scale(${scale})`,
            transformOrigin: "center bottom", display: "inline",
          }}>{char}</span>
        );
      })}
      <WritingHand chars={chars} startFrame={startFrame} framesPerChar={framesPerChar} fontSize={fontSize} />
    </div>
  );
};
```

用 `visibility: hidden/visible` 而非固定字宽，让浏览器自然排版——中英数字混排间距自然。`textOverlay.drawAt` 通常落在 hold 阶段（镜头已缩回全画布），文字在全画布视角下书写；写完最后一个字后 5 帧淡出。

### 9. 绘画音效

**设计决策：Remotion 层而非 Python 层处理时序。** SFX 时序与 timeline.json 同源，Remotion 原生处理音频同步；调整 timeline 后 SFX 自动对齐，Python 层只负责视觉渲染。

**零依赖合成音效：** 内置 `generate_default_sfx.py`，用 numpy + pydub 程序化生成，首次运行自动生成到 `remotion-project/public/assets/sfx/`（已存在则跳过），用户可替换为真实音效：

- `pen_sketch.mp3`：带通滤波白噪声（2-8kHz）+ 不规则振幅包络，模拟铅笔沙沙声
- `marker_color.mp3`：低通滤波白噪声（500-3kHz）+ 平滑包络，模拟马克笔声
- 首尾 crossfade 处理，完美循环

**时序对齐 sketch/colorize 两个 pass**（而非 v8 式的单一 per-element 时长拆分），每段 SFX 加 ~5 帧 fade-in/fade-out 避免硬切：

```tsx
const DrawingSFX: React.FC<{ elements: ElementTimeline[] }> = ({ elements }) => (
  <>
    {elements.map((elem) => (
      <React.Fragment key={elem.id}>
        <Sequence from={elem.sketchAtFrame} durationInFrames={elem.sketchDurationFrames}>
          <Audio src={staticFile("assets/sfx/pen_sketch.mp3")} loop
            volume={(f) => {
              const dur = elem.sketchDurationFrames;
              const fadeIn = interpolate(f, [0, 5], [0, 0.12], { extrapolateRight: "clamp" });
              const fadeOut = interpolate(f, [dur - 5, dur], [0.12, 0], { extrapolateLeft: "clamp" });
              return Math.min(fadeIn, fadeOut);
            }} />
        </Sequence>
        <Sequence from={elem.colorizeAtFrame} durationInFrames={elem.colorizeDurationFrames}>
          <Audio src={staticFile("assets/sfx/marker_color.mp3")} loop
            volume={(f) => {
              const dur = elem.colorizeDurationFrames;
              const fadeIn = interpolate(f, [0, 5], [0, 0.08], { extrapolateRight: "clamp" });
              const fadeOut = interpolate(f, [dur - 5, dur], [0.08, 0], { extrapolateLeft: "clamp" });
              return Math.min(fadeIn, fadeOut);
            }} />
        </Sequence>
      </React.Fragment>
    ))}
  </>
);
```

元素间过渡帧内无 Sequence → 自然静音 → 镜头移动时的安静反而增强节奏感（暗示"画师在移动手臂准备下一笔"）。

### 10. 性能优化：画手一次加载 + 多尺寸缓存

`preprocess_hand_image` 每次调用都从磁盘读取 PNG。sketch-first 模式下 n 个元素需要 2n 次镜头缩放，若每次都重新读盘会有不必要的 I/O 开销。方案：只在场景开始时加载一次原始尺寸，后续按需缩放并缓存：

```python
_hand_cache = {}  # target_ht → {"hand", "hand_mask", "hand_mask_inv", "hand_ht", "hand_wd"}

def load_hand_once(hand_path, variables):
    """首次加载手部图像到 variables（引擎函数固定尺寸 493px），存入缓存。"""
    preprocess_hand_image(hand_path, variables)
    _hand_cache[variables["hand_ht"]] = {
        k: variables[k].copy() if isinstance(variables[k], np.ndarray) else variables[k]
        for k in ("hand", "hand_mask", "hand_mask_inv", "hand_ht", "hand_wd")
    }

def scale_hand_for_zoom(variables, zoom_ratio):
    """将缓存的原始尺寸手部图像缩放到当前镜头缩放级别，写回 variables。"""
    target_ht = max(100, int(HAND_TARGET_HT * zoom_ratio))
    if target_ht in _hand_cache:
        variables.update(_hand_cache[target_ht])
        return variables

    orig = _hand_cache[HAND_TARGET_HT]
    ratio = target_ht / orig["hand_ht"]
    new_w = max(1, int(orig["hand_wd"] * ratio))
    variables["hand"] = cv2.resize(orig["hand"], (new_w, target_ht), interpolation=cv2.INTER_AREA)
    variables["hand_mask"] = cv2.resize(orig["hand_mask"], (new_w, target_ht), interpolation=cv2.INTER_AREA)
    variables["hand_mask_inv"] = 1.0 - variables["hand_mask"]
    variables["hand_ht"], variables["hand_wd"] = target_ht, new_w

    _hand_cache[target_ht] = {k: variables[k].copy() if isinstance(variables[k], np.ndarray) else variables[k]
                              for k in ("hand", "hand_mask", "hand_mask_inv", "hand_ht", "hand_wd")}
    return variables
```

引擎的绘制函数从 `variables` 读取手部数据，对这层缓存完全无感知。



---

## storyboard.json Schema

管线的单一数据源。

```json
{
  "meta": {
    "title": "AI时代资产蓝图",
    "topic": "ai-asset",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "imageStyle": "whiteboard",
    "imageAspectRatio": "16:9",
    "drawMode": "sketch_first",
    "pipeline": {
      "mode": "video_first",
      "defaultSceneDuration": null
    },
    "camera": {
      "enabled": true,
      "maxZoom": 2.5,
      "transitionMs": 800
    },
    "tts": {
      "provider": "tencent",
      "voice": 602005,
      "speed": 1.1
    },
    "subtitle": { "enabled": true, "fontSize": 36 },
    "transition": { "type": "fade", "durationFrames": 15 },
    "animationEngine": "whiteboard"
  },
  "scenes": [
    {
      "id": "scene1",
      "imagePrompt": "画面左侧一个火柴人坐在电脑前低头工作，头上冒汗珠；右上方一个巨大的闹钟时针飞速旋转；右下角散落几张纸币。各元素之间有明确的空白间隔。",
      "voiceText": "还在单纯靠出卖劳动时间，来换取那点微薄的工资吗？",
      "duration": null,
      "elements": [
        {
          "id": "person",
          "description": "火柴人坐在电脑前低头工作，头上冒汗珠",
          "bbox": {"x": 80, "y": 250, "w": 500, "h": 550},
          "drawAt": null,
          "narration": "还在单纯靠出卖劳动时间，"
        },
        {
          "id": "clock",
          "description": "巨大的闹钟时针飞速旋转",
          "bbox": {"x": 700, "y": 50, "w": 400, "h": 400},
          "drawAt": null,
          "narration": "来换取那点微薄的工资吗？"
        },
        {
          "id": "money",
          "description": "散落的纸币",
          "bbox": {"x": 750, "y": 550, "w": 350, "h": 300},
          "drawAt": null,
          "narration": ""
        }
      ]
    },
    {
      "id": "scene3",
      "imagePrompt": "画面中间一个简洁的大脑轮廓，脑内中心留白...",
      "voiceText": "停止做执行者，开始做拥有高阶判断力的决策者。",
      "duration": null,
      "textOverlay": {
        "text": "判断",
        "x": 960, "y": 500,
        "fontSize": 120, "color": "#2D3748",
        "style": "handwritten",
        "drawAt": 0.7,
        "duration": 1.5
      }
    }
  ]
}
```

### 字段说明

**meta 级别：**

| 字段 | 说明 |
|------|------|
| `drawMode` | `"sketch_first"`（默认）双程绘制 / `"sequential"` 逐元素完成 |
| `pipeline.mode` | `"full"` = 含 TTS+音频；`"video_first"` = 只出视频+字幕+绘画音效 |
| `pipeline.defaultSceneDuration` | 手动指定默认场景时长（秒），null 时自动估算 |
| `camera.enabled` | 虚拟镜头开关，默认 true |
| `camera.maxZoom` | 最大缩放倍数，默认 2.5 |
| `camera.transitionMs` | 镜头过渡基准时间（毫秒），默认 800 |
| `imageStyle` | prompt 风格模板：`"whiteboard"` / `"blackboard"` / `"notebook"` / `"custom"` |
| `animationEngine` | `"whiteboard"`（当前唯一选项） |

**scene 级别：**

| 字段 | 说明 |
|------|------|
| `imagePrompt` | 画面描述，多元素场景应描述元素的空间分布 |
| `voiceText` | TTS 配音文本 / video_first 模式下用于生成字幕 |
| `duration` | 手动指定场景时长（秒），null 时自动计算 |
| `elements` | 场景内的可绘制元素列表；不存在时自动生成全画布单元素 |
| `textOverlay` | 可选，Remotion 层手写文字叠加 |

**element 级别：**

| 字段 | 说明 |
|------|------|
| `id` | 元素唯一标识（场景内唯一） |
| `description` | 元素内容描述（用于 prompt 空间引导 + 调试日志） |
| `bbox` | 源图片坐标系的像素坐标 `{x, y, w, h}`（引擎 resize 时等比转换） |
| `drawAt` | null 时由管线自动编排；手动指定时覆盖自动值（秒） |
| `narration` | 此元素 sketch 阶段显示的字幕文本；所有元素拼接应约等于 voiceText |

**textOverlay 级别：**

| 字段 | 说明 |
|------|------|
| `style` | `"handwritten"` 逐字弹出+手部跟随 / `"fade"` 简单淡入，默认 `"handwritten"` |
| `drawAt` | 场景开始后的秒数 |
| `duration` | 手写持续秒数，默认 `text.length * 0.3` |

---

## 时间轴编排

### mode=full（有 TTS）

1. 整段 `voiceText` → TTS → 一个完整 WAV（保持语气连贯，不逐句合成）
2. 静音检测（pydub `detect_silence`）+ 标点位置对齐 → 切割出每个元素 narration 在完整音频中的实际起止时间
3. per-element `durationMs` = 对应音频片段时长（精确匹配语音）
4. 场景总时长 = 语音总时长 + 镜头过渡时间 + 阶段过渡 + blend/hold

### mode=video_first（无 TTS）

```python
def estimate_scene_duration(scene, draw_mode="sketch_first", transition_ms=800):
    elements = scene.get("elements", [])
    n = len(elements)
    total_chars = sum(len(e.get("narration", "")) for e in elements)
    narration_s = total_chars / 4.0 * 1.2       # 中文 ~4字/秒 + 20% 余量
    min_anim_s = n * 2.0                         # 每个元素最少 2s 动画
    anim_s = max(min_anim_s, narration_s)

    if draw_mode == "sketch_first" and n > 1:
        # sketch 阶段 (n-1) 次 dip + 阶段过渡(1.5x) + colorize 阶段 (n-1) 次 breathe
        transition_s = ((n - 1) * 2 + 1.5) * transition_ms / 1000
    else:
        transition_s = (n - 1) * transition_ms / 1000

    blend_s, hold_s = 1.5, 1.5
    return anim_s + transition_s + blend_s + hold_s


def compute_element_durations(scene, scene_duration_s, transition_ms=800, draw_mode="sketch_first"):
    """按 narration 字数比例分配 per-element 动画时长预算。"""
    elements = scene.get("elements", [])
    n = len(elements)
    blend_s, hold_s = 1.5, 1.5

    if draw_mode == "sketch_first" and n > 1:
        total_transition_s = ((n - 1) * 2 + 1.5) * transition_ms / 1000
    else:
        total_transition_s = (n - 1) * transition_ms / 1000

    anim_budget_ms = max(0, (scene_duration_s - blend_s - hold_s - total_transition_s) * 1000)
    total_chars = sum(len(e.get("narration", "")) for e in elements) or n

    for elem in elements:
        chars = len(elem.get("narration", "")) or 1
        elem["durationMs"] = max(1500, int(anim_budget_ms * chars / total_chars))
```

用户手动设置 `elements[].drawAt` / `duration` 会覆盖自动计算；若手动设置的间隔小于 `transitionMs`，打印警告但不阻断执行。

### ElementTimeline 输出结构

v8 式的单一 `drawAtFrame + durationFrames` 无法表达 sketch/colorize 两个独立阶段。`compute_timeline.py` 为每个元素输出四个时间点（场景内相对帧号）：

```python
element_timeline = {
    "id": "person",
    "sketchAtFrame": 0,
    "sketchDurationFrames": 120,
    "colorizeAtFrame": 450,       # sketch_first 模式下位于 Pass 2 区间；sequential 模式下紧邻 sketchAtFrame+sketchDurationFrames
    "colorizeDurationFrames": 60,
    "narration": "还在单纯靠出卖劳动时间，"
}
```

`sketch/colorize` 各阶段帧数按引擎常量 `SKETCH_PHASE_WEIGHT:COLOR_PHASE_WEIGHT = 2:1` 从 `durationMs` 拆分。


---

## generate_scene_animation.py 完整流程

```python
def generate_scene_with_regions(image_path, regions, total_duration_ms, output_dir,
                                 camera_config=None, draw_hand=True, draw_mode="sketch_first"):
    camera_enabled = camera_config.get("enabled", True) if camera_config else True
    max_zoom = camera_config.get("maxZoom", 2.5) if camera_config else 2.5
    transition_ms = camera_config.get("transitionMs", 800) if camera_config else 800

    # ── 1. 读取图片 + 统一 resize（max_dim=1920）──
    img_bgr = cv2.imread(image_path)
    orig_h, orig_w = img_bgr.shape[:2]
    max_dim = 1920
    scale = max_dim / max(orig_w, orig_h)
    lcm = SPLIT_LEN if SPLIT_LEN % 2 == 0 else SPLIT_LEN * 2
    resize_wd = (int(orig_w * scale) // lcm) * lcm
    resize_ht = (int(orig_h * scale) // lcm) * lcm

    sx, sy = resize_wd / orig_w, resize_ht / orig_h
    for region in regions:
        b = region["bbox"]
        region["scaled_bbox"] = {"x": int(b["x"]*sx), "y": int(b["y"]*sy),
                                  "w": int(b["w"]*sx), "h": int(b["h"]*sy)}

    variables = {"split_len": SPLIT_LEN, "resize_wd": resize_wd, "resize_ht": resize_ht,
                 "draw_hand": draw_hand}
    img_resized = cv2.resize(img_bgr, (resize_wd, resize_ht))
    variables["img"] = img_resized
    variables = preprocess_image(img_resized, variables)
    variables["grid_of_cuts"] = split_image_into_cells(variables["img_thresh"], SPLIT_LEN)
    active_grid, _ = extract_active_grid(variables["img_thresh"], SPLIT_LEN, BLACK_PIXEL_THRESHOLD)
    variables["active_grid"] = active_grid
    layout_blocks = build_layout_blocks(active_grid)
    full_draw_order = build_draw_order(active_grid, layout_blocks=layout_blocks)

    # ── 2. 预计算每个元素的视口 / 过滤路径（含连续性修复）/ 笔刷半径 ──
    sorted_regions = sorted(regions, key=lambda r: r.get("drawAt", 0))
    full_vp = {"x": 0, "y": 0, "w": resize_wd, "h": resize_ht}
    for region in sorted_regions:
        region["_viewport"] = compute_element_viewport(region["scaled_bbox"], resize_wd, resize_ht, max_zoom)
        raw_order = filter_draw_order_for_bbox(full_draw_order, region["scaled_bbox"])
        region["_draw_order"] = ensure_path_coherence(raw_order)
        region["_brush_radius"] = compute_adjusted_brush_radius(region["_viewport"]["w"], resize_wd)

    # ── 3. VideoWriter ──
    OUTPUT_W, OUTPUT_H = 1920, 1080
    raw_path = os.path.join(output_dir, f"raw_{int(time.time())}.mp4")
    h264_path = raw_path.replace("raw_", "vid_").replace(".mp4", "_h264.mp4")
    real_writer = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*"mp4v"), FRAME_RATE, (OUTPUT_W, OUTPUT_H))
    camera_writer = CameraVideoWriter(real_writer, resize_wd, resize_ht, OUTPUT_W, OUTPUT_H)
    variables["video_object"] = camera_writer
    variables["drawn_frame"] = create_background_canvas(img_resized.shape)
    if draw_hand:
        load_hand_once(HAND_PATH, variables)

    colorize_skip = int(SKIP_RATE * COLOR_SKIP_MULTIPLIER)

    def get_phase_frames(region):
        elem_ms = region.get("durationMs", 3000)
        sketch_ms = elem_ms * SKETCH_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT)
        return round(sketch_ms * FRAME_RATE / 1000), round((elem_ms - sketch_ms) * FRAME_RATE / 1000)

    def do_transition(current_vp, target_vp, phase):
        strategy = choose_transition_strategy(current_vp, target_vp, resize_wd, resize_ht, phase)
        trans_frames = round(transition_ms * FRAME_RATE / 1000)
        frame = variables["drawn_frame"]
        frame = frame if frame.dtype == np.uint8 else frame.astype(np.uint8)
        if strategy == "dip":
            write_dip_transition(camera_writer, frame, current_vp, target_vp, trans_frames)
        else:
            write_breathe_transition(camera_writer, frame, current_vp, target_vp, resize_wd, resize_ht, trans_frames)

    # ── 4. 绘制 ──
    current_viewport = full_vp
    n = len(sorted_regions)

    if draw_mode == "sketch_first" and n > 1:
        # Pass 1: 全部线稿
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx == 0:
                camera_writer.set_viewport(target_vp)
            else:
                do_transition(current_viewport, target_vp, phase="sketch")
            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)

            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                sketch_frames, _ = get_phase_frames(region)
                draw_masked_object(variables, sketch_frames * SKIP_RATE, skip_rate=SKIP_RATE)
            current_viewport = target_vp

        # 阶段过渡（长 dip，标记 sketch → colorize 的转折）
        phase_trans_frames = round(transition_ms * 1.5 * FRAME_RATE / 1000)
        first_vp = sorted_regions[0]["_viewport"]
        frame = variables["drawn_frame"]
        frame = frame if frame.dtype == np.uint8 else frame.astype(np.uint8)
        write_dip_transition(camera_writer, frame, current_viewport, first_vp, phase_trans_frames)
        current_viewport = first_vp

        # Pass 2: 全部上色
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx > 0:
                do_transition(current_viewport, target_vp, phase="colorize")
            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)
            camera_writer.set_viewport(target_vp)

            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                _, color_frames = get_phase_frames(region)
                colorize_animation(variables, color_frames * colorize_skip,
                                   skip_rate=colorize_skip, brush_radius=region["_brush_radius"])
                if variables["drawn_frame"].dtype != np.uint8:
                    variables["drawn_frame"] = variables["drawn_frame"].astype(np.uint8)
            current_viewport = target_vp

    else:
        # sequential 模式（单元素场景，或用户显式选择）
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx == 0:
                camera_writer.set_viewport(target_vp)
            else:
                do_transition(current_viewport, target_vp, phase="colorize")
            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)

            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                sketch_frames, color_frames = get_phase_frames(region)
                draw_masked_object(variables, sketch_frames * SKIP_RATE, skip_rate=SKIP_RATE)
                colorize_animation(variables, color_frames * colorize_skip,
                                   skip_rate=colorize_skip, brush_radius=region["_brush_radius"])
                if variables["drawn_frame"].dtype != np.uint8:
                    variables["drawn_frame"] = variables["drawn_frame"].astype(np.uint8)
            current_viewport = target_vp

    # ── 5. 结束过渡 + Hold ──
    drawn_frame_uint8 = variables["drawn_frame"]
    drawn_frame_uint8 = drawn_frame_uint8 if drawn_frame_uint8.dtype == np.uint8 else drawn_frame_uint8.astype(np.uint8)

    blend_zoom_frames = 90
    elapsed_frames = _count_written_frames(camera_writer)  # 内部帧计数器
    total_frames_target = round(total_duration_ms * FRAME_RATE / 1000)
    total_end_frames = max(blend_zoom_frames + 60, total_frames_target - elapsed_frames)
    actual_blend_frames = min(blend_zoom_frames, total_end_frames)

    for f in range(actual_blend_frames):
        t = (f + 1) / actual_blend_frames
        blended = cv2.addWeighted(drawn_frame_uint8, 1 - t**0.5, img_resized, t**0.5, 0)
        vp = interpolate_viewport(current_viewport, full_vp, t**2)
        camera_writer.set_viewport(vp)
        camera_writer.write(blended)

    write_hold_with_ken_burns(camera_writer, img_resized, resize_wd, resize_ht,
                               total_end_frames - actual_blend_frames)

    # ── 6. 释放 + H.264 转码 ──
    camera_writer.release()
    ffmpeg_convert(raw_path, h264_path)
    if os.path.exists(h264_path) and os.path.getsize(h264_path) > 0:
        os.remove(raw_path)
    return h264_path
```


---

## Remotion 合成

### types.ts

```typescript
export interface ElementTimeline {
  id: string;
  sketchAtFrame: number;       // 场景内相对帧号
  sketchDurationFrames: number;
  colorizeAtFrame: number;
  colorizeDurationFrames: number;
  narration: string;
}

export interface SceneTimeline {
  id: string;
  startFrame: number;
  durationFrames: number;
  elements?: ElementTimeline[];
}

export interface Timeline {
  fps: number;
  totalFrames: number;
  frameReference: "scene-relative";
  drawMode: "sketch_first" | "sequential";
  scenes: SceneTimeline[];
}

export interface TextOverlayConfig {
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
  style?: "handwritten" | "fade";
  drawAt?: number;
  duration?: number;
}

export interface StoryboardElement {
  id: string;
  description: string;
  bbox: { x: number; y: number; w: number; h: number };
  drawAt: number | null;
  narration: string;
}

export interface StoryboardScene {
  id: string;
  imagePrompt: string;
  voiceText: string;
  duration: number | null;
  elements?: StoryboardElement[];
  textOverlay?: TextOverlayConfig;
}

export interface CameraConfig {
  enabled?: boolean;
  maxZoom?: number;
  transitionMs?: number;
}

export interface Storyboard {
  meta: {
    title: string; topic: string; fps: number;
    width: number; height: number;
    imageStyle: string; imageAspectRatio: string;
    drawMode: "sketch_first" | "sequential";
    pipeline: { mode: string; defaultSceneDuration: number | null };
    camera?: CameraConfig;
    tts: { provider: string; voice: number; speed: number };
    subtitle: { enabled: boolean; fontSize: number };
    transition: { type: string; durationFrames: number };
    animationEngine: string;
  };
  scenes: StoryboardScene[];
}
```

### WhiteboardVideo.tsx

```tsx
export const WhiteboardVideo: React.FC = () => {
  const fps = storyboard.meta.fps;
  const totalF = timeline.totalFrames;
  const hasAudio = storyboard.meta.pipeline.mode === "full";

  const bgmVolume = (frame: number) => {
    const fadeIn = interpolate(frame, [0, 30], [0, 0.03], { extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [totalF - 30, totalF], [0.03, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return Math.min(fadeIn, fadeOut);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#F6F1E3" }}>
      {hasAudio && <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />}

      {timeline.scenes.map((tScene, i) => {
        const scene = storyboard.scenes[i];

        const subSegs = tScene.elements
          ? tScene.elements
              .filter((e) => e.narration)
              .map((elem) => ({
                text: elem.narration,
                startTime: elem.sketchAtFrame / fps,
                endTime: (elem.sketchAtFrame + elem.sketchDurationFrames) / fps,
              }))
          : [{ text: scene.voiceText, startTime: 0, endTime: tScene.durationFrames / fps }];

        return (
          <Sequence key={tScene.id} from={tScene.startFrame} durationInFrames={tScene.durationFrames}>
            <AbsoluteFill style={{ backgroundColor: "#F6F1E3" }}>
              <Grid />
              <Video
                src={staticFile(`animations/${scene.id}_final.mp4`)}
                style={{ width: "100%", height: "100%", objectFit: "contain" }}
              />
              <Subtitle segments={subSegs} />
              {tScene.elements && <DrawingSFX elements={tScene.elements} />}
              {hasAudio && <Audio src={staticFile(`audio/${scene.id}.wav`)} volume={5.0} />}
              {scene.textOverlay && (
                <TextOverlay config={scene.textOverlay} sceneDurationFrames={tScene.durationFrames} />
              )}
            </AbsoluteFill>
          </Sequence>
        );
      })}

      <ProgressBar />
    </AbsoluteFill>
  );
};
```

`HandwrittenText`、`DrawingSFX`、`Grid`、`ProgressBar` 组件定义参见前述"视觉真实感设计"章节 8/9。`Grid`、`ProgressBar`、BGM 音量函数参考 `whiteboard-video` 项目的 `LightclawaceVideo.tsx` 实现模式。

**关键约定：每个 `Sequence` 内必须有独立背景**（`<AbsoluteFill style={{backgroundColor}}>` + `<Grid/>`），否则场景切换时出现黑帧。

---

## 目录结构

```
/home/admin/workspace/video/
├── plan_v10.md
├── .env
├── .env.example
├── requirements.txt              # pydub, edge-tts, tencentcloud-sdk-python-tts,
│                                  #   python-dotenv, opencv-python, numpy, av, scipy
├── remotion-project/
│   ├── package.json              # remotion@4.0.0, @remotion/cli, react, react-dom,
│   │                              #   @fontsource/zcool-kuaile, @remotion/media-utils
│   ├── tsconfig.json
│   ├── src/
│   │   ├── index.tsx             # registerRoot, Composition id="VideoMain"
│   │   ├── WhiteboardVideo.tsx   # 主合成器
│   │   └── types.ts
│   └── public/
│       ├── fonts/ZCOOLKuaiLe-Regular.ttf
│       ├── bgm.mp3
│       └── assets/
│           ├── sfx/
│           │   ├── pen_sketch.mp3       # 首次运行自动生成
│           │   └── marker_color.mp3
│           └── writing-hand-small.png   # 从 drawing-hand.png 缩放而来
├── scripts/
│   ├── make_video.py              # 一键入口，编排全部步骤
│   ├── parse_storyboard.py        # 脚本 → storyboard.json（无 elements 自动生成全画布单元素）
│   ├── generate_prompts.py        # 生成 prompt（含空间分离引导 + 风格一致性指引）
│   ├── validate_images.py         # 校验图片齐全性/尺寸/背景色/风格一致性
│   ├── detect_regions.py          # 自动检测元素区域 → preview + JSON
│   ├── generate_scene_animation.py  # 核心：镜头驱动手绘动画引擎
│   ├── generate_animations.py     # 批量调用 scene_animation（统一走该路径）
│   ├── generate_default_sfx.py    # 程序化生成合成音效
│   ├── tts_pipeline.py            # 整段 TTS + 静音检测切割
│   ├── compute_timeline.py        # drawAt 自动编排 + per-element 四段帧号
│   ├── generate_subtitles.py      # 生成 SRT 字幕（对齐 sketch 阶段）
│   ├── audio_mixer.py             # 三层混音（mode=full）
│   ├── deploy_resources.py        # 复制资源到 remotion-project/public/
│   ├── generate_publish.py        # 发布文案
│   └── validate.py                # 环境校验 + storyboard schema 校验
├── cache/tts/                     # TTS 缓存（sha256(text+voice+speed)）
└── output/{topic}-{date}/
    ├── storyboard.json
    ├── prompts.md
    ├── images/{scene_id}.png
    ├── regions_preview.png
    ├── regions_detected.json
    ├── audio/{scene_id}.wav
    ├── animations/{scene_id}_final.mp4
    ├── timeline.json
    ├── subtitles.srt
    ├── video.mp4 / video_silent.mp4
    ├── publish.md
    └── .checkpoint.json
```

---

## 可直接引用的文件

| 引用来源 | 文件 | 用途 | 引用方式 |
|---------|------|------|---------|
| `whiteboard-video-workflow/whiteboard-animation` | `scripts/generate_whiteboard.py` | 核心手绘动画算法函数 | **Python import**（不修改原文件） |
| `whiteboard-video-workflow/whiteboard-animation` | `assets/drawing-hand.png` | 手部素材 | 引擎加载 + 缩放缓存 |
| `whiteboard-video-workflow/whiteboard-video-workflow` | `scripts/banana_prompt_template.py` | 白板风格 prompt 模板 | import 读取 |
| `whiteboard-video-workflow/whiteboard-video-workflow` | `scripts/generate-image.py` | AI 文生图参考实现（可选） | 参考 / 可选调用 |
| `whiteboard-video-workflow/whiteboard-video-workflow` | `scripts/generate-image-gemini.py` | 降级文生图方案 | 参考 / 可选调用 |
| `whiteboard-video-workflow/shorts-audio-engine` | `scripts/mixer.py` | 三层混音 | import 调用 |
| `whiteboard-video-workflow/shorts-audio-engine` | `scripts/sfx_library.py` | 关键词→音效映射 | import 调用 |
| `whiteboard-video` | `scripts/tts_tencent.py` | 腾讯云 TTS | subprocess 调用 |
| `whiteboard-video` | `remotion-project/src/LightclawaceVideo.tsx` | Grid/Subtitle/ProgressBar/BGM 音量函数模式参考 | 参考实现（不直接复制文件） |
| `whiteboard-video` | `remotion-project/public/bgm.mp3` | 背景音乐 | 复制到 remotion-project |

### Python 路径解析（统一约定）

```python
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-animation"
sys.path.insert(0, str(_ENGINE_DIR / "scripts"))

assert _ENGINE_DIR.exists(), f"Animation engine not found at {_ENGINE_DIR}"
assert (_ENGINE_DIR / "assets" / "drawing-hand.png").exists(), "Hand asset missing"

from generate_whiteboard import (
    preprocess_image, preprocess_hand_image, split_image_into_cells,
    extract_active_grid, build_layout_blocks, build_draw_order,
    draw_masked_object, colorize_animation, create_background_canvas,
    ffmpeg_convert, FRAME_RATE, SPLIT_LEN, SKIP_RATE, HAND_PATH,
    BACKGROUND_BGR, SKETCH_PHASE_WEIGHT, COLOR_PHASE_WEIGHT,
    BLACK_PIXEL_THRESHOLD, COLOR_BRUSH_RADIUS, HAND_TARGET_HT,
)
```

所有脚本用 `Path(__file__)` 相对项目根解析依赖路径，不硬编码绝对路径；关键文件用 `assert` 做启动期 sanity check，缺失时立即失败并给出明确提示，而非运行到中途才报错。

---


## 完整入口命令

```bash
# === 视频优先模式（推荐的两步流程）===

# 第一步：生成 prompt
python scripts/make_video.py --storyboard storyboard.json --mode video-first
# 输出: prompts.md

# 用户生成图片放入 images/ 后（可选先跑区域检测辅助标注 bbox）：
python scripts/detect_regions.py output/{topic}/images/scene1.png
# 查看 regions_preview.png，在 storyboard.json 中设置 elements[].bbox

# 第二步：生成视频（含镜头运动 + 绘画音效）
python scripts/make_video.py --storyboard storyboard.json --mode video-first --skip-prompts
# 输出: video_silent.mp4 + subtitles.srt

# 第三步：后续补音频（可选）
python scripts/make_video.py --storyboard storyboard.json --audio-only \
  --video output/{topic}/video_silent.mp4
# 输出: video.mp4

# === 完整模式（一次出成品，需要 TTS API key）===
python scripts/make_video.py --storyboard storyboard.json --mode full
```

### make_video.py 编排逻辑

```
if --audio-only:
    Step 5: TTS → Step 10: 混音 → ffmpeg 合并到已有视频
    exit

Step 0:  validate 环境检查（ffmpeg、ffprobe、API keys、Python 依赖）
Step 1:  parse_storyboard（无 elements 自动生成全画布单元素）
Step 2:  generate_prompts → prompts.md
         ⏸ 暂停，等用户生成图片放入 images/
         ⏸ 可选：运行 detect_regions 辅助标注 bbox
Step 3:  validate_images
Step 5:  tts_pipeline（仅 mode=full，整段 TTS + 静音检测切割）
Step 6:  compute_timeline（drawAt 自动编排 + per-element durationMs + 四段帧号）
Step 7:  generate_default_sfx（首次运行自动生成合成音效）
Step 8:  generate_animations（统一走 generate_scene_animation，sketch_first/sequential）
Step 9:  compute_timeline（终，ffprobe 校正实际视频时长）+ generate_subtitles
Step 10: audio_mixer（仅 mode=full）
Step 11: deploy_resources → remotion render
Step 12: generate_publish

每步完成写 .checkpoint.json，支持断点续跑（重跑时跳过已完成步骤，除非上游产物已变化）。
```

---

## 约束清单

1. 插画必须用浅色背景（引擎对浅色背景效果最佳）
2. `banana_prompt_template` 明确禁止画面文字（"Absolutely no text"），画面文字统一用 `textOverlay` 在 Remotion 层叠加
3. 单场景总时长至少 6 秒（blend+hold ~3s + 至少 1.5s 动画 + 过渡开销）
4. 单元素最小动画时长 1500ms（sketch + colorize 各需足够帧数）
5. 输出固定 1920×1080（`CameraVideoWriter` 统一裁剪+缩放，无需额外 ffmpeg pad）
6. Remotion 中用 `<Video>` 嵌入手绘动画 MP4，音频独立于 `<Audio>` 播放
7. 每个 `Sequence` 内必须有独立背景（`AbsoluteFill` + `Grid`），防止场景切换黑帧
8. TTS 前将中文标点转换为英文标点（`normalize_punctuation`）
9. 混音中语音音量 +5dB（腾讯云 TTS 输出偏小）
10. 多元素场景的 `imagePrompt` 必须包含空间分离描述，引导 AI 生成元素间有明确间隔的构图
11. `elements[].narration` 拼接应约等于 `voiceText`
12. `bbox` 使用源图片坐标系，引擎 resize 时按比例转换，不需要用户手动换算
13. 所有脚本路径通过 `Path(__file__)` 相对项目根解析，禁止硬编码绝对路径
14. TTS 单条请求上限 150 汉字（超限需拆分或使用长文本切分降级方案）
15. 图片文件名必须与 scene id 一致（如 `scene1.png`）
16. `sketchAtFrame` / `colorizeAtFrame` 是场景内相对偏移，不是全局帧号
17. 画手尺寸必须按 viewport/canvas 比例反向缩放，通过缓存缩放实现而非引擎参数
18. 合成音效首次运行自动生成，用户可替换为真实录音素材
19. `drawAt` 手动值间隔小于 `transitionMs` 时打印警告但不阻断执行
20. sketch-first 模式下每次 `colorize_animation` 调用后必须检查并转回 `drawn_frame` 为 uint8
21. 路径连续性重排阈值 3.0（低于此值保留引擎原始智能遍历策略，不做任何改动）
22. 笔刷半径下限 15px，防止极端缩放下笔刷过小导致上色留白
23. sketch 阶段的镜头过渡必须使用 dip 策略，不使用 breathe（避免暴露未绘制区域）

---

## 已知问题与解决方案

### 引擎调用相关

**Q1：动画引擎输出 60fps，Remotion 以 30fps 渲染。**
解决：`ffmpeg_convert` 转码后额外用 ffmpeg `-r 30` 统一帧率，或依赖 Remotion `<Video>` 自适应播放（生产环境建议显式转码，避免时长误差累积）。

**Q2：`generate_whiteboard.py` 原生输出文件名基于时间戳，不可预测。**
解决：`generate_scene_animation.py` 内部固定使用 `raw_{timestamp}.mp4` → `vid_..._h264.mp4` 命名模式，`generate_animations.py` 统一重命名为 `{scene_id}_final.mp4`。

**Q3：短时长场景的 hold 阶段（引擎默认 3 秒）挤占动画时间。**
解决：约束清单第 3、4 条的时长下限已覆盖此问题；`estimate_scene_duration` 计算已包含 blend+hold 预算。

**Q4：`colorize_animation` 将 `drawn_frame` 转为 float32，多次调用需注意 dtype。**
解决：见约束清单第 20 条，每次 colorize 后显式检查转换。

**Q5：`generate_whiteboard.py` 的 `setup_env.py` 依赖需要用其创建的 venv 执行，不能用系统 Python。**
解决：`validate.py` 启动时检测：
```python
result = subprocess.run([sys.executable, f"{ANIM_DIR}/scripts/setup_env.py", "--check"],
                        capture_output=True, text=True)
if result.returncode != 0:
    subprocess.run([sys.executable, f"{ANIM_DIR}/scripts/setup_env.py"])
```

**Q6：TTS `.env` 路径依赖 `whiteboard-video` 项目根目录（`tts_tencent.py` 内部通过 `dirname(__file__)/../.env` 加载）。**
解决：调用前通过环境变量传入密钥（环境变量优先于 `.env` 文件加载）：
```python
env = os.environ.copy()
env["TENCENT_SECRET_ID"] = config["tencent_secret_id"]
env["TENCENT_SECRET_KEY"] = config["tencent_secret_key"]
subprocess.run([sys.executable, TTS_SCRIPT, "--text", text, "--output", output_path], env=env)
```

### 图片/风格相关

**Q7：AI 生成图片背景色与引擎画布背景色（`#F6F1E3`）不完全匹配，导致上色阶段边缘色差。**
解决：`generate_animations.py` 预处理阶段将近白色/米白背景像素统一替换为精确的 `#F6F1E3`：
```python
img = cv2.imread(image_path)
mask = cv2.inRange(img, (200, 210, 220), (255, 255, 255))
img[mask > 0] = np.array([227, 241, 246], dtype=np.uint8)  # BGR of #F6F1E3
```

**Q8：跨场景 AI 生成图片风格不一致（线条粗细、构图、人物比例微妙差异）。**
解决（三层）：(a) prompt 末尾注入 "Keep the whole series visually consistent"；(b) `prompts.md` 提供各工具的风格参考图操作指引（如上传前序场景图作为参考）；(c) `validate_images.py` 用直方图相似度检测跨场景色调偏差，超出阈值时警告用户。

**Q9：自动区域检测（`detect_regions.py`）结果不准确。**
解决：检测结果仅作辅助建议，输出 `regions_preview.png` 供人工审阅确认，用户可在 `storyboard.json` 中直接覆盖 `bbox`。检测算法建议留 10-20px 边距，cell 归属按中心点判断避免边界切割不完整。

### 依赖相关

**Q10：`reorder_nearest_neighbor` 依赖 `scipy.spatial.KDTree`。**
解决：`requirements.txt` 包含 `scipy`（当前项目 `generate_default_sfx.py` 的滤波处理已需要该依赖，无新增负担）；缺失时路径连续性检查自动降级为跳过重排（打印警告）。

**Q11：Remotion `<Video>` 时长需与 `Sequence.durationInFrames` 匹配，否则截断或冻结帧。**
解决：`compute_timeline.py` 用 `ffprobe` 读取每个动画 MP4 的实际时长，以此为准计算 `durationFrames`（而非预估的 TTS/narration 时长）。`package.json` 引入 `@remotion/media-utils`。

---

## 验证方法

### 视觉真实感专项

1. **镜头过渡无空白暴露**：渲染 3 元素场景，逐帧检查元素间过渡；dip 过渡不应出现空白画布区域；breathe 过渡应看到已绘制内容作为上下文。
2. **视觉状态一致性**：sketch-first 模式下，Pass 1 结束时所有元素应为统一的黑白线稿状态；Pass 2 进行中已上色元素旁边应是线稿而非空白。
3. **笔刷尺寸恒定**：在不同缩放级别下截取 colorize 帧，测量屏幕上笔刷直径应恒定在 ~50px ±10px。
4. **路径连续性**：打印每个元素的 `avg_step` 值，正常应 < 3.0；构造一个元素间距不足的测试图片，验证 `reorder_nearest_neighbor` 被触发且绘制路径无明显跳跃。
5. **Ken Burns hold**：最终 hold 阶段应有极轻微缩放动效，肉眼几乎不可察觉但画面非完全静止。
6. **手部尺寸恒定**：不同缩放级别下手部在屏幕上的尺寸应大致相同（~250px 高 ±30%）。
7. **阶段过渡区分度**：sketch→colorize 的过渡应比元素间过渡更长（~1.5x transitionMs），给观众明确的"阶段切换"感知。

### 功能性验证

8. **统一路径**：无 `elements` 场景自动转全画布单元素，行为与显式单元素场景一致。
9. **音效同步**：Remotion Studio 预览中，sketch 阶段有笔触声，colorize 阶段有马克笔声，镜头过渡期间静音，音效切换无硬切。
10. **文字动画**：中英混排间距自然，手部跟随位置正确，写完后 5 帧淡出。
11. **SRT 校验**：字幕时间戳连续无间隙，文本内容与 `narration` 字段一致，时序对齐 sketch 阶段。
12. **Prompt 校验**：多元素场景生成的 `prompts.md` 包含明确的空间分离引导文字。
13. **区域检测校验**：`regions_preview.png` 清晰标注检测到的区域，`bbox` 覆盖主要元素轮廓，小噪声区域被过滤。
14. **端到端**：3 场景（2 个多元素 + 1 个无 elements 自动转单元素）分别跑 `video_first` 和 `full` 模式，人工审看成片。

---

## 成本分析

### 单次 3 场景视频（~30 秒成片）

| 步骤 | 成本 |
|------|------|
| 图片生成 | $0（用户自行选择文生图工具） |
| 区域检测 | $0（本地 OpenCV） |
| 合成音效生成 | $0（本地 numpy + pydub） |
| 镜头驱动手绘动画 | $0（本地 OpenCV，单场景 ~25-35s 渲染） |
| TTS（mode=full） | ~$0.003 |
| Remotion 渲染 | $0 |
| **合计（video_first）** | **$0** |
| **合计（full）** | **~$0.003** |

### 10 场景 3 分钟知识讲解视频

| 模式 | 成本 | 渲染耗时估算 |
|------|------|------------|
| video_first | $0 | ~5-6 分钟（10 场景手绘动画） |
| full | ~$0.01 | ~6-7 分钟（+ TTS + 混音） |

---

## 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 用户图片元素间缺少空白分隔 | 中 | 高 | prompt 空间引导 + 区域检测预览让用户确认 |
| 自动区域检测不准确 | 中 | 低 | 仅作建议，用户可在 storyboard.json 中手动调整 bbox |
| bbox 切割不完整 | 中 | 中 | 提示留边距 + cell 中心点判断归属 |
| 跨场景风格不一致 | 中 | 中 | 三层参考链（prompt 指令 + 操作指引 + 直方图校验） |
| 镜头缩放画面模糊 | 低 | 中 | max_dim=1920 + LANCZOS4 插值 + maxZoom 上限 2.5 |
| 画手缩放后手指细节丢失 | 低 | 低 | 可接受——观众关注绘制内容而非手部细节 |
| dip/breathe 过渡不自然 | 低 | 中 | 分阶段缓动（ease-in/ease-out）+ 距离阈值自适应选择策略 |
| sketch-first 节奏偏慢 | 中 | 中 | 可缩短 transitionMs；元素少的场景影响很小；用户可切换 sequential |
| dip 过渡过于频繁显得"闪烁" | 低 | 中 | 元素数量少时不明显；元素多时可缩短单次 dip 时长 |
| TTS 静音检测切割不精确 | 中 | 中 | 标点位置辅助对齐 + 允许手动覆盖 drawAt |
| 合成音效不够真实 | 中 | 低 | 用户可替换为 Freesound CC0 等真实音效素材 |
| 20,736 cells 渲染较慢 | 低 | 低 | 单场景 ~25-35s，离线管线可接受 |
| colorize float32 dtype 遗漏转换导致异常 | 低 | 高 | 每次 colorize 后显式 uint8 转换（约束清单第 20 条） |
| 路径重排破坏引擎原始遍历策略 | 低 | 低 | 保守阈值 3.0，仅在检测到明显跳跃时触发 |

---


## 实施步骤

一次性交付完整版本，按依赖顺序实施。

### Phase 0：环境准备

1. 更新 `requirements.txt`：新增 `opencv-python`、`numpy`、`av`、`scipy`（当前仅有 pydub/edge-tts/tencentcloud-sdk/python-dotenv）
2. 确认 `whiteboard-video-workflow/whiteboard-animation/scripts/setup_env.py` 已执行，`opencv-python`/`numpy`/`av` 在目标 Python 环境可用
3. 确认 `ffmpeg` / `ffprobe` 已安装
4. `remotion-project` 已完成 `npm install`（当前已就绪）

### Phase 1：Python 管线脚本

1. `scripts/validate.py` — 环境检查 + storyboard schema 校验
2. `scripts/parse_storyboard.py` — 脚本解析（含无 elements 自动生成全画布单元素）
3. `scripts/generate_prompts.py` — 生成 prompt（含空间分离引导 + 风格一致性指引）
4. `scripts/validate_images.py` — 图片校验（齐全性/尺寸/背景色/直方图一致性）
5. `scripts/detect_regions.py` — 自动区域检测 + preview 生成
6. `scripts/generate_scene_animation.py` — **核心文件**：`CameraVideoWriter`、`choose_transition_strategy`、`write_breathe_transition`/`write_dip_transition`、`compute_breathe_viewport`、`compute_adjusted_brush_radius`、`ensure_path_coherence`/`check_path_coherence`/`reorder_nearest_neighbor`、`load_hand_once`/`scale_hand_for_zoom`、`write_hold_with_ken_burns`、`generate_scene_with_regions` 主函数
7. `scripts/generate_animations.py` — 批量调用（统一走 `generate_scene_animation`）
8. `scripts/generate_default_sfx.py` — 程序化合成音效生成
9. `scripts/tts_pipeline.py` — 整段 TTS + 静音检测切割
10. `scripts/compute_timeline.py` — `drawAt` 自动编排 + per-element 四段帧号 + 场景时长估算
11. `scripts/generate_subtitles.py` — 生成 SRT（对齐 sketch 阶段）
12. `scripts/audio_mixer.py` — 三层混音
13. `scripts/deploy_resources.py` — 资源部署到 `remotion-project/public/`
14. `scripts/generate_publish.py` — 发布文案
15. `scripts/make_video.py` — 总编排（含断点续跑）

### Phase 2：Remotion 合成

1. `src/types.ts`（含 scene-relative 帧号标注）
2. `src/WhiteboardVideo.tsx`（`Grid` + `Video` + `Subtitle` + `DrawingSFX` + `HandwrittenText` + `TextOverlay` + `ProgressBar`）
3. `src/index.tsx`（`registerRoot`，Composition id 固定为 `VideoMain`）
4. 复制 `bgm.mp3` + 生成 `writing-hand-small.png`（从 `drawing-hand.png` 缩放）
5. `npx remotion studio` 逐组件预览调试
