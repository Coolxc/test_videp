# 0708 重构方案：SVG 路径动画引擎

## 一句话目标

用 SVG 路径动画替代 10px 网格逐格揭示，让白板手绘视频真正呈现"线条从笔尖生长"的效果。

---

## 为什么要换引擎

### 当前引擎的天花板

当前引擎（`generate_whiteboard.py`）的核心机制：

```
PNG → 灰度 → adaptiveThreshold 二值化 → 切成 10×10px 网格 → 按遍历顺序逐格揭示
```

这本质上是**刮刮乐**，不是**画画**。无论上层怎么包装（缩放、过渡、画手叠加），观众看到的始终是"图片在一块块出现"，不是"笔尖在画线"。

YouTube 上所有专业白板视频工具（VideoScribe、Doodly、Explaindio）使用的都是 **SVG 路径动画**：

```
SVG path → stroke-dasharray = pathLength → animate stroke-dashoffset from pathLength to 0
```

效果：线条从起点向终点连续"生长"，笔尖始终在线条最前端。

### 为什么现在是切换的最佳时机

1. **iPad 简笔画风格**（已确认）= 简单黑色线条在白底上 = 矢量化效果最佳的图片类型
2. **去掉缩放**（已确认）= 全画布视角下网格揭示的机械感完全暴露，SVG 动画不依赖缩放即可好看
3. 引擎的约束"不修改 generate_whiteboard.py"变得无关紧要——我们不再使用它

---

## 架构对比

```
当前架构：
  PNG 图片
    → Python: OpenCV 灰度+二值化+10px网格+逐格揭示+画手叠加 → 输出 60fps MP4
    → Remotion: <Video src="scene_final.mp4"> 嵌入预渲染视频
  
  依赖链: generate_whiteboard.py → generate_scene_animation.py → generate_animations.py
         → CameraVideoWriter → dip/breathe 过渡 → alpha blend → Ken Burns hold
         → 60fps→30fps 转换 → ffprobe 校正

新架构：
  PNG 图片
    → Python: vtracer 矢量化 → SVG paths + 元素分组 + 绘制排序 → 输出 paths.json
    → Remotion: <SVGDrawAnimation> 用 stroke-dashoffset 逐路径动画 + 画手跟随
  
  依赖链: vectorize_images.py → deploy_resources.py → Remotion SVG 渲染
```

**移除的复杂度**：
- CameraVideoWriter / viewport / zoom 系统
- dip / breathe 过渡
- alpha blend 结束过渡（"展示整图"问题的根因）
- Ken Burns hold
- 60fps → 30fps 帧率转换
- ffprobe 时长校正
- sketch_first 双程绘制（sketch/colorize 拆分）
- 笔刷半径自适应
- 画手多尺寸缓存
- 路径连续性修复（reorder_nearest_neighbor）

**新增的模块**：
- `scripts/vectorize_images.py` — PNG → SVG 矢量化 + 路径分组排序
- `remotion-project/src/SVGDrawAnimation.tsx` — SVG 路径动画渲染
- `remotion-project/src/PaperPullTransition.tsx` — 手拉新纸转场

---

## 实施方案

### Phase 1：矢量化管线（Python 侧）

#### 1-1. 新增 `scripts/vectorize_images.py`

核心职责：将每个场景的 PNG 图片转为可动画的 SVG 路径数据。

```python
"""
vectorize_images.py - PNG → SVG 矢量化 + 路径分组排序

输入: images/{scene_id}.png + storyboard.json (elements/bbox)
输出: svg_data/{scene_id}.json (paths + metadata)
"""

import vtracer  # pip install vtracer
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def vectorize_scene(image_path: str, elements: list[dict], scene_id: str) -> dict:
    """
    将一张场景图片矢量化并按元素分组。
    
    Returns:
        {
            "sceneId": "scene1",
            "viewBox": "0 0 1920 1080",
            "elements": [
                {
                    "id": "person",
                    "paths": [
                        {
                            "d": "M100,200 C150,180 ...",
                            "stroke": "#000000",
                            "strokeWidth": 2.5,
                            "fill": "none",
                            "length": 342.5,   # 路径总长度（用于 dashoffset 计算）
                            "bbox": {"x":..., "y":..., "w":..., "h":...},
                            "type": "stroke"    # "stroke" | "fill"
                        },
                        ...
                    ],
                    "totalLength": 1234.5,
                    "narration": "还在单纯靠出卖劳动时间，"
                },
                ...
            ],
            "unassignedPaths": [...]  # 不属于任何元素 bbox 的路径
        }
    """
```

**矢量化参数（针对 iPad 简笔画优化）**：

```python
VTRACER_PARAMS = {
    "colormode": "binary",       # 黑白模式，最适合线条画
    "filter_speckle": 8,         # 过滤 < 8px 的噪点
    "mode": "spline",            # 输出贝塞尔曲线（而非折线），线条更平滑
    "corner_threshold": 45,      # 拐角检测角度阈值
    "length_threshold": 5.0,     # 路径简化阈值，值越大路径越简化
    "splice_threshold": 60,      # 路径拼接角度阈值
    "path_precision": 3,         # SVG 坐标精度（小数位数），控制文件大小
}
```

**路径分组逻辑**：

```python
def assign_paths_to_elements(svg_paths: list[dict], elements: list[dict]) -> dict:
    """
    将 SVG 路径按 bbox 归属到对应元素。
    
    归属规则：路径 bbox 中心点落在哪个 element 的 bbox 内，就归属于该 element。
    不在任何 bbox 内的路径归入 unassignedPaths。
    """

def order_paths_within_element(paths: list[dict]) -> list[dict]:
    """
    元素内路径排序——模拟人类绘画顺序。
    
    策略：
    1. 按路径 bbox 的左上角坐标排序（y 优先，x 次之）
    2. 对相邻路径做 nearest-neighbor 优化（避免笔跳跃太远）
    3. 长路径优先（主要轮廓先画，细节后画）
    """
```

**闭合路径 → 描边路径转换**：

vtracer 输出的是闭合填充路径。对于线条画，需要转换处理：

```python
def classify_path(path_d: str, bbox: dict) -> str:
    """
    判断路径类型：
    - 细长路径（宽高比 > 3 或面积 < 阈值）→ "stroke"：保留为描边，用 dashoffset 动画
    - 宽大路径（面积大、宽高比接近 1）→ "fill"：保留为填充，用渐显动画
    """
    area = bbox["w"] * bbox["h"]
    aspect = max(bbox["w"], bbox["h"]) / max(1, min(bbox["w"], bbox["h"]))
    
    if aspect > 3.0 or area < 500:  # 细长或小面积 → 当作笔画
        return "stroke"
    return "fill"
```

对于 `type="stroke"` 的路径：
- 提取路径中心线（闭合路径取中线，或直接用原路径作为 stroke 路径）
- 设置 `fill="none"`, `stroke="#000"`, `strokeWidth` 由原路径宽度决定

对于 `type="fill"` 的路径：
- 保留原始填充
- 动画方式改为：先用 stroke-dashoffset 描绘轮廓，然后 fade-in 填充

#### 1-2. 修改 `scripts/config.py`

```python
# 背景色统一为纯白
BACKGROUND_HEX = "#FFFFFF"
BACKGROUND_BGR = (255, 255, 255)
BACKGROUND_RGB = (255, 255, 255)

# 新增 vtracer 配置
VTRACER_PARAMS = {
    "colormode": "binary",
    "filter_speckle": 8,
    "mode": "spline",
    "corner_threshold": 45,
    "length_threshold": 5.0,
    "splice_threshold": 60,
    "path_precision": 3,
}
```

#### 1-3. 修改 `scripts/generate_prompts.py`

**删除** `REFINED_ILLUSTRATION_TEMPLATE` 和对应的 LLM system prompt。

