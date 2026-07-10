
## 一、YouTube 专业白板视频到底怎么做的

### 行业标准方案（VideoScribe / Doodly）

| 工具 | 核心技术 | 路径来源 |
|------|---------|---------|
| **VideoScribe** | SVG stroke-dashoffset，但用的是**人工绘制的 stroke 中心线 path**，不是 potrace 轮廓 | 专业画师手工制作 SVG |
| **Doodly** | **PNG 原图 + 沿路径的渐进蒙版揭示** | 用户手动画路径 / 对角线扫描 |

关键区别：

- **VideoScribe 路径**：`<path fill="none" stroke="#000" d="M100,200 C..."/>` — 一条线就是一条 path，有 stroke 无 fill。dashoffset 动画直接就是"画一条线"。
- **potrace 路径**：`<path fill="#000" d="M100,200 ... z"/>` — 一个填充区域的闭合轮廓。dashoffset 动画是"描轮廓"。

**本项目不可能手工制作 SVG，所以 VideoScribe 的路线走不通。**
**正确路线 = Doodly 模式：用原始 PNG 作为最终画面，用路径驱动蒙版揭示。**

---

## 二、新架构：PNG Mask Reveal

### 核心思想

```
不要试图重新"画"出图片（矢量化 → 重渲染），
而是"揭示"原始 PNG 图片（蒙版沿路径展开）。
```

### 数据流

```
                         ┌─────────────────────────────┐
                         │  AI 生成的 PNG（最终画质）   │
                         └──────────┬──────────────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                     ▼
      ┌────────────────┐  ┌─────────────────┐  ┌────────────────┐
      │  中心线提取     │  │  PNG 原图        │  │  时间轴计算     │
      │  (skeleton)    │  │  (全质量保留)     │  │  (不变)         │
      └───────┬────────┘  └────────┬─────────┘  └───────┬────────┘
              │                    │                     │
              ▼                    ▼                     ▼
      ┌──────────────────────────────────────────────────────────┐
      │                    Remotion 渲染                          │
      │                                                          │
      │   <Img src="scene1.png" style={{mask: url(#reveal)}} />  │
      │                                                          │
      │   <svg><mask id="reveal">                                │
      │     <path d={中心线} stroke="white"                       │
      │           strokeWidth={粗蒙版笔刷}                        │
      │           strokeDasharray={len}                           │
      │           strokeDashoffset={len*(1-progress)} />          │
      │   </mask></svg>                                          │
      │                                                          │
      │   <DrawingHand position={getPointAtLength(中心线, t)} />  │
      └──────────────────────────────────────────────────────────┘
              │
              ▼
      ┌────────────────┐
      │  最终 MP4 视频  │
      └────────────────┘
```

### 与 07 方案的根本区别

| 维度 | 07 方案 (SVG 重绘) | 新方案 (PNG Mask Reveal) |
|------|-------------------|------------------------|
| **最终可见内容** | SVG 路径重新渲染（质量丢失） | 原始 PNG 图片（零质量损失） |
| **路径用途** | 作为**可见内容**被渲染 | 作为**蒙版**控制揭示区域 |
| **路径精度要求** | 极高（像素级，否则画面残缺） | 低（粗笔刷覆盖，容错高） |
| **路径类型** | 需要 stroke 中心线（potrace 给不了） | 中心线最好，但粗略骨架也够用 |
| **对 AI 图片风格的依赖** | 极高（必须纯线条、强对比） | 低（任何图片都能被蒙版揭示） |
| **视觉效果** | 轮廓爬行 | PNG 沿绘画路径渐进出现 |

---

## 三、中心线提取：scikit-image skeletonize

蒙版路径必须沿画面内容走，画手才能跟随内容轮廓移动，揭示效果才像"在画"。

```
pip install scikit-image scipy numpy Pillow

PNG → 灰度 → 二值化 → skeletonize() → 1px 骨架 → 连通分量标记 → nearest-neighbor 排序 → SVG polyline paths
```

scikit-image 的 skeletonize 是形态学细化的工业标准实现，输出精确的 1px 宽中心线，对 iPad 简笔画风格（黑色线条、白底、强对比）效果最好。

