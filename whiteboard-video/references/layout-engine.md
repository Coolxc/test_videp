# 自动布局引擎

AI 只负责标记 `row` 编号，所有坐标由 `layoutScene()` 函数在渲染时实时计算。

## 画布分区（1080x1920）

```
y:    0 -   80   保留区（水印）
y:   80 - 1600   内容区（elements 在此范围内自动排布）
y: 1600 - 1780   字幕区
y: 1780 - 1920   进度条区
```

## 算法

1. 将场景的 elements 按 `row` 分组
2. 行按 row 编号从小到大排列
3. 每行高度 = 该行最高元素的估算高度（svg 考虑 `scale` 系数）
4. 剩余空间均匀分配为行间距（行数+1 个间距，最小 30px）
5. 每行内元素水平并排居中，间距 40px，宽度均分（可用 `widthScale` 微调）

## 各类型元素默认高度

| type | 默认高度 | 宽度 |
|------|---------|------|
| `title` | 80px | 占满行宽，文字居中 |
| `box` | 80px（估算） | 行内多个 box 等宽 |
| `svg` | 250px × scale | 250px × scale（正方形） |
| `arrow` | 40px | 最大 60px（超出 clamp 到 60） |
| `badge` | 60px | 60px |

## 参考实现（完整可直接 copy）

```tsx
const CONTENT_TOP = 80;
const CONTENT_BOTTOM = 1600;
const CONTENT_HEIGHT = CONTENT_BOTTOM - CONTENT_TOP;
const CANVAS_WIDTH = 1080;
const H_PADDING = 80;
const ITEM_GAP = 40;

const TYPE_HEIGHT: Record<string, number> = {
  title: 80, box: 80, svg: 250, arrow: 40, badge: 60,
};

function layoutScene(elements: any[]) {
  // 按 row 分组，同时记录原始索引（渲染时要用 trigger 对应原始顺序）
  const rowMap: Record<number, { idx: number; elem: any }[]> = {};
  elements.forEach((e, idx) => {
    (rowMap[e.row] ??= []).push({ idx, elem: e });
  });
  const rowKeys = Object.keys(rowMap).map(Number).sort((a, b) => a - b);
  const rowCount = rowKeys.length;

  // 每行实际高度
  const rowHeights = rowKeys.map(key =>
    Math.max(...rowMap[key].map(({ elem }) => {
      const base = TYPE_HEIGHT[elem.type] || 80;
      return elem.type === "svg" ? base * (elem.scale || 1) : base;
    }))
  );
  const totalContentH = rowHeights.reduce((a, b) => a + b, 0);
  const gap = Math.max(30, (CONTENT_HEIGHT - totalContentH) / (rowCount + 1));

  // 每行 y 中心
  let currentY = CONTENT_TOP + gap;
  const rowCenters = rowHeights.map(h => {
    const cy = currentY + h / 2;
    currentY += h + gap;
    return cy;
  });

  // 行内水平布局：按原索引放回，保证 `laid[j]` 对应 `elements[j]`
  const laid: any[] = new Array(elements.length);
  rowKeys.forEach((key, ri) => {
    const items = rowMap[key];
    const cy = rowCenters[ri];
    const availW = CANVAS_WIDTH - H_PADDING * 2;
    const itemW = (availW - ITEM_GAP * (items.length - 1)) / items.length;
    const totalW = itemW * items.length + ITEM_GAP * (items.length - 1);
    let sx = (CANVAS_WIDTH - totalW) / 2;

    items.forEach(({ idx, elem }) => {
      const ws = elem.widthScale || 1;
      const myW = itemW * ws;
      laid[idx] = { ...elem, _x: sx, _y: cy, _w: myW, _h: rowHeights[ri] };
      sx += myW + ITEM_GAP;
    });
  });
  return laid;
}
```

**关键点：**
- `laid` 数组**按原始索引排列**，不是按 row 顺序。这样 `laid[j]` 永远对应 `sceneConfig.scenes[i].elements[j]`，可以直接用 `scene.elements[j].trigger` 取动画 delay。
- `_x` 是左边界，`_y` 是**行中心**（渲染时需 `top = _y - _h/2`）。
- `_w` 已考虑 `widthScale`，渲染时直接用。