**新增** iPad 手绘简笔画模板：

```python
IPAD_SKETCH_TEMPLATE = {
    "prefix": (
        "Simple hand-drawn sketch on pure white background, "
        "loose organic black ink strokes like iPad Procreate freehand drawing, "
        "varying line weight with natural pressure sensitivity, "
        "simple cartoon or stick-figure style, "
        "minimal detail, bold confident strokes, "
    ),
    "suffix": (
        "Absolutely no text, no letters, no numbers, no typography. "
        "Pure white background #FFFFFF, no grid, no texture, no gradients. "
        "Simple artistic sketch, not precise or mechanical. "
        "Lines should feel alive and hand-drawn with slight imperfections. "
        "Clear black outlines, minimal or no color fills. "
        "Elements well-separated with generous blank space between them. "
        "16:9 aspect ratio, balanced composition."
    ),
    "negative": (
        "text, words, letters, numbers, realistic photo, 3D render, "
        "vector art, precise geometric shapes, mechanical lines, "
        "gradient background, colored background, texture, "
        "complex shading, photorealistic, printed look, "
        "detailed illustration, fine detail, intricate patterns"
    ),
}
```

**LLM System Prompt** 改为：

```
你是一位 iPad 手绘简笔画风格的 prompt 工程师。

【画风规则】
1. 像用 Apple Pencil 在 Procreate 上随手画的简笔画
2. 纯黑色线条为主，线宽有自然的压感粗细变化（1-4px）
3. 线条松散有机，有手绘的自然抖动，不死板不机械
4. 每个元素用最少的笔画表达（5-15 笔），追求神韵不追求精确
5. 纯白背景 #FFFFFF，绝对不加任何背景色/纹理/网格
6. 绝对不出现任何文字

【技术约束 — 矢量化兼容】
- 图片会经过矢量化（PNG → SVG）处理
- 因此：线条必须与白色背景有强烈黑白对比
- 避免：灰色渐变、半透明、毛笔飞白效果（矢量化后会变成碎片）
- 推荐：用清晰的实线，粗细变化可以有但别太极端

【构图约束】
- 16:9 横版
- 元素间留足空白（至少 15% 画布宽度间隔）
- 每个元素是一个视觉上独立的"岛"
```

#### 1-4. 修改 `scripts/compute_timeline.py`

**大幅简化**：不再有 sketch/colorize 双阶段，不再有 60fps → 30fps 转换。

```python
FRAME_RATE = 30  # 直接 30fps，与 Remotion 一致

def compute_timeline_entry(scene, scene_start_frame, ..., fps=30):
    """
    每个元素只有一组时间：drawAtFrame + drawDurationFrames
    不再区分 sketch/colorize。
    """
    elements_timeline = []
    current_frame = 0
    
    for elem in elem_durations:
        elements_timeline.append({
            "id": elem["id"],
            "drawAtFrame": current_frame,              # 场景内相对帧
            "drawDurationFrames": elem_frames,          # 绘制持续帧数
            "narration": elem["narration"],
        })
        current_frame += elem_frames + pause_frames     # 元素间停顿
    
    return {
        "id": scene["id"],
        "startFrame": scene_start_frame,
        "durationFrames": current_frame + hold_frames,
        "elements": elements_timeline,
    }
```

新增字段：
```json
{
    "transitionDurationFrames": 25,
    "drawMode": "sequential"
}
```

#### 1-5. 修改 `scripts/deploy_resources.py`

**替换**：不再复制 animation MP4，改为复制 SVG 路径数据。

```python
# 旧：复制 animations/{scene_id}_final.mp4 → public/animations/
# 新：复制 svg_data/{scene_id}.json → public/svg-data/

def deploy_resources(...):
    # SVG 路径数据
    svg_src = Path(output_dir) / "svg_data"
    svg_dst = remotion_public / "svg-data"
    os.makedirs(svg_dst, exist_ok=True)
    for f in svg_src.glob("*.json"):
        shutil.copy2(f, svg_dst / f.name)
```

#### 1-6. 修改 `scripts/make_video.py`

管线步骤变化：

```
Step 0:  validate（移除 ffmpeg/ffprobe 依赖检查，新增 vtracer 检查）
Step 1:  parse_storyboard（不变）
Step 2:  generate_prompts（用 iPad 简笔画模板）
         ⏸ 用户生图
Step 3:  validate_images（背景色目标改为纯白）
Step 5:  tts_pipeline（不变，仅 mode=full）
Step 6:  compute_timeline（简化版，30fps 直出）
Step 7:  generate_default_sfx（不变）
Step 8:  vectorize_images  ← 【替换 generate_animations】
Step 9:  generate_subtitles（不再需要 ffprobe 校正）
Step 10: audio_mixer（不变，仅 mode=full）
Step 11: deploy_resources → remotion render
Step 12: generate_publish（不变）
```

**删除的步骤**：
- Step 4（detect_regions）— 不再需要自动区域检测，bbox 由 storyboard 定义
- Step 9 的 ffprobe 校正 — 不再有预渲染视频

---

### Phase 2：Remotion 渲染层

#### 2-1. 新增 `@remotion/paths` 依赖

```bash
cd remotion-project && npm install @remotion/paths
```

`@remotion/paths` 提供：
- `getLength(d)` — 计算 SVG path 总长度
- `getPointAtLength(d, length)` — 获取路径上指定长度处的坐标
- `evolvePath(progress, d)` — 返回 `strokeDasharray` 和 `strokeDashoffset` 值

#### 2-2. 新增 `remotion-project/src/SVGDrawAnimation.tsx`

核心渲染组件，替代原来的 `<Video>` 嵌入。

```tsx
interface PathData {
  d: string;           // SVG path data
  stroke: string;      // 描边颜色
  strokeWidth: number;
  fill: string;        // "none" 或颜色
  length: number;      // 路径总长度
  type: "stroke" | "fill";
}

interface ElementPaths {
  id: string;
  paths: PathData[];
  totalLength: number;
  narration: string;
}

interface SVGDrawAnimationProps {
  elements: ElementPaths[];
  drawAtFrames: number[];     // 每个元素的起始帧（场景内相对）
  drawDurations: number[];    // 每个元素的绘制帧数
  viewBox: string;
  showHand: boolean;
}
```

**动画逻辑**：

```tsx
const SVGDrawAnimation: React.FC<SVGDrawAnimationProps> = ({
  elements, drawAtFrames, drawDurations, viewBox, showHand
}) => {
  const frame = useCurrentFrame();
  
  return (
    <AbsoluteFill>
      <svg viewBox={viewBox} style={{ width: "100%", height: "100%" }}>
        {elements.map((element, elemIdx) => {
          const elemStart = drawAtFrames[elemIdx];
          const elemDuration = drawDurations[elemIdx];
          const elemEnd = elemStart + elemDuration;
          
          // 在当前元素的时间范围内，计算每个 path 的进度
          return element.paths.map((path, pathIdx) => {
            // 按路径在元素内的顺序分配时间
            const pathStart = elemStart + (pathIdx / element.paths.length) * elemDuration;
            const pathDuration = elemDuration / element.paths.length;
            const pathProgress = clamp((frame - pathStart) / pathDuration, 0, 1);
            
            if (pathProgress <= 0) return null;  // 尚未开始
            
            if (path.type === "stroke") {
              // stroke-dashoffset 动画：线条从起点生长到终点
              const dashOffset = path.length * (1 - pathProgress);
              return (
                <path
                  key={`${elemIdx}-${pathIdx}`}
                  d={path.d}
                  stroke={path.stroke}
                  strokeWidth={path.strokeWidth}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                  strokeDasharray={path.length}
                  strokeDashoffset={dashOffset}
                />
              );
            } else {
              // fill 类型：先描轮廓（前 60%），再淡入填充（后 40%）
              const outlineProgress = clamp(pathProgress / 0.6, 0, 1);
              const fillProgress = clamp((pathProgress - 0.6) / 0.4, 0, 1);
              return (
                <g key={`${elemIdx}-${pathIdx}`}>
                  <path
                    d={path.d}
                    stroke={path.stroke || "#000"}
                    strokeWidth={2}
                    fill="none"
                    strokeDasharray={path.length}
                    strokeDashoffset={path.length * (1 - outlineProgress)}
                  />
                  <path
                    d={path.d}
                    fill={path.fill}
                    stroke="none"
                    opacity={fillProgress}
                  />
                </g>
              );
            }
          });
        })}
      </svg>
      
      {/* 画手跟随当前绘制位置 */}
      {showHand && <DrawingHand elements={elements} frame={frame} ... />}
    </AbsoluteFill>
  );
};
```

