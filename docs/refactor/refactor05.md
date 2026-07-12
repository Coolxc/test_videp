# 修复方案：手拿笔展示 + 按元素顺序绘制

## 一、当前问题

经过 v08（PNG Mask Reveal）+ 交叉点拆分修复后，线条的手绘揭示效果已经出来了，但还有两个问题：

1. **没有手拿笔的展示** — 画面只是线条逐步出现，看不到手和笔跟随
2. **绘制顺序不对** — 应该按脚本定义的元素顺序逐个绘制（画完一个元素再画下一个），而不是从上往下扫描

---

## 二、问题 1：手拿笔不显示

### 2-1. 根因

`MaskRevealAnimation.tsx` 第 158 行存在**解构错误**：

```typescript
// 第 158 行（当前代码）
const { d, pathStart, pathDuration } = currentPath;
```

`currentPath` 的类型是 `ActivePathInfo`：

```typescript
interface ActivePathInfo {
  path: DrawingPath;    // ← path 是对象，内含 d 属性
  pathStart: number;
  pathDuration: number;
  progress: number;
}
```

解构 `currentPath.d` 得到 `undefined`（ActivePathInfo 没有 `d` 属性，`d` 在 `path.d` 里面）。

后续调用链：
```
d = undefined
→ getLength(undefined)   // 第 165 行：抛异常
→ catch { return null }  // 第 166 行：静默吞掉异常
→ DrawingHand 返回 null  // 手永远不渲染
```

手的图片文件 `writing-hand-small.png` 存在且正常（27KB），DrawingHand 组件逻辑完整，唯一问题就是这个解构错误导致手被静默隐藏。

### 2-2. 修复

**文件**: `remotion-project/src/MaskRevealAnimation.tsx`

**第 158-159 行**，改为：

```typescript
// 修复前
const { d, pathStart, pathDuration } = currentPath;
let { progress } = currentPath;

// 修复后
const { path, pathStart, pathDuration } = currentPath;
let { progress } = currentPath;
const d = path.d;
```

后续代码引用 `d` 的地方（第 165、169、174 行）不需要改，因为 `d` 已经是 `path.d` 的值。

---

## 三、问题 2：绘制顺序不按元素

### 3-1. 根因

涉及**两层问题**：Python 输出层 + Remotion 渲染层。

#### A. Python 层：路径没有按元素分组

当前 `_assign_paths_to_elements()` 的输出是按**空间位置**排列的，同一元素的路径散布在不同位置：

```
当前输出顺序（scene1）:
  path[0]  elementId=person   ← y=216
  path[1]  elementId=clock    ← y=234（clock 在画面上方）
  path[2]  elementId=clock    ← y=285
  path[3]  elementId=person   ← y=300
  ...（共 47 次元素切换）

期望输出顺序:
  path[0..189]   elementId=person  ← 先输出 person 的所有路径
  path[190..261] elementId=clock   ← 再输出 clock 的所有路径
  path[262..328] elementId=money   ← 最后输出 money 的所有路径
  （共 3 次元素切换 = 完美分组）
```

#### B. Remotion 层：elementOrder 与 drawAtFrames 对不齐

`MaskRevealAnimation.tsx` 中的 `elementOrder` 是从**路径数据的首次出现顺序**推导的：

```typescript
// 第 265-275 行
const elementOrder = useMemo(() => {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const dp of drawingPaths) {
    if (!seen.has(dp.elementId)) {
      seen.add(dp.elementId);
      order.push(dp.elementId);
    }
  }
  return order;
}, [drawingPaths]);
```

而 `drawAtFrames` 和 `drawDurations` 来自**时间轴**（脚本定义的元素顺序）：

```typescript
// WhiteboardVideo.tsx 第 469-471 行
drawAtFrames={tScene.elements?.map((e) => e.drawAtFrame) || []}
drawDurations={tScene.elements?.map((e) => e.drawDurationFrames) || []}
```

**两个顺序不一致时，元素-时间映射就错了**。

具体例子（scene1）：

| 索引 | elementOrder（路径推导） | drawAtFrames（时间轴） | 实际效果 |
|------|------------------------|----------------------|---------|
| 0 | clock（画面最上方 y=50） | 0（应该给 person） | clock 从第 0 帧开始画 ✗ |
| 1 | person（y=250） | 118（应该给 clock） | person 从第 118 帧开始画 ✗ |
| 2 | money（y=550） | 236 | money 从第 236 帧开始画 ✓ |

结果：绘制顺序跟着空间位置走（先画画面上方的元素），而不是跟脚本走。

### 3-2. 修复

#### 修复 A：Python 层 — 路径按元素分组输出

**文件**: `scripts/extract_drawing_paths.py`

**修改函数**: `_assign_paths_to_elements()`