**关键洞察：中心线不需要完美。** 它只是蒙版路径，蒙版笔刷宽度 80-100px，中心线偏移 20px 完全不影响视觉效果。

---

## 四、Remotion 渲染层重构

### 4-1. 新组件：MaskRevealAnimation（替代 SVGDrawAnimation）

**文件**: `remotion-project/src/MaskRevealAnimation.tsx`

```tsx
import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
  interpolate,
} from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";

interface DrawingPath {
  d: string;         // SVG path d 属性（中心线）
  elementId: string;  // 归属元素 ID
}

interface MaskRevealProps {
  imageSrc: string;               // 场景 PNG 图片路径
  drawingPaths: DrawingPath[];    // 中心线路径列表
  drawAtFrames: number[];         // 每组路径的起始帧
  drawDurations: number[];        // 每组路径的绘制帧数
  brushRadius?: number;           // 蒙版笔刷半径 (px)
  showHand?: boolean;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const MaskRevealAnimation: React.FC<MaskRevealProps> = ({
  imageSrc,
  drawingPaths,
  drawAtFrames,
  drawDurations,
  brushRadius = 50,
  showHand = true,
}) => {
  const frame = useCurrentFrame();

  // 为每条路径计算蒙版状态
  const maskPaths = useMemo(() => {
    return drawingPaths.map((dp, i) => {
      const elemIdx = drawAtFrames.findIndex((_, idx) => {
        // 找到此路径属于哪个元素的时间段
        // 简化：按路径顺序分配到元素
        return idx === Math.min(i, drawAtFrames.length - 1);
      });
      return { ...dp, elemIdx: Math.min(i, drawAtFrames.length - 1) };
    });
  }, [drawingPaths, drawAtFrames]);

  // 找到当前正在绘制的路径（用于画手定位）
  let handX = -200, handY = -200, handAngle = 0, handVisible = false;

  return (
    <AbsoluteFill>
      {/* 层 1: 被蒙版揭示的 PNG 原图 */}
      <div
        style={{
          position: "absolute",
          width: CANVAS_W,
          height: CANVAS_H,
          // CSS mask 引用内联 SVG 蒙版
          WebkitMaskImage: "url(#reveal-mask)",
          maskImage: "url(#reveal-mask)",
        }}
      >
        {/* 使用 SVG mask 方式 (Remotion 兼容) */}
        <svg
          width={CANVAS_W}
          height={CANVAS_H}
          viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
          style={{ position: "absolute", width: "100%", height: "100%" }}
        >
          <defs>
            <mask id={`reveal-mask-${frame}`}>
              {/* 黑色背景 = 完全遮挡 */}
              <rect width={CANVAS_W} height={CANVAS_H} fill="black" />

              {/* 白色笔刷路径 = 揭示区域 */}
              {drawingPaths.map((dp, pathIdx) => {
                const elemIdx = Math.min(pathIdx, drawAtFrames.length - 1);
                const elemStart = drawAtFrames[elemIdx] || 0;
                const elemDuration = drawDurations[elemIdx] || 1;

                // 此路径在元素内的时间偏移
                // 简化：元素内多条路径按顺序均分时间
                const pathsInElem = drawingPaths.filter(
                  (_, j) => Math.min(j, drawAtFrames.length - 1) === elemIdx
                ).length;
                const pathIndexInElem = drawingPaths
                  .slice(0, pathIdx)
                  .filter((_, j) => Math.min(j, drawAtFrames.length - 1) === elemIdx)
                  .length;

                const pathDuration = elemDuration / Math.max(1, pathsInElem);
                const pathStart = elemStart + pathIndexInElem * pathDuration;
                const progress = Math.max(0, Math.min(1,
                  (frame - pathStart) / pathDuration
                ));

                if (progress <= 0) return null;

                let pathLen: number;
                try {
                  pathLen = getLength(dp.d);
                } catch {
                  pathLen = 100;
                }

                // 完成的路径：完全揭示
                if (progress >= 1) {
                  return (
                    <path
                      key={pathIdx}
                      d={dp.d}
                      stroke="white"
                      strokeWidth={brushRadius * 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                    />
                  );
                }

                // 进行中：dashoffset 控制揭示进度
                const dashOffset = pathLen * (1 - progress);

                // 更新画手位置
                if (progress > 0 && progress < 1) {
                  try {
                    const point = getPointAtLength(dp.d, pathLen * progress);
                    handX = point.x;
                    handY = point.y;
                    handVisible = true;

                    // 计算画手角度
                    const epsilon = Math.min(2, pathLen * 0.01);
                    const p1 = getPointAtLength(dp.d,
                      Math.max(0, pathLen * progress - epsilon));
                    const p2 = getPointAtLength(dp.d,
                      Math.min(pathLen, pathLen * progress + epsilon));
                    handAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
                  } catch {
                    // 忽略
                  }
                }

                return (
                  <path
                    key={pathIdx}
                    d={dp.d}
                    stroke="white"
                    strokeWidth={brushRadius * 2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                    strokeDasharray={pathLen}
                    strokeDashoffset={dashOffset}
                  />
                );
              })}
            </mask>
          </defs>

          {/* 应用蒙版的图片 */}
          <image
            href={imageSrc}
            width={CANVAS_W}
            height={CANVAS_H}
            mask={`url(#reveal-mask-${frame})`}
          />
        </svg>
      </div>

      {/* 层 2: 画手 */}
      {showHand && handVisible && (
        <Img
          src={staticFile("assets/writing-hand-small.png")}
          style={{
            position: "absolute",
            left: handX - 10,
            top: handY - 30,
            width: 120,
            height: 120,
            transform: `rotate(${handAngle}deg)`,
            transformOrigin: "10px 30px",
            zIndex: 100,
            pointerEvents: "none",
          }}
        />
      )}
    </AbsoluteFill>
  );
};