**画手跟随逻辑**：

```tsx
const DrawingHand: React.FC<{...}> = ({ elements, frame, drawAtFrames, drawDurations }) => {
  // 找到当前正在绘制的路径
  const currentPath = findCurrentPath(elements, frame, drawAtFrames, drawDurations);
  if (!currentPath) return null;
  
  // 用 @remotion/paths 获取当前点坐标
  const { d, progress } = currentPath;
  const length = getLength(d);
  const point = getPointAtLength(d, length * progress);
  
  return (
    <Img
      src={staticFile("assets/writing-hand-small.png")}
      style={{
        position: "absolute",
        left: point.x - 10,   // 笔尖偏移
        top: point.y - 30,
        width: 120,
        height: 120,
        transformOrigin: "10px 30px",
        transform: `rotate(${computeAngle(d, progress)}deg)`,  // 手随路径方向旋转
        zIndex: 100,
      }}
    />
  );
};
```

画手的关键改进：
- **笔尖精确定位**：`getPointAtLength` 给出亚像素级坐标，笔尖始终在线条末端
- **手随路径旋转**：根据路径在当前点的切线方向旋转画手角度，像真人运笔
- **元素间抬手**：两个元素之间的停顿帧内，画手不显示（模拟画师抬手移位）

#### 2-3. 新增 `remotion-project/src/PaperPullTransition.tsx`

场景间转场：白纸从上方滑入覆盖旧画面。

```tsx
const TRANSITION_FRAMES = 25;  // ~0.83s @30fps

interface PaperPullTransitionProps {
  startFrame: number;     // 转场开始帧（场景内相对帧）
  durationFrames: number; // 转场持续帧数
}

const PaperPullTransition: React.FC<PaperPullTransitionProps> = ({
  startFrame, durationFrames
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  const progress = clamp((frame - startFrame) / durationFrames, 0, 1);
  if (progress <= 0) return null;
  
  // 白纸从 y=-1080 滑到 y=0，使用 spring 缓动
  const paperY = interpolate(
    spring({ frame: Math.max(0, frame - startFrame), fps, config: { damping: 28, stiffness: 120 } }),
    [0, 1],
    [-1080, 0]
  );
  
  return (
    <AbsoluteFill style={{ zIndex: 50 }}>
      {/* 白纸 */}
      <div style={{
        position: "absolute",
        left: 0,
        top: paperY,
        width: 1920,
        height: 1080,
        backgroundColor: "#FFFFFF",
        boxShadow: "0 4px 20px rgba(0,0,0,0.15)",  // 纸张底边阴影
      }} />
      
      {/* 纸张底边的轻微弧度（可选，增加真实感） */}
      <div style={{
        position: "absolute",
        left: 0,
        top: paperY + 1080,
        width: 1920,
        height: 8,
        background: "linear-gradient(to bottom, rgba(0,0,0,0.08), transparent)",
      }} />
    </AbsoluteFill>
  );
};
```

注意：经过 red team 分析，**不使用 drawing-hand.png 做拉纸**（握笔姿势拉纸不自然）。改为纯白纸滑入 + 底边阴影，视觉效果更干净。如果后续需要手，应使用专门的拉纸手势素材。

#### 2-4. 修改 `remotion-project/src/WhiteboardVideo.tsx`

**主要变化**：

```tsx
// 旧：嵌入预渲染 MP4
<Video src={staticFile(`animations/${scene.id}_final.mp4`)} />

// 新：SVG 路径动画
<SVGDrawAnimation
  elements={svgData.elements}
  drawAtFrames={tScene.elements.map(e => e.drawAtFrame)}
  drawDurations={tScene.elements.map(e => e.drawDurationFrames)}
  viewBox={svgData.viewBox}
  showHand={true}
/>
```

**背景色改为纯白**：

```tsx
const C = {
  bg: "#FFFFFF",
  grid: "#F5F5F5",   // 极淡灰，几乎不可见
  // ...
};
```

**Grid 改为更淡或移除**：

纯白纸上不应有明显的格线。改为极淡的点阵或完全移除：

```tsx
const Grid: React.FC = () => {
  // 选项 A：极淡点阵（模拟微弱纸纹）
  // 选项 B：直接返回 null（纯白纸）
  return null;
};
```

**场景渲染加入转场**：

```tsx
{timeline.scenes.map((tScene, i) => {
  const isLast = i === timeline.scenes.length - 1;
  const transitionFrames = timeline.transitionDurationFrames || 25;
  
  return (
    <Sequence key={tScene.id} from={tScene.startFrame} durationInFrames={tScene.durationFrames}>
      <AbsoluteFill style={{ backgroundColor: C.bg }}>
        {/* SVG 绘制动画 */}
        <SVGDrawAnimation ... />
        
        {/* 字幕 */}
        <Subtitle ... />
        
        {/* 绘画音效（简化为单层，不区分 sketch/colorize）*/}
        <DrawingSFX elements={tScene.elements} />
        
        {/* 转场：当前场景末尾，新白纸从上方滑入 */}
        {!isLast && (
          <PaperPullTransition
            startFrame={tScene.durationFrames - transitionFrames}
            durationFrames={transitionFrames}
          />
        )}
        
        {/* 进度条 */}
        <ProgressBar current={i + 1} total={timeline.scenes.length} />
      </AbsoluteFill>
    </Sequence>
  );
})}
```

#### 2-5. 修改 `remotion-project/src/types.ts`

```typescript
// 新增 SVG 路径数据类型
export interface SVGPathData {
  d: string;
  stroke: string;
  strokeWidth: number;
  fill: string;
  length: number;
  type: "stroke" | "fill";
}

export interface SVGElementData {
  id: string;
  paths: SVGPathData[];
  totalLength: number;
  narration: string;
}

export interface SVGSceneData {
  sceneId: string;
  viewBox: string;
  elements: SVGElementData[];
  unassignedPaths: SVGPathData[];
}

// 简化 ElementTimeline（不再区分 sketch/colorize）
export interface ElementTimeline {
  id: string;
  drawAtFrame: number;        // 场景内相对帧
  drawDurationFrames: number;
  narration: string;
}

// Timeline 新增转场帧数
export interface Timeline {
  fps: number;
  totalFrames: number;
  transitionDurationFrames: number;
  drawMode: "sequential";
  scenes: SceneTimeline[];
}
```

#### 2-6. 修改 `remotion-project/src/index.tsx`

```tsx
// 新增 SVG 数据导入方式
// SVG 数据通过 staticFile 在运行时加载，或预编译到 src/ 目录

// 如果 SVG 数据量不大（每个场景 < 500KB），可以作为 JSON import：
import svgDataScene1 from "../public/svg-data/scene1.json";
// 但这样不灵活——场景数不固定

// 更好的方式：在 WhiteboardVideo.tsx 中用 fetch 动态加载
// 或在 deploy_resources.py 中生成一个 all-svg-data.json 汇总文件
```