改为先确定每条路径的归属元素，然后按 `elements` 列表顺序分组输出：

```python
def _assign_paths_to_elements(raw_paths, elements):
    if not elements:
        return [{"d": rp["d"], "elementId": "content"} for rp in raw_paths]

    # 扩增 element bbox（15% padding）— 保持不变
    padded = [...]

    # 先为每条路径确定归属元素
    path_elem_map = {}  # path_index → elementId
    for i, rp in enumerate(raw_paths):
        cx = rp["bbox"]["x"] + rp["bbox"]["w"] / 2
        cy = rp["bbox"]["y"] + rp["bbox"]["h"] / 2

        matched = None
        for pe in padded:
            if pe["x1"] <= cx <= pe["x2"] and pe["y1"] <= cy <= pe["y2"]:
                matched = pe["id"]
                break
        if not matched:
            nearest = min(padded, key=lambda pe: ...)
            matched = nearest["id"]
        path_elem_map[i] = matched

    # 按元素分组输出（顺序 = storyboard 定义顺序）
    result = []
    for elem in elements:
        eid = elem["id"]
        for i, rp in enumerate(raw_paths):
            if path_elem_map[i] == eid:
                result.append({"d": rp["d"], "elementId": eid})

    return result
```

#### 修复 B：Remotion 层 — elementOrder 从时间轴传入

**文件 1**: `remotion-project/src/MaskRevealAnimation.tsx`

1. 接口新增 `elementIds` prop：

```typescript
interface MaskRevealProps {
  imageSrc: string;
  drawingPaths: DrawingPath[];
  drawAtFrames: number[];
  drawDurations: number[];
  elementIds?: string[];          // 新增：元素 ID 顺序（与 drawAtFrames 对齐）
  brushRadius?: number;
  showHand?: boolean;
}
```

2. 组件参数解构新增 `elementIds`：

```typescript
const MaskRevealAnimation: React.FC<MaskRevealProps> = ({
  imageSrc,
  drawingPaths,
  drawAtFrames,
  drawDurations,
  elementIds,        // 新增
  brushRadius = 50,
  showHand = true,
}) => {
```

3. `elementOrder` 优先使用 `elementIds`（第 265-275 行替换为）：

```typescript
const elementOrder = useMemo(() => {
  if (elementIds && elementIds.length > 0) {
    return elementIds;
  }
  // fallback：从路径数据推导
  const seen = new Set<string>();
  const order: string[] = [];
  for (const dp of drawingPaths) {
    if (!seen.has(dp.elementId)) {
      seen.add(dp.elementId);
      order.push(dp.elementId);
    }
  }
  return order;
}, [drawingPaths, elementIds]);
```

**文件 2**: `remotion-project/src/WhiteboardVideo.tsx`

传入 `elementIds`（第 465-475 行）：

```typescript
<MaskRevealAnimation
  imageSrc={staticFile(`images/${tScene.id}.png`)}
  drawingPaths={scenePaths.paths}
  drawAtFrames={tScene.elements?.map((e) => e.drawAtFrame) || []}
  drawDurations={tScene.elements?.map((e) => e.drawDurationFrames) || []}
  elementIds={tScene.elements?.map((e) => e.id) || []}   // 新增
  brushRadius={50}
  showHand={!storyboard.meta?.noHand}
/>
```

---

## 四、改动清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `remotion-project/src/MaskRevealAnimation.tsx` | 修复解构 bug（158 行）；接口新增 `elementIds`；`elementOrder` 优先用 `elementIds` | ~10 行 |
| `remotion-project/src/WhiteboardVideo.tsx` | 传入 `elementIds` prop | 1 行 |
| `scripts/extract_drawing_paths.py` | `_assign_paths_to_elements` 输出按元素分组 | ~20 行 |

---

## 五、修复后效果

### 场景 1（人+钟+钱）

```
修复前:
  帧 0~108:   clock 的线条出现（空间上方先画）
  帧 118~226: person 的线条出现
  帧 236~266: money 的线条出现
  全程无手

修复后:
  帧 0~108:   手拿笔画 person（按脚本顺序第一个元素）
  帧 118~226: 手拿笔画 clock（第二个元素）
  帧 236~266: 手拿笔画 money（第三个元素）
  手沿每条线段平滑移动，跟随笔画轨迹
```

### 场景 2（脑）和场景 3（金字塔）

这两个场景各只有 1 个元素，不存在元素顺序问题，修复后主要变化是**手拿笔跟随线条移动**。

---

## 六、验证

1. 重新提取路径 → 检查路径按元素分组（element switches = 元素数）
2. 部署到 Remotion → 渲染视频
3. 检查：手是否跟随线条移动、元素是否按脚本顺序逐个绘制