export default MaskRevealAnimation;
```

**核心机制解释**：

1. **SVG `<mask>` 元素**：黑色 = 完全遮挡，白色 = 完全显示
2. **蒙版中的 `<path>`**：用 `stroke="white"` + 很粗的 `strokeWidth`（笔刷直径 80-100px）
3. **strokeDashoffset 动画**：让白色笔刷沿路径渐进展开
4. **PNG `<image>` 被蒙版裁剪**：只有白色笔刷扫过的区域能看到 PNG

**为什么这次 dashoffset 可以用**：

蒙版路径是**中心线**（开放 path，不闭合），不是 potrace 的闭合轮廓。中心线上的 dashoffset 就是一个点沿路径移动，白色笔刷跟着走，PNG 被渐进揭示。观众看到的不是"线在爬行"，而是"PNG 图片沿着画手轨迹出现"。

### 4-2. WhiteboardVideo.tsx 改动

将 `SVGDrawAnimation` 替换为 `MaskRevealAnimation`：

```tsx
// 旧（07 方案）
{hasSvgData ? (
  <SVGDrawAnimation
    elements={sceneSvg.elements}
    drawAtFrames={...}
    drawDurations={...}
    viewBox={sceneSvg.viewBox}
  />
) : null}

// 新
{hasDrawingPaths ? (
  <MaskRevealAnimation
    imageSrc={staticFile(`images/${tScene.id}.png`)}
    drawingPaths={sceneDrawPaths}
    drawAtFrames={tScene.elements?.map(e => e.drawAtFrame) || []}
    drawDurations={tScene.elements?.map(e => e.drawDurationFrames) || []}
    brushRadius={50}
    showHand={!storyboard.meta?.noHand}
  />
) : null}
```

### 4-3. 数据格式变化

**旧格式** (svg-data.json)：
```json
{
  "scene1": {
    "viewBox": "0 0 1920 1080",
    "elements": [
      {
        "id": "person",
        "paths": [
          {"d": "M14169 9696 c...", "stroke": "#000", "fill": "none",
           "length": 0.0, "type": "stroke"}
        ],
        "totalLength": 0.0
      }
    ]
  }
}
```

**新格式** (drawing-paths.json)：
```json
{
  "scene1": {
    "paths": [
      {"d": "M120 350 L180 320 L250 380 L300 400", "elementId": "person"},
      {"d": "M700 200 L750 180 L800 220 L850 250", "elementId": "clock"},
      {"d": "M780 600 L820 580 L860 620", "elementId": "money"}
    ]
  }
}
```

**关键区别**：
- 路径是中心线（开放路径，不闭合）
- 坐标在 0-1920 / 0-1080 范围内（PNG 像素坐标）
- 不需要 length / totalLength / type / viewBox — Remotion 侧用 `@remotion/paths` 实时计算
- 一条路径对应一条绘制轨迹，不是一个填充区域的边界

---

## 五、Python 管线重构

### 5-1. 新脚本：extract_drawing_paths.py（替代 vectorize_images.py）

```python
#!/usr/bin/env python3
"""
extract_drawing_paths.py - 从 PNG 图片中提取绘制中心线路径。

输入: images/{scene_id}.png + storyboard.json (elements/bbox)
输出: drawing_paths/{scene_id}.json + drawing-paths.json (合并)

技术: scikit-image skeletonize → 1px 骨架 → 连通分量 → nearest-neighbor 排序 → SVG polyline
路径用途: 作为 Remotion MaskRevealAnimation 的蒙版引导路径。
"""