推荐：`deploy_resources.py` 将所有场景的 SVG 数据合并为一个 `svg-data.json`，复制到 `src/`，在 index.tsx 中 import。

#### 2-7. DrawingSFX 简化

不再区分 sketch/colorize 两层音效，改为单层绘画音效：

```tsx
const DrawingSFX: React.FC<{ elements: ElementTimeline[] }> = ({ elements }) => (
  <>
    {elements.map((elem) => (
      <Sequence key={elem.id} from={elem.drawAtFrame} durationInFrames={elem.drawDurationFrames}>
        <Audio
          src={staticFile("assets/sfx/pen_sketch.mp3")}
          loop
          volume={(f) => {
            const dur = elem.drawDurationFrames;
            if (dur <= 0) return 0;
            const fadeIn = interpolate(f, [0, 5], [0, 0.12], { extrapolateRight: "clamp" });
            const fadeOut = interpolate(f, [dur - 5, dur], [0.12, 0], { extrapolateLeft: "clamp" });
            return Math.min(fadeIn, fadeOut);
          }}
        />
      </Sequence>
    ))}
  </>
);
```

---

### Phase 3：背景色与配套修改

#### 3-1. `scripts/validate_images.py`

`fix_background_color` 目标色改为纯白：
```python
def fix_background_color(images_dir, target_bgr=(255, 255, 255), tolerance=30):
```

#### 3-2. `scripts/parse_storyboard.py`

默认值更新：
```python
meta.setdefault("style", "ipad_sketch")
meta.setdefault("imageStyle", "ipad_sketch")
```

---

## 文件改动清单

### 新增文件

| 文件 | 职责 |
|------|------|
| `scripts/vectorize_images.py` | PNG → SVG 矢量化 + 路径分组排序 |
| `remotion-project/src/SVGDrawAnimation.tsx` | SVG stroke-dashoffset 路径动画渲染 |
| `remotion-project/src/PaperPullTransition.tsx` | 手拉新纸场景转场 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `scripts/config.py` | 背景色 → #FFFFFF，新增 VTRACER_PARAMS |
| `scripts/generate_prompts.py` | Prompt 模板 → iPad 简笔画，LLM system prompt 更新 |
| `scripts/compute_timeline.py` | 简化为 30fps 直出，去掉 sketch/colorize 双阶段 |
| `scripts/deploy_resources.py` | 部署 SVG 数据替代 MP4 动画 |
| `scripts/make_video.py` | Step 8 替换为 vectorize，移除 ffprobe 校正步骤 |
| `scripts/validate_images.py` | 背景色目标改为纯白 |
| `scripts/parse_storyboard.py` | 默认风格值更新 |
| `remotion-project/src/WhiteboardVideo.tsx` | SVGDrawAnimation 替代 Video，背景色，转场 |
| `remotion-project/src/types.ts` | 新增 SVG 类型，简化 ElementTimeline |
| `remotion-project/src/index.tsx` | SVG 数据导入方式 |
| `remotion-project/package.json` | 新增 @remotion/paths 依赖 |
| `requirements.txt`（如有） | 新增 vtracer |

### 可删除文件

| 文件 | 原因 |
|------|------|
| `scripts/generate_scene_animation.py` | 整个文件被 SVG 方案替代 |
| `scripts/generate_animations.py` | 被 vectorize_images.py 替代 |
| `scripts/detect_regions.py` | 不再需要自动区域检测 |

---

## 依赖变化

### Python 侧

```
# 新增
vtracer>=0.6.10        # PNG → SVG 矢量化

# 不再需要（可保留但非必需）
# opencv-python        # 仅 validate_images 的背景修复仍用
# scipy                # 不再需要 KDTree 路径重排
# av                   # 不再需要视频处理
```

注意：`opencv-python` 仍然被 `validate_images.py` 的背景色修复使用。如果后续将背景修复也移到 Pillow，可完全移除 OpenCV 依赖。

### Node 侧

```bash
npm install @remotion/paths
```

### 系统依赖

```
# 不再需要
# ffmpeg / ffprobe     # 不再有 MP4 预渲染和时长校正
```

ffmpeg 仅在最终 Remotion 渲染输出 MP4 时需要（Remotion 自带）。

---

## Timeline / Storyboard Schema 变化

### timeline.json 新格式

```json
{
  "fps": 30,
  "totalFrames": 450,
  "transitionDurationFrames": 25,
  "drawMode": "sequential",
  "scenes": [
    {
      "id": "scene1",
      "startFrame": 0,
      "durationFrames": 210,
      "elements": [
        {
          "id": "person",
          "drawAtFrame": 0,
          "drawDurationFrames": 90,
          "narration": "还在单纯靠出卖劳动时间，"
        },
        {
          "id": "clock",
          "drawAtFrame": 100,
          "drawDurationFrames": 75,
          "narration": "来换取那点微薄的工资吗？"
        }
      ]
    }
  ]
}
```

对比旧格式：
- 移除 `sketchAtFrame` / `sketchDurationFrames` / `colorizeAtFrame` / `colorizeDurationFrames`
- 合并为 `drawAtFrame` / `drawDurationFrames`
- 新增 `transitionDurationFrames`
- `drawMode` 固定为 `"sequential"`（SVG 方案下不需要 sketch_first）
- `frameReference` 字段移除（统一为 scene-relative，无歧义）

---

## 实施顺序

```
Week 1:
  Day 1-2: vectorize_images.py（vtracer 集成、路径分组、排序）
  Day 3:   config.py / generate_prompts.py / validate_images.py（背景色 + 风格）
  Day 4:   compute_timeline.py 简化

Week 2:
  Day 5-7: SVGDrawAnimation.tsx（核心 Remotion 组件 + 画手跟随）
  Day 8:   PaperPullTransition.tsx
  Day 9:   WhiteboardVideo.tsx 整合 + types.ts 更新

Week 3:
  Day 10:  deploy_resources.py + make_video.py 管线串联
  Day 11:  index.tsx + package.json 依赖
  Day 12-14: 端到端测试 + 调优（路径排序、动画速度、画手角度）
```

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| AI 生图线条太复杂，vtracer 输出几千个碎片 path | 中 | 高 | Prompt 强制极简；`filter_speckle` 调高过滤噪点；后处理合并相邻小 path |
| 闭合 path 的 stroke-dashoffset 动画视觉不自然 | 中 | 高 | 路径分类：细长→stroke 动画，宽大→轮廓+填充分离动画 |
| 路径排序不符合人类绘画直觉 | 中 | 中 | nearest-neighbor + 长路径优先；element 级已保证大方向正确 |
| vtracer Python binding 安装失败（Rust 编译） | 低 | 高 | PyPI 提供预编译 wheel；fallback: 调用 vtracer CLI |
| @remotion/paths 与 remotion 4.0.0 版本不兼容 | 低 | 高 | 检查版本兼容性；如不兼容则手动实现 getLength/getPointAtLength |
| SVG 路径数据量过大（单场景 > 1MB） | 低 | 中 | `path_precision=3` 控制精度；过滤无效 path；必要时压缩 |
| 画手角度计算在路径尖角处抖动 | 中 | 低 | 角度平滑（取前后 N 帧平均值）|

---

## 验证方法

### 核心视觉验证

1. **线条生长效果**：渲染一个单元素场景（如一个简笔画人物），逐帧检查线条是否从起点"连续生长"到终点，而非"逐块出现"
2. **笔尖定位精度**：画手的笔尖是否始终在当前绘制线条的最前端，误差 < 5px
3. **多元素顺序**：3 元素场景，确认按 element 顺序依次绘制，字幕同步正确
4. **fill 类型动画**：含有填充区域的元素，确认先描轮廓再淡入填充
5. **转场效果**：场景切换时白纸从上方平滑滑入，覆盖旧画面，无闪烁

