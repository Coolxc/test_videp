# 修复手绘路径提取：消除锯齿扫描线，恢复手绘动画效果

## 一、问题现象

v08 方案（PNG Mask Reveal）改造后，生成的视频存在三个问题：

1. **画面从上到下渐进展示**，像百叶窗/扫描仪，完全不像手绘
2. **没有手跟随画面内容移动**（手在画面两端来回跳跃，视觉上等于不可见）
3. **没有画线条的效果**（蒙版是横向扫过，不是沿着线条展开）

## 二、根因分析

### 2-1. 数据层面的证据

检查当前 `drawing-paths.json` 中的路径数据：

```
scene2 brain path[0] (11771 字符):
  M951 226 L1057 226 L903 234 L1091 234 L871 235 L1093 235 L868 236 ...

scene3 pyramid path[0] (15734 字符):
  M968 60 L954 69 L972 69 L954 70 L973 70 L945 71 L974 71 L944 72 ...
```

**特征**：X 坐标在左（~840-950）和右（~1050-1140）之间交替跳跃，Y 坐标缓慢递增。这是典型的**水平锯齿扫描线**模式。

### 2-2. 根因追溯

问题出在 `scripts/extract_drawing_paths.py` 的路径排序算法：

```
PNG 图片
  → 二值化 (img < 200)
  → skeletonize() → 1px 骨架
  → label() 连通分量标记              ← 问题从这里开始
  → _order_points_nearest_neighbor()   ← 这里产生锯齿
  → SVG polyline
```

**关键链路**：

1. `skeletonize` 对粗线条（5-30px 宽的手绘笔画）和交叉区域产生**分支骨架**
2. 图片中的线条通过交叉点（如脑部曲线交叉、金字塔边角相交）**全部连通**
3. `label()` 将整个骨架标记为**一个巨大的连通分量**（数千个像素点）
4. `_order_points_nearest_neighbor()` 对这数千个点做最近邻排序

最近邻排序在分支骨架上的行为：

```
骨架结构（示意）:

    A ─── B ─── C
              │
              D
              │
              E

numpy 返回点的顺序（按行扫描）: A, B, C, D, E（如果它们在不同行）

最近邻从 A 开始:
  A → B（最近）→ C（最近）→ D（需要折返到分支点 B 附近）→ E
  
实际在复杂骨架中，分支密集交错，最近邻不断在相邻的平行分支间跳跃，
产生锯齿路径。
```

### 2-3. 对渲染效果的影响

```
锯齿路径                           自然路径
─────────────────                 ─────────────────
                                  
→→→→→→→→→→→→→  y=100            ╭───╮
←←←←←←←←←←←←←  y=102            │   │  ← 手沿轮廓移动
→→→→→→→→→→→→→  y=104            │   │
←←←←←←←←←←←←←  y=106            ╰───╯
                                  
蒙版效果: 从上到下一行行扫         蒙版效果: 沿线条逐步揭示
手的位置: 左右来回跳跃(不可见)      手的位置: 沿线条平滑移动 ✓
```

---

## 三、修复方案：交叉点拆分 + 链式遍历

### 3-1. 核心思路

```
旧流程:
  骨架 → 连通分量(一大坨) → 最近邻排序(锯齿) → 一条巨大路径

新流程:
  骨架 → 检测交叉点 → 移除交叉点(骨架分裂) → 多个简单链 → 逐链遍历 → 多条自然路径
```

**不改 Remotion 渲染组件**（`MaskRevealAnimation.tsx`），**只改路径提取脚本**（`extract_drawing_paths.py`）。输出格式不变，路径质量提升。

### 3-2. 算法详解

#### Step 1: 检测交叉点（Junction Detection）

```python
# 用 3x3 卷积核计算每个骨架像素的 8-连通邻居数
kernel = [[1,1,1],
          [1,0,1],
          [1,1,1]]
neighbor_count = convolve(skeleton, kernel)

# 邻居数 > 2 = 交叉点
#   普通线段上的像素: 2 个邻居（前后各一）
#   端点: 1 个邻居
#   T 型交叉: 3 个邻居
#   十字交叉: 4 个邻居
junctions = (neighbor_count > 2) & skeleton
```