from PIL import Image
import numpy as np
from skimage.morphology import skeletonize
from scipy.ndimage import label


def extract_drawing_paths(image_path, elements):
    """从 PNG 提取中心线路径，按 element bbox 分组。"""
    img = np.array(Image.open(image_path).convert('L'))
    binary = img < 200  # 黑色内容 = True
    skeleton = skeletonize(binary)  # 1px 宽骨架
    
    # 标记连通分量，每个连通分量 = 一条绘制路径
    labeled, n = label(skeleton)
    
    raw_paths = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(xs) < 5:
            continue
        points = list(zip(xs.tolist(), ys.tolist()))
        ordered = _order_points_nearest_neighbor(points)
        d = _points_to_svg_path(ordered)
        bbox = {"x": int(xs.min()), "y": int(ys.min()),
                "w": int(xs.max() - xs.min()), "h": int(ys.max() - ys.min())}
        raw_paths.append({"d": d, "bbox": bbox})
    
    return _assign_paths_to_elements(raw_paths, elements)


def _points_to_svg_path(points):
    """坐标点列表 → SVG path d 属性。"""
    if not points:
        return ""
    d = f"M{points[0][0]} {points[0][1]}"
    for p in points[1:]:
        d += f" L{p[0]} {p[1]}"
    return d


def _order_points_nearest_neighbor(points):
    """Nearest-neighbor 排序，将散点连成连续路径。"""
    if len(points) <= 2:
        return points
    
    ordered = [points[0]]
    remaining = set(range(1, len(points)))
    
    for _ in range(len(points) - 1):
        if not remaining:
            break
        last = ordered[-1]
        best_idx = min(remaining,
                       key=lambda i: (points[i][0]-last[0])**2 + (points[i][1]-last[1])**2)
        ordered.append(points[best_idx])
        remaining.remove(best_idx)
    
    return ordered


def _assign_paths_to_elements(raw_paths, elements):
    """将路径按 bbox 归属到元素。坐标已在 PNG 像素空间，直接匹配。"""
    result = []
    assigned = set()
    
    for elem in elements:
        eb = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
        # 15% padding
        pad_x = eb["w"] * 0.15
        pad_y = eb["h"] * 0.15
        ex1 = eb["x"] - pad_x
        ey1 = eb["y"] - pad_y
        ex2 = eb["x"] + eb["w"] + pad_x
        ey2 = eb["y"] + eb["h"] + pad_y
        
        elem_paths = []
        for i, rp in enumerate(raw_paths):
            if i in assigned:
                continue
            rb = rp["bbox"]
            cx = rb["x"] + rb["w"] / 2
            cy = rb["y"] + rb["h"] / 2
            if ex1 <= cx <= ex2 and ey1 <= cy <= ey2:
                elem_paths.append({"d": rp["d"], "elementId": elem["id"]})
                assigned.add(i)
        
        result.extend(elem_paths)
    
    # 未分配的路径归入最近的元素
    for i, rp in enumerate(raw_paths):
        if i in assigned:
            continue
        cx = rp["bbox"]["x"] + rp["bbox"]["w"] / 2
        cy = rp["bbox"]["y"] + rp["bbox"]["h"] / 2
        nearest = min(elements,
                      key=lambda e: (e["bbox"]["x"]+e["bbox"]["w"]/2-cx)**2 +
                                    (e["bbox"]["y"]+e["bbox"]["h"]/2-cy)**2)
        result.append({"d": rp["d"], "elementId": nearest["id"]})
    
    return result