### 管线验证

6. **vtracer 输出**：检查 `svg_data/{scene_id}.json` 的 path 数量和大小是否合理
7. **路径分组**：检查每个 element 的 paths 是否只包含其 bbox 内的内容
8. **timeline 一致性**：timeline.json 的帧数与 Remotion 渲染时长匹配
9. **端到端**：用现有 storyboard 跑完整管线，人工审看成片

### 对比验证

10. **与旧方案对比**：同一张图片分别用旧引擎和新 SVG 方案渲染，截图对比
11. **与 VideoScribe 对比**：找一个 VideoScribe 白板视频截图，对比线条动画的自然度

---

## 成本分析

### 单次 3 场景视频（~30 秒成片）

| 步骤 | 旧方案成本 | 新方案成本 |
|------|-----------|-----------|
| 图片生成 | $0 | $0 |
| 矢量化 | — | $0（本地 vtracer，< 1s/张） |
| 动画渲染 | ~25-35s/场景（Python+OpenCV） | 0（Remotion 直接渲染） |
| Remotion 渲染 | ~30s（嵌入视频） | ~20-40s（SVG 渲染，依赖路径复杂度） |
| **总渲染时间** | **~2-3 分钟** | **~1-2 分钟** |
| **API 成本** | $0 | $0 |

渲染时间可能持平或略快，因为省去了 Python 逐帧写像素 + ffmpeg 转码的开销。

---

## 补充：Grill 发现的缺失项

以下内容补全方案中经 red team 穿刺发现的所有空洞。

---

### 补充 1：SVG 路径长度计算——缺失依赖 `svgpathtools`

**问题**：`vectorize_images.py` 输出的每个 path 需要 `length` 字段（路径总长度），用于 Remotion 侧的 `strokeDasharray`/`strokeDashoffset` 计算。vtracer 的 `d` 属性是贝塞尔曲线字符串（`M`, `C`, `L`, `Q`, `Z` 等命令），精确长度需要数值积分。

**解决**：新增 Python 依赖 `svgpathtools`：

```bash
pip install svgpathtools
```

在 `vectorize_images.py` 中：

```python
from svgpathtools import parse_path

def compute_path_length(d: str) -> float:
    """计算 SVG path 'd' 属性的精确长度。"""
    try:
        path = parse_path(d)
        return path.length()
    except Exception:
        # 降级：用路径 bbox 对角线长度估算
        return 0.0

def compute_path_bbox(d: str) -> dict:
    """计算 SVG path 的精确 bounding box。"""
    try:
        path = parse_path(d)
        xmin, xmax, ymin, ymax = path.bbox()
        return {"x": xmin, "y": ymin, "w": xmax - xmin, "h": ymax - ymin}
    except Exception:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
```

**双重校验**：Remotion 侧的 `@remotion/paths` 也提供 `getLength(d)`。Python 侧计算 length 用于时间分配，Remotion 侧用于动画渲染。两者基于不同实现（Python 数值积分 vs 浏览器 SVG API），结果可能有微小差异（< 0.1%），对视觉效果无影响。

**完整依赖列表更新**：

```
# requirements.txt 新增
vtracer>=0.6.10
svgpathtools>=1.6.0
```

---

### 补充 2：Unassigned Paths 处理策略

**问题**：不在任何 element bbox 内的路径（元素间的连接线、装饰线条、背景图案）永远不会被绘制，导致最终画面残缺。

**解决**：三层策略。

#### 策略 A：就近归属（默认）

对每个 unassigned path，找距离最近的 element，归入该 element 的 paths 末尾（在该 element 的主要内容画完后补充绘制）。

```python
def assign_orphan_paths(orphan_paths: list[dict], elements: list[dict]) -> None:
    """将孤立路径归入距离最近的元素。"""
    for path in orphan_paths:
        path_cx = path["bbox"]["x"] + path["bbox"]["w"] / 2
        path_cy = path["bbox"]["y"] + path["bbox"]["h"] / 2
        
        min_dist = float("inf")
        nearest_elem = None
        for elem in elements:
            elem_cx = elem["bbox"]["x"] + elem["bbox"]["w"] / 2
            elem_cy = elem["bbox"]["y"] + elem["bbox"]["h"] / 2
            dist = ((path_cx - elem_cx) ** 2 + (path_cy - elem_cy) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_elem = elem
        
        if nearest_elem:
            nearest_elem["paths"].append(path)
```

#### 策略 B：扫尾阶段

在所有 element 画完后，追加一个虚拟 element `"_cleanup"` 包含所有 unassigned paths，用 2x 速度快速绘制。

```python
if unassigned_paths:
    elements.append({
        "id": "_cleanup",
        "paths": unassigned_paths,
        "totalLength": sum(p["length"] for p in unassigned_paths),
        "narration": "",
    })
```

Timeline 中 `_cleanup` 分配较短的绘制时间（比正常元素快 2x），不显示字幕。

#### 策略 C：扩大 bbox 覆盖

在路径分组前，将每个 element 的 bbox 扩大 15% padding（与旧方案的 `filter_draw_order_for_bbox` padding 思路一致），让更多路径被自然归属。

```python
def expand_bbox(bbox: dict, padding_ratio: float = 0.15) -> dict:
    pad_x = bbox["w"] * padding_ratio
    pad_y = bbox["h"] * padding_ratio
    return {
        "x": bbox["x"] - pad_x,
        "y": bbox["y"] - pad_y,
        "w": bbox["w"] + 2 * pad_x,
        "h": bbox["h"] + 2 * pad_y,
    }
```

**推荐组合**：先用策略 C 扩大 bbox → 再用策略 A 就近归属剩余 → 最终 unassigned 应为 0 或极少量噪点。

---

### 补充 3：坐标系映射（SVG viewBox → Remotion 画布 → 画手 CSS）

**问题**：AI 生图可能是任意尺寸（2048×1152、1024×1024 等）。vtracer SVG 使用原图像素坐标。Remotion 画布是 1920×1080。画手 PNG 用 CSS absolute 定位在 Remotion 画布上。

**解决**：三层坐标系统与映射规则。

```
Layer 1: SVG viewBox 坐标系（原图像素）
  - vtracer 输出的 path 'd' 值使用此坐标
  - viewBox="0 0 {imgWidth} {imgHeight}"
  - SVG 内部渲染自动按 viewBox 缩放到 <svg> 元素尺寸

Layer 2: Remotion 画布坐标系（1920×1080）
  - <svg> 元素: width="100%" height="100%" viewBox="0 0 {imgWidth} {imgHeight}"
  - 浏览器自动处理 viewBox → 元素尺寸的映射
  - objectFit 行为：SVG preserveAspectRatio="xMidYMid meet" (默认)

Layer 3: CSS 定位坐标系（画手 PNG）
  - getPointAtLength() 返回 viewBox 坐标
  - 需要手动转换到 CSS 坐标
```

**画手坐标转换实现**：

```tsx
const DrawingHand: React.FC<DrawingHandProps> = ({
  elements, frame, drawAtFrames, drawDurations, viewBox, showHand
}) => {
  const currentPath = findCurrentPath(elements, frame, drawAtFrames, drawDurations);
  if (!currentPath) return null;

  // viewBox 解析
  const [, , vbWidth, vbHeight] = viewBox.split(" ").map(Number);
  
  // SVG preserveAspectRatio="xMidYMid meet" 的行为：
  // 按短边等比缩放，居中对齐
  const canvasW = 1920;
  const canvasH = 1080;
  const scaleX = canvasW / vbWidth;
  const scaleY = canvasH / vbHeight;
  const scale = Math.min(scaleX, scaleY);  // meet = 按短边
  
  // 居中偏移
  const offsetX = (canvasW - vbWidth * scale) / 2;
  const offsetY = (canvasH - vbHeight * scale) / 2;
  
  // viewBox 坐标 → CSS 坐标
  const { d, progress } = currentPath;
  const length = getLength(d);
  const point = getPointAtLength(d, length * progress);
  
  const cssX = point.x * scale + offsetX;
  const cssY = point.y * scale + offsetY;
  
  return (
    <Img
      src={staticFile("assets/writing-hand-small.png")}
      style={{
        position: "absolute",
        left: cssX - 10,
        top: cssY - 30,
        width: 120,
        height: 120,
        zIndex: 100,
      }}
    />
  );
};
```