骨架交叉点示意：

```
  ·               ·
  · · · J · · ·   J = junction (3 neighbors)
  ·               
  ·
```

#### Step 2: 移除交叉点，骨架分裂

```python
branch_mask = skeleton & ~junctions
```

移除交叉点后，连通的骨架在每个交叉点处断开，分裂为多个独立的简单链：

```
Before:                  After removing J:
  ·                        ·
  · · · J · · ·            · · ·   · · ·   (两个独立分支)
  ·                        ·
  ·                        ·               (一个独立分支)
```

#### Step 3: 链式遍历（Chain Walk）

每个分裂后的连通分量是一条简单链（无分支），可以从端点开始逐像素遍历：

```python
def walk_chain(mask):
    # 1. 找端点（邻居数 ≤ 1）
    # 2. 从最上方的端点开始
    # 3. 每步移动到唯一的未访问邻居
    # 4. 链结束时停止
```

与最近邻排序的区别：
- **最近邻**：在整个点集中搜索最近点 → 可能跳到其他分支
- **链式遍历**：只在当前链的相邻像素中移动 → 严格沿链前进

#### Step 4: RDP 简化 + SVG 输出

保持现有的 Ramer-Douglas-Peucker 简化和 SVG polyline 输出逻辑不变。

### 3-3. 各场景的效果预期

| 场景 | 旧: 路径数 × 平均长度 | 新: 路径数 × 平均长度 | 效果变化 |
|------|----------------------|----------------------|---------|
| scene1 (人+钟+钱) | 53 条，含锯齿 | ~100-200 条短分支 | 手沿人物/时钟/钞票轮廓移动 |
| scene2 (脑) | 82 条，path[0] 11771 字符 | ~200-400 条曲线分支 | 手沿脑部曲线移动 |
| scene3 (金字塔) | 14 条，path[0] 15734 字符 | ~50-100 条线段分支 | 手沿三角形边/横线移动 |

### 3-4. 边界情况处理

| 情况 | 处理 |
|------|------|
| 单条曲线（无交叉） | 无交叉点需移除，整条骨架为一个分量，walk_chain 从端点遍历到另一端 ✓ |
| 多线条交叉（脑部曲线） | 每个交叉点拆分，每段曲线独立遍历，画手依次画每段 ✓ |
| 闭合圈（时钟圆圈） | 无端点，从最上方像素开始绕圈遍历 ✓ |
| 粗线条（金字塔边框） | skeletonize 已将粗线简化为 1px 中心线，无分支，正常遍历 ✓ |
| 交叉点移除造成的 1px 间隙 | brushRadius=50（直径 100px）轻松覆盖，视觉上完全无缝 ✓ |
| 极短分支（<5px 噪点） | 过滤掉，不生成路径 ✓ |

---

## 四、代码改动

### 4-1. 改动范围

| 文件 | 改动 | 说明 |
|------|------|------|
| `scripts/extract_drawing_paths.py` | 替换排序算法 | **唯一改动文件** |

Remotion 组件（`MaskRevealAnimation.tsx`、`WhiteboardVideo.tsx`）、数据格式（`drawing-paths.json`）、管线流程（`make_video.py`）均不需要修改。

### 4-2. 函数级改动清单

**删除**：
- `_order_points_nearest_neighbor()` — 最近邻排序（产生锯齿的根源）
- `_nearest_neighbor_sort()` — 辅助排序函数

**新增**：
- `_extract_branches(skeleton)` — 交叉点检测 + 骨架拆分 + 连通分量标记
- `_walk_chain(mask)` — 从端点遍历简单链

**修改**：
- `extract_drawing_paths()` — 主函数，调用 `_extract_branches` 替代原来的 per-component nearest-neighbor

**保留不变**：
- `_simplify_path()` — RDP 路径简化
- `_points_to_svg_polyline()` — 坐标 → SVG path d
- `_assign_paths_to_elements()` — 按元素 bbox 分组
- `extract_all_scenes()` / `main()` — 批量处理入口