```

### 5-2. make_video.py Step 8 替换

```python
# 旧 Step 8: vectorize_images（potrace → SVG 轮廓路径）
# 新 Step 8: extract_drawing_paths（骨架化 → 中心线路径）

if not _step_done(output_dir, "drawing_paths"):
    paths_mod = _import_step("extract_drawing_paths")
    paths_mod.extract_all_scenes(
        str(output_dir / "storyboard.json"),
        str(images_dir),
        str(output_dir),
    )
    _write_checkpoint(output_dir, "drawing_paths")
```

### 5-3. deploy_resources.py 改动

```python
# 旧：复制 svg_data/svg-data.json → src/svg-data.json
# 新：复制 drawing_paths/drawing-paths.json → src/drawing-paths.json
#     复制 images/*.png → public/images/

# 新增：将场景 PNG 图片复制到 Remotion public/
images_src = Path(output_dir) / "images"
images_dst = remotion_public / "images"
os.makedirs(images_dst, exist_ok=True)
for f in images_src.glob("*.png"):
    shutil.copy2(f, images_dst / f.name)
```

---

## 六、已知风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| SVG `<mask>` 在 Remotion 逐帧渲染中性能不足 | 渲染慢 | Remotion 底层 Chromium 原生支持 SVG mask，几十条路径+几百坐标点无压力。实测验证。 |
| 骨架在线条交叉点分叉，产生多余短路径 | 画手跳跃 | 过滤 <5 像素的短路径，nearest-neighbor 排序消除跳跃 |
| 画手跟随中心线时短暂遮挡内容 | 无 | 这是所有白板视频工具的正常行为，画完后画手移走，增加真实感 |
| 复杂图片（渐变、彩色）骨架化产生噪点 | 蒙版碎片 | 蒙版笔刷 80-100px 足够粗，噪点不影响揭示效果 |

---

## 七、文件改动清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `scripts/extract_drawing_paths.py` | PNG → 骨架化 → 中心线路径提取 |
| `remotion-project/src/MaskRevealAnimation.tsx` | PNG 蒙版揭示动画组件 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `remotion-project/src/WhiteboardVideo.tsx` | `SVGDrawAnimation` → `MaskRevealAnimation` |
| `remotion-project/src/index.tsx` | `svg-data.json` → `drawing-paths.json` |
| `remotion-project/src/types.ts` | 新增 DrawingPath 类型，移除 SVGPathData 等 |
| `scripts/deploy_resources.py` | 复制 PNG 到 public/images/，复制 drawing-paths.json |
| `scripts/make_video.py` | Step 8: vectorize → extract_drawing_paths |
| `requirements.txt` | 新增 scikit-image, scipy, numpy, Pillow |

### 废弃文件

| 文件 | 原因 |
|------|------|
| `scripts/vectorize_images.py` | 被 extract_drawing_paths.py 替代 |
| `remotion-project/src/SVGDrawAnimation.tsx` | 被 MaskRevealAnimation.tsx 替代 |
| `remotion-project/src/svg-data.json` | 被 drawing-paths.json 替代 |

---

## 八、实施顺序

```
Day 1:
  1. 安装依赖：pip install scikit-image scipy numpy Pillow       (0.5h)
  2. extract_drawing_paths.py: 骨架化 + 路径提取 + 元素分组      (3h)
  3. 验证：对 scene1.png 提取中心线，人工检查路径质量             (0.5h)

Day 2:
  4. MaskRevealAnimation.tsx: SVG mask + PNG reveal + 画手        (3h)
  5. WhiteboardVideo.tsx: 替换 SVGDrawAnimation                   (1h)
  6. index.tsx + types.ts + deploy_resources.py 适配              (1h)

Day 3:
  7. make_video.py Step 8 替换                                    (0.5h)
  8. 端到端测试：全管线跑通 → 渲染视频                           (1h)
  9. 质量调优：笔刷半径、绘制速度、画手角度                      (2h)
  10. 多场景/多风格图片测试                                       (1h)
  11. 与 YouTube 参考视频对比质量审查                              (1h)
```

---