**统一图片尺寸建议**：为降低映射复杂度，`validate_images.py` 增加一步将所有图片 resize 到 1920×1080（或等比缩放到最长边 1920），使 viewBox 坐标直接对应 Remotion 画布。

```python
def normalize_image_size(image_path: str, target_w=1920, target_h=1080):
    """等比缩放图片到目标尺寸，白色 padding 填充。"""
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    
    canvas = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    y_off = (target_h - new_h) // 2
    x_off = (target_w - new_w) // 2
    canvas[y_off:y_off+new_h, x_off:x_off+new_w] = resized
    cv2.imwrite(image_path, canvas)
```

如果预处理统一为 1920×1080，则 viewBox = "0 0 1920 1080"，坐标转换简化为恒等映射。

---

### 补充 4：路径时间分配——按长度比例而非等分

**问题**：方案原始代码将绘制时间均分给每个 path。但路径长度差异巨大（主轮廓 500px vs 小装饰点 10px），等分导致主轮廓画太快、小点画太慢。

**解决**：按路径长度比例分配。

```tsx
// SVGDrawAnimation.tsx 内

// 预计算每个 path 的累计长度占比
const cumulativeLengths: number[] = [];
let cumLen = 0;
for (const path of element.paths) {
  cumulativeLengths.push(cumLen);
  cumLen += path.length;
}

// 每个 path 的起始帧和持续帧
element.paths.map((path, pathIdx) => {
  const pathStartRatio = cumulativeLengths[pathIdx] / element.totalLength;
  const pathLengthRatio = path.length / element.totalLength;
  
  const pathStart = elemStart + pathStartRatio * elemDuration;
  const pathDuration = Math.max(1, pathLengthRatio * elemDuration);
  const pathProgress = clamp((frame - pathStart) / pathDuration, 0, 1);
  // ...
});
```

**效果**：长路径（主轮廓、长线条）获得更多绘制时间 → 视觉上匀速描绘。短路径（小点、细节）快速闪过 → 自然的"收笔"感觉。

---

### 补充 5：compute_timeline.py 新时间分配公式

**问题**：方案只说"简化"但没给出具体公式。以下是完整的时间分配逻辑。

#### 常量定义

```python
FRAME_RATE = 30
ELEMENT_GAP_FRAMES = 10          # 元素间停顿（~0.33s），画手抬起移位
HOLD_FRAMES = 45                  # 场景末尾 hold 静态画面（~1.5s）
TRANSITION_FRAMES = 25            # 转场帧数（~0.83s），被下一场景的白纸覆盖
MIN_ELEMENT_DRAW_FRAMES = 30      # 单元素最小绘制帧数（~1.0s）
CHARS_PER_SECOND = 4.0            # 中文旁白语速
NARRATION_MARGIN = 1.2            # 旁白时长余量系数
```

#### 场景时长估算

```python
def estimate_scene_duration_frames(scene: dict) -> int:
    elements = scene.get("elements", [])
    n = max(1, len(elements))
    
    # 基于旁白的时长
    total_chars = sum(len(e.get("narration", "")) for e in elements)
    narration_frames = round(total_chars / CHARS_PER_SECOND * NARRATION_MARGIN * FRAME_RATE)
    
    # 基于元素数量的最小时长
    min_draw_frames = n * MIN_ELEMENT_DRAW_FRAMES
    
    # 取较大值
    draw_frames = max(min_draw_frames, narration_frames)
    
    # 加上间隙 + hold + 转场
    gap_frames = (n - 1) * ELEMENT_GAP_FRAMES
    total = draw_frames + gap_frames + HOLD_FRAMES + TRANSITION_FRAMES
    
    return max(total, FRAME_RATE * 5)  # 最短 5 秒
```

#### 元素时长分配

```python
def allocate_element_durations(elements: list[dict], total_draw_frames: int) -> list[int]:
    """按旁白字数比例分配绘制帧数。"""
    total_chars = sum(len(e.get("narration", "")) for e in elements) or len(elements)
    
    durations = []
    for elem in elements:
        chars = len(elem.get("narration", "")) or 1
        frames = max(MIN_ELEMENT_DRAW_FRAMES, round(total_draw_frames * chars / total_chars))
        durations.append(frames)
    
    return durations
```

#### 完整 timeline entry 计算

```python
def compute_timeline_entry(scene, scene_start_frame, fps=30):
    elements = scene.get("elements", [])
    n = len(elements)
    
    # 场景总帧数
    total_frames = estimate_scene_duration_frames(scene)
    
    # 可用于绘制的帧数（去掉间隙、hold、转场）
    gap_frames_total = (n - 1) * ELEMENT_GAP_FRAMES
    draw_budget = total_frames - gap_frames_total - HOLD_FRAMES - TRANSITION_FRAMES
    
    # 分配
    elem_draw_frames = allocate_element_durations(elements, draw_budget)
    
    # 编排时间轴
    timeline_elements = []
    current_frame = 0
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
    
    return {
        "id": scene["id"],
        "startFrame": scene_start_frame,
        "durationFrames": total_frames,
        "elements": timeline_elements,
    }
```

#### 场景之间的时间关系

```
Scene 1:  [绘制...][hold 45帧][转场 25帧]
Scene 2:                       [绘制...][hold 45帧][转场 25帧]
                               ↑ scene2.startFrame = scene1.startFrame + scene1.durationFrames - TRANSITION_FRAMES
```

场景之间 **重叠 TRANSITION_FRAMES 帧**：Scene 1 的最后 25 帧被 Scene 2 的白纸转场覆盖。

```python
# compute_timeline() 中场景串联
current_frame = 0
for i, scene in enumerate(scenes):
    entry = compute_timeline_entry(scene, current_frame)
    scene_entries.append(entry)
    # 下一个场景开始帧 = 当前场景开始 + 时长 - 重叠帧数
    current_frame += entry["durationFrames"]
    if i < len(scenes) - 1:
        current_frame -= TRANSITION_FRAMES  # 重叠
```

---

### 补充 6：generate_subtitles.py 适配新 timeline 格式

**问题**：方案修改清单中遗漏此文件。它读取 timeline 的 `sketchAtFrame` / `sketchDurationFrames` 来生成 SRT 时间戳，但新格式改为 `drawAtFrame` / `drawDurationFrames`。

**修改内容**：

```python
# 旧
start_time = elem["sketchAtFrame"] / fps
end_time = (elem["sketchAtFrame"] + elem["sketchDurationFrames"]) / fps

# 新
start_time = elem["drawAtFrame"] / fps
end_time = (elem["drawAtFrame"] + elem["drawDurationFrames"]) / fps
```

字段名替换，逻辑不变。加入修改文件清单。

---

### 补充 7：validate.py 适配——检查 vtracer 而非 ffmpeg

**问题**：当前 `validate.py` 检查 ffmpeg/ffprobe 是否安装。SVG 方案不再需要这些，但需要检查 vtracer。

**修改内容**：