### 4-3. 新增函数伪代码

```python
def _extract_branches(skeleton):
    """在交叉点拆分骨架为简单分支链。"""
    
    # 1. 计算 8-连通邻居数
    kernel = np.array([[1,1,1],[1,0,1],[1,1,1]])
    nbr_count = convolve(skeleton, kernel) * skeleton
    
    # 2. 标记交叉点（邻居数 > 2）
    junctions = (nbr_count > 2) & skeleton
    
    # 3. 移除交叉点
    branch_mask = skeleton & ~junctions
    
    # 4. 标记连通分量
    labeled, n = label(branch_mask, structure=ones_3x3)
    
    # 5. 遍历每个分量
    branches = []
    for i in range(1, n + 1):
        ordered = _walk_chain(labeled == i)
        if len(ordered) >= 3:
            branches.append(ordered)
    
    return branches


def _walk_chain(mask):
    """从端点遍历一条简单链。"""
    points = set(所有前景像素坐标)
    
    # 找端点（邻居数 ≤ 1），取最上方的
    endpoints = [p for p in points if count_neighbors(p) <= 1]
    start = min(endpoints, key=lambda p: (p.y, p.x))
    
    # 逐步遍历
    ordered = [start]
    visited = {start}
    while True:
        next = 在 current 的 8 邻域中找未访问的 points 成员
        if not next:
            break
        ordered.append(next)
        visited.add(next)
    
    return ordered
```

---

## 五、验证步骤

### 5-1. 路径数据验证

```bash
# 重新提取路径
cd /home/admin/workspace/test_videp
python scripts/extract_drawing_paths.py \
  -s output/ai-asset-20260710/storyboard.json \
  -i output/ai-asset-20260710/images \
  -o output/ai-asset-20260710

# 检查路径统计
python3 -c "
import json
with open('output/ai-asset-20260710/drawing_paths/drawing-paths.json') as f:
    data = json.load(f)
for sid, sd in data.items():
    paths = sd['paths']
    avg_len = sum(len(p['d']) for p in paths) / max(1, len(paths))
    print(f'{sid}: {len(paths)} paths, avg d_len={avg_len:.0f}')
    # 检查前 3 条路径的坐标是否连续（不再锯齿）
    for i, p in enumerate(paths[:3]):
        print(f'  [{i}] {p[\"d\"][:120]}...')
"
```

**预期**：
- 路径数量增加（从 14-82 条增到 50-400 条）
- 单条路径长度减小（从数千字符减到数十~数百字符）
- 坐标连续递变（不再左右跳跃）

### 5-2. 视频渲染验证

```bash
# 部署资源到 Remotion
python scripts/deploy_resources.py \
  -s output/ai-asset-20260710/storyboard.json \
  -o output/ai-asset-20260710

# 渲染视频
cd remotion-project
npx remotion render src/index.tsx VideoMain ../output/ai-asset-20260710/video_test.mp4 --overwrite
```

**预期效果**：
- 画面沿着线条轮廓逐步出现（不再是从上到下扫描）
- 手（writing-hand-small.png）沿线条平滑移动，像在画画
- 每个元素（人物、时钟、脑、金字塔）按时间轴依次绘制

---

## 六、风险评估

| 风险 | 影响 | 概率 | 缓解 |
|------|------|------|------|
| 分支过多导致路径碎片化 | 每条路径太短，手移动太快 | 低 | 过滤 <5px 短分支；brushRadius=50 覆盖间隙 |
| 交叉点密集区域间隙多 | 蒙版在交叉点处有小空洞 | 极低 | 交叉点最多 1px，100px 笔刷直径远大于间隙 |
| 闭合环路遍历不完整 | 圆形/环形路径可能断裂 | 低 | walk_chain 对环路从任意点开始绕行，应遍历完整 |
| 路径数量大增影响渲染性能 | Remotion 渲染变慢 | 低 | 每条路径只是 SVG path，数百条在 Chromium 中无压力 |