```python
def check_vectorizer():
    """检查 vtracer 是否可用。"""
    try:
        import vtracer
        return []
    except ImportError:
        return ["vtracer 未安装。运行: pip install vtracer"]

def check_svg_path_tools():
    """检查 svgpathtools 是否可用。"""
    try:
        import svgpathtools
        return []
    except ImportError:
        return ["svgpathtools 未安装。运行: pip install svgpathtools"]

# 移除或降级 ffmpeg 检查：
# ffmpeg 仍被 Remotion CLI 使用，但不是 Python 管线的直接依赖
# 改为 warn 而非 error
```

---

### 补充 8：binary vs color 模式开关

**问题**：`colormode="binary"` 丢失所有颜色信息。如果场景包含彩色元素（红色箭头、蓝色高亮），需要 color 模式。

**解决**：在 storyboard.json 的 `meta` 或每个 `scene` 上新增可选字段。

```json
{
  "meta": {
    "vectorize": {
      "colormode": "binary",
      "filter_speckle": 8
    }
  },
  "scenes": [
    {
      "id": "scene3",
      "vectorize": { "colormode": "color" }
    }
  ]
}
```

`vectorize_images.py` 中：

```python
def get_vtracer_params(scene: dict, meta: dict) -> dict:
    """合并 meta 级和 scene 级矢量化参数，scene 级覆盖 meta 级。"""
    base = {**VTRACER_PARAMS}
    meta_override = meta.get("vectorize", {})
    scene_override = scene.get("vectorize", {})
    base.update(meta_override)
    base.update(scene_override)
    return base
```

**color 模式的差异**：
- 输出的 path 有 `fill` 颜色（不再全是黑色）
- path 数量更多（每个颜色区域是独立 path）
- `classify_path` 逻辑不变（仍按宽高比分类 stroke vs fill）
- `type="fill"` 的路径动画保留原色

---

### 补充 9：图片质量门禁——矢量化前检测

**问题**：如果 AI 生图不够"简笔画"（灰色渐变、复杂背景、抗锯齿模糊），vtracer 输出大量碎片 path，整个后续链路产出垃圾。

**解决**：在 `vectorize_images.py` 中矢量化前后各做一次检测。

#### 矢量化前：图片适合度检查

```python
def check_vectorization_readiness(image_path: str) -> list[str]:
    """检查图片是否适合矢量化。返回警告列表。"""
    import cv2
    img = cv2.imread(image_path)
    warnings = []
    
    # 1. 背景是否足够白
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corner_brightness = [
        gray[0:20, 0:20].mean(),
        gray[0:20, -20:].mean(),
        gray[-20:, 0:20].mean(),
        gray[-20:, -20:].mean(),
    ]
    avg_corner = sum(corner_brightness) / 4
    if avg_corner < 240:
        warnings.append(f"背景偏暗 (四角平均亮度={avg_corner:.0f})，可能影响矢量化质量")
    
    # 2. 对比度是否足够
    content_mask = gray < 200  # 非白色像素
    if content_mask.sum() < 0.01 * gray.size:
        warnings.append("图片内容过少 (非白色像素 < 1%)")
    elif content_mask.sum() > 0.60 * gray.size:
        warnings.append("图片内容过密 (非白色像素 > 60%)，矢量化可能产生大量碎片")
    
    # 3. 灰色过渡区域（抗锯齿/渐变）
    mid_gray = ((gray > 50) & (gray < 200)).sum()
    mid_gray_ratio = mid_gray / gray.size
    if mid_gray_ratio > 0.15:
        warnings.append(f"灰色过渡区域过多 ({mid_gray_ratio:.1%})，建议增加对比度或使用更清晰的线条")
    
    return warnings
```

#### 矢量化后：输出质量检查

```python
def check_vectorization_output(paths: list[dict], image_area: int) -> list[str]:
    """检查矢量化输出质量。"""
    warnings = []
    
    if len(paths) > 500:
        warnings.append(f"路径数量过多 ({len(paths)})，建议提高 filter_speckle 或简化原图")
    
    if len(paths) < 3:
        warnings.append(f"路径数量过少 ({len(paths)})，图片可能无足够内容")
    
    # 检查碎片比例
    small_paths = [p for p in paths if p["bbox"]["w"] * p["bbox"]["h"] < image_area * 0.001]
    if len(small_paths) > len(paths) * 0.5:
        warnings.append(f"碎片路径过多 ({len(small_paths)}/{len(paths)})，建议检查原图线条清晰度")
    
    return warnings
```

**行为**：警告打印但不阻断管线。如果警告数量 > 3 或出现严重警告（路径 > 500），打印红色提示建议用户检查原图。

---

### 补充 10：svg-data.json 合并格式定义

**问题**：Remotion 需要加载每个场景的 SVG 路径数据，但场景数不固定，不能硬编码 import。

**解决**：`deploy_resources.py` 将所有场景的 SVG 数据合并为单个 JSON 文件。

#### 文件格式：`src/svg-data.json`

```json
{
  "scene1": {
    "viewBox": "0 0 1920 1080",
    "elements": [
      {
        "id": "person",
        "paths": [
          { "d": "M100,200 C...", "stroke": "#000", "strokeWidth": 2.5, "fill": "none", "length": 342.5, "type": "stroke" },
          { "d": "M300,400 L...", "stroke": "#000", "strokeWidth": 1.8, "fill": "none", "length": 89.2, "type": "stroke" }
        ],
        "totalLength": 431.7
      }
    ]
  },
  "scene2": { ... },
  "scene3": { ... }
}
```

#### deploy_resources.py 合并逻辑

```python
def merge_svg_data(svg_data_dir: str, output_path: str):
    """合并所有场景的 SVG 数据为单个 JSON 文件。"""
    merged = {}
    for f in sorted(Path(svg_data_dir).glob("*.json")):
        scene_id = f.stem  # "scene1"
        with open(f) as fh:
            data = json.load(fh)
        # 从 data 中剔除 narration（已在 scene-config.json 中）
        # 只保留渲染必需的 paths 数据
        merged[scene_id] = {
            "viewBox": data["viewBox"],
            "elements": [
                {
                    "id": elem["id"],
                    "paths": elem["paths"],
                    "totalLength": elem["totalLength"],
                }
                for elem in data["elements"]
            ],
        }
    
    with open(output_path, "w") as f:
        json.dump(merged, f)  # 不 indent，减小文件体积
```

#### Remotion 侧加载

```tsx
// index.tsx
import svgData from "./svg-data.json";
import timeline from "./timeline.json";
import sceneConfig from "./scene-config.json";

// WhiteboardVideo.tsx
const WhiteboardVideo: React.FC<{
  timeline: Timeline;
  storyboard: Storyboard;
  svgData: Record<string, SVGSceneData>;
}> = ({ timeline, storyboard, svgData }) => {
  // 渲染时按 scene.id 查找对应的 SVG 数据
  const sceneSvg = svgData[tScene.id];
  // ...
};
```

---

### 补充 11：画手角度计算具体实现

```tsx
function computeHandAngle(d: string, progress: number): number {
  /**
   * 计算路径在当前绘制点的切线方向角度（度）。
   * 用于旋转画手 PNG 使其朝向绘制方向。
   */
  const length = getLength(d);
  const currentLen = length * progress;
  
  // 取当前点和稍前方的点，计算方向
  const epsilon = Math.min(2, length * 0.01);  // 采样间距
  const p1 = getPointAtLength(d, Math.max(0, currentLen - epsilon));
  const p2 = getPointAtLength(d, currentLen);
  
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  
  if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) {
    return 0;  // 静止点，不旋转
  }
  
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  return angle;
}
```

**角度平滑**：为避免尖角处画手突然旋转，在组件中维护 3 帧平均：

```tsx
const [angleHistory, setAngleHistory] = useState<number[]>([]);

const rawAngle = computeHandAngle(d, progress);
const smoothedAngle = angleHistory.length > 0
  ? [...angleHistory.slice(-2), rawAngle].reduce((a, b) => a + b) / Math.min(3, angleHistory.length + 1)
  : rawAngle;
```

注意：Remotion 组件是无状态渲染（每帧独立计算），不能用 useState。改为直接计算当前帧和前两帧的角度平均值：

```tsx
const angles = [-2, -1, 0].map(offset => {
  const f = Math.max(0, frame + offset);
  const prog = clamp((f - pathStart) / pathDuration, 0, 1);
  return computeHandAngle(d, prog);
});
const smoothedAngle = angles.reduce((a, b) => a + b) / angles.length;
```

---

### 补充 12：fill 路径复杂度检测——跳过描轮廓

**问题**：极复杂的 fill 路径（几十个贝塞尔段），用 stroke-dashoffset 描轮廓时线条来回折返、视觉混乱。

**解决**：对 fill 路径增加复杂度检测，超过阈值的直接用淡入，跳过描轮廓。

```tsx
// SVGDrawAnimation.tsx 内 fill 路径渲染逻辑

const pathComplexity = (path.d.match(/[MCLQSAZ]/gi) || []).length;
const useOutlineAnimation = pathComplexity < 30;  // < 30 个命令才描轮廓

if (path.type === "fill") {
  if (useOutlineAnimation) {
    // 先描轮廓（前 60%），再淡入填充（后 40%）
    // ...（原方案代码）
  } else {
    // 复杂路径：直接淡入，无描轮廓
    return (
      <path
        key={...}
        d={path.d}
        fill={path.fill}
        stroke="none"
        opacity={pathProgress}
      />
    );
  }
}
```

---

### 补充 13：PaperPullTransition spring 过冲修正

**问题**：spring 动画可能产生过冲（纸张"弹一下"），纸张不应弹跳。

**修正**：使用 `interpolate` + ease-out 缓动替代 spring，或给 spring 加 `overshootClamping`。

```tsx
// 方案 A：使用 interpolate + ease-out（推荐，行为可预测）
const progress = clamp((frame - startFrame) / durationFrames, 0, 1);
const eased = progress < 1
  ? 1 - Math.pow(1 - progress, 3)  // ease-out cubic
  : 1;
const paperY = -1080 + 1080 * eased;

// 方案 B：spring 加 overshootClamping
const paperY = interpolate(
  spring({
    frame: Math.max(0, frame - startFrame),
    fps,
    config: { damping: 30, stiffness: 80, overshootClamping: true },
  }),
  [0, 1],
  [-1080, 0]
);
```

---

### 补充 14：端到端验证需要新测试图片

**问题**：现有 storyboard 的图片是"精致插画风"，不适合矢量化测试。

**解决**：在 Day 1（vectorize_images.py 开发）前，先准备测试素材：

1. **手动绘制 3 张测试图**：用 Procreate / 纸笔扫描 / 在线工具画 3 张简笔画
   - scene_test1.png：单元素（一个简笔画人物）
   - scene_test2.png：多元素（人物 + 闹钟 + 纸币，有间隔）
   - scene_test3.png：含填充区域（一个实心圆 + 线条）

2. **AI 生成 3 张测试图**：用 iPad 简笔画 Prompt 在 Seedream/Midjourney 生成
   - 检验 Prompt 能否真正产出"干净可矢量化"的图片
   - 如果不行，**先调通 Prompt 再写代码**

3. **vtracer 预验证**：对 6 张测试图分别跑 vtracer binary 模式，检查：
   - 路径数量是否在 10-200 范围内
   - 是否有大量碎片
   - 线条路径是否连续（非断裂碎片）

```bash
# 快速验证命令
pip install vtracer
python -c "
import vtracer
svg_str = vtracer.convert_image_to_svg_py(
    'scene_test1.png', 'test_output.svg',
    colormode='binary', filter_speckle=8, mode='spline'
)
# 用浏览器打开 test_output.svg 检查质量
"
```

**这一步必须在 Day 0 完成，是整个方案的前置条件。**

---

## 更新后的文件改动清单

### 新增文件

| 文件 | 职责 |
|------|------|
| `scripts/vectorize_images.py` | PNG → SVG 矢量化 + 路径分组排序 + 质量门禁 |
| `remotion-project/src/SVGDrawAnimation.tsx` | SVG stroke-dashoffset 路径动画 + 画手跟随 |
| `remotion-project/src/PaperPullTransition.tsx` | 纯白纸场景转场（ease-out，无过冲） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `scripts/config.py` | 背景色 → #FFFFFF，新增 VTRACER_PARAMS |
| `scripts/generate_prompts.py` | Prompt 模板 → iPad 简笔画，LLM system prompt 更新 |
| `scripts/compute_timeline.py` | 30fps 直出，新时间分配公式，场景重叠 |
| `scripts/deploy_resources.py` | 部署 SVG 数据（合并为 svg-data.json），替代 MP4 |
| `scripts/make_video.py` | Step 8 替换为 vectorize，移除 ffprobe 步骤 |
| `scripts/validate_images.py` | 背景色纯白 + 图片尺寸归一化 1920×1080 |
| `scripts/validate.py` | 检查 vtracer/svgpathtools 而非 ffmpeg |
| `scripts/generate_subtitles.py` | `sketchAtFrame` → `drawAtFrame` 字段名更新 |
| `scripts/parse_storyboard.py` | 默认风格值 ipad_sketch + vectorize 参数 |
| `remotion-project/src/WhiteboardVideo.tsx` | SVGDrawAnimation 替代 Video，背景色，转场，SVG 数据传入 |
| `remotion-project/src/types.ts` | 新增 SVG 类型，简化 ElementTimeline |
| `remotion-project/src/index.tsx` | import svg-data.json，传入 WhiteboardVideo |
| `remotion-project/package.json` | 新增 @remotion/paths |

### Python 依赖完整列表

```
vtracer>=0.6.10
svgpathtools>=1.6.0
opencv-python>=4.8.0    # validate_images 尺寸归一化仍用
pydub>=0.25.1           # SFX 生成 + 音频处理
python-dotenv>=1.0.0    # 环境变量
```

### 可删除文件

| 文件 | 原因 |
|------|------|
| `scripts/generate_scene_animation.py` | 被 SVG 方案完整替代 |
| `scripts/generate_animations.py` | 被 vectorize_images.py 替代 |
| `scripts/detect_regions.py` | 不再需要自动区域检测 |

---

## 更新后的实施顺序

```
Day 0 (前置验证):
  - 准备 6 张测试图（3 手绘 + 3 AI 生成）
  - 跑 vtracer binary 验证输出质量
  - 如果 AI 生图不达标，先调通 Prompt
  - 验证 @remotion/paths 与 remotion 4.0.0 的兼容性

Week 1:
  Day 1-2: vectorize_images.py（vtracer + svgpathtools + 分组 + 排序 + 质量检测）
  Day 3:   config.py / generate_prompts.py / validate_images.py（背景色 + 风格 + 尺寸归一化）
  Day 4:   compute_timeline.py（新公式）+ generate_subtitles.py（字段名）+ validate.py

Week 2:
  Day 5-7: SVGDrawAnimation.tsx（路径动画 + 按长度比例分配时间 + 画手坐标转换 + 角度平滑）
  Day 8:   PaperPullTransition.tsx（ease-out 无过冲）
  Day 9:   WhiteboardVideo.tsx 整合 + types.ts + DrawingSFX 简化

Week 3:
  Day 10:  deploy_resources.py（svg-data.json 合并）+ make_video.py 管线串联
  Day 11:  index.tsx + package.json 依赖
  Day 12-14: 端到端测试 + 调优（路径排序、unassigned 处理、动画速度、画手角度）