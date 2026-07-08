# 组件库实现参考

所有组件内联在单个视频 `.tsx` 文件中。**遇到新视频，首选「照抄 LightclawaceVideo.tsx」，只替换数据 import 和组件名。**

## Design Tokens

```tsx
const C: Record<string, any> = {
  bg: "#F5F5F0", grid: "#E0DDD5",
  pink:   { bg: "#FDE8E8", border: "#E8A0A0" },
  blue:   { bg: "#E0EEFF", border: "#8BB8E8" },
  yellow: { bg: "#FFF5E0", border: "#E8C878" },
  dark:   { bg: "#2D3748", border: "#1A202C" },
  title: "#2D3748", body: "#4A5568", accent: "#C05050",
  white: "#FFFFFF", arrow: "#6B7280",
};
const F = "'ZCOOL KuaiLe', sans-serif";
const FPS = 30;

// 旁白音量：腾讯云 TTS 输出偏小，实测 5.0 刚好盖过 BGM
const NARRATION_VOL = sceneConfig.meta.ttsProvider === "tencent" ? 5.0 : 1.0;
```

## Grid（方格纸背景）

```tsx
const Grid: React.FC = () => {
  const lines: React.ReactNode[] = [];
  for (let x = 0; x <= 1080; x += 100)
    lines.push(<line key={`v${x}`} x1={x} y1={0} x2={x} y2={1920} stroke={C.grid} strokeWidth={0.5} />);
  for (let y = 0; y <= 1920; y += 100)
    lines.push(<line key={`h${y}`} x1={0} y1={y} x2={1080} y2={y} stroke={C.grid} strokeWidth={0.5} />);
  return <svg width={1080} height={1920} style={{ position: "absolute" }}>{lines}</svg>;
};
```

> Grid 必须在**每个 Sequence 内重新渲染**（而不是只放在外层 AbsoluteFill 里）。原因：Remotion 的 Sequence 在活跃期间会叠在外层上方，如果 Sequence 内不画背景，场景切换的 PAD 间隙会出现黑帧。

## Fade / Pop（入场动画）

```tsx
const Fade: React.FC<{ delay?: number; children: React.ReactNode }> = ({ delay = 0, children }) => {
  const f = useCurrentFrame();
  const d = delay * FPS;
  const o  = interpolate(f, [d, d + 12], [0, 1],  { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ty = interpolate(f, [d, d + 12], [40, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ opacity: o, transform: `translateY(${ty}px)` }}>{children}</div>;
};

const Pop: React.FC<{ delay?: number; children: React.ReactNode }> = ({ delay = 0, children }) => {
  const f = useCurrentFrame();
  const d = Math.floor(delay * FPS);
  const s = spring({ frame: f - d, fps: FPS, config: { stiffness: 120, damping: 14 } });
  return <div style={{ transform: `scale(${f < d ? 0 : s})`, transformOrigin: "center" }}>{children}</div>;
};
```

`delay` 是 **Sequence 内的相对秒数**。`useCurrentFrame()` 在 Sequence 内返回的是从 0 开始的相对帧号，所以直接 `delay * FPS` 即可，**不要加全局偏移**。

## RoughBox（内联 SVG 矩形，不用 roughjs）

```tsx
// 用纯 SVG 替代 roughjs。roughjs 每帧重算路径会在 Remotion 中闪烁。
const RoughBox: React.FC<{
  w: number; h: number; fill: string; stroke: string; seed?: number;
}> = ({ w, h, fill, stroke }) => {
  const r = 8;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      <rect
        x={r} y={r} width={w - r * 2} height={h - r * 2}
        rx={8} ry={8}
        fill={fill} stroke={stroke} strokeWidth={2.5}
      />
      {/* 高光：顶部一条浅白横条，伪手绘质感 */}
      <rect
        x={r + 3} y={r + 3} width={w - r * 2 - 6} height={4}
        rx={2} fill="rgba(255,255,255,0.25)"
      />
    </svg>
  );
};
```

## BoxElement（带文字的矩形）

```tsx
const BoxElement: React.FC<{
  content: string; color: string; w: number; seed?: number;
}> = ({ content, color, w, seed = 42 }) => {
  const colors = C[color] || C.blue;
  const isDark = color === "dark";
  return (
    <div style={{
      width: w, minHeight: 60,
      display: "flex", alignItems: "center", justifyContent: "center",
      position: "relative",
    }}>
      <RoughBox w={w} h={80} fill={colors.bg} stroke={colors.border} seed={seed} />
      <span style={{
        position: "absolute",
        fontFamily: F, fontSize: 36, color: isDark ? C.white : C.body,
        lineHeight: 1.3, textAlign: "center", padding: "8px 16px",
      }}>
        {content}
      </span>
    </div>
  );
};
```

## ArrowElement（方块箭头）

```tsx
const ArrowElement: React.FC<{ w: number; seed?: number }> = ({ w }) => {
  const bodyW = Math.max(20, w - 30);
  return (
    <div style={{ width: w, height: 40, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{
        width: bodyW, height: 14, backgroundColor: C.arrow, borderRadius: 4,
        position: "relative",
      }}>
        <div style={{
          position: "absolute", right: -12, top: -8,
          width: 0, height: 0,
          borderLeft: "18px solid " + C.arrow,
          borderTop: "15px solid transparent",
          borderBottom: "15px solid transparent",
        }} />
      </div>
    </div>
  );
};
```

## Subtitle（字幕）

字幕时间采用**按句数均分**策略（简单稳定，不依赖 TTS 精确断句）：

```tsx
const Subtitle: React.FC<{
  segments: Array<{ text: string; startTime: number; endTime: number }>;
  duration: number;
}> = ({ segments }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps; // Sequence 内相对秒数

  const currentSeg = segments.find(
    (s) => currentTime >= s.startTime && currentTime < s.endTime
  );
  if (!currentSeg) return null;

  return (
    <div style={{
      position: "absolute", bottom: 140, left: 40, right: 40,
      display: "flex", justifyContent: "center",
    }}>
      <div style={{
        backgroundColor: "rgba(45, 55, 72, 0.85)",
        borderRadius: 16, padding: "16px 32px", maxWidth: 960,
      }}>
        <span style={{ fontFamily: F, fontSize: 36, color: "#FFFFFF", lineHeight: 1.4 }}>
          {currentSeg.text}
        </span>
      </div>
    </div>
  );
};
```

主组件内构造 segments：

```tsx
const sceneDur = sConfig.duration;
const subs = sConfig.subtitles;
const subCount = subs.length;
const subSegs = subs.map((s: any, si: number) => ({
  text: s.text,
  startTime: (si / subCount) * sceneDur,
  endTime: ((si + 1) / subCount) * sceneDur,
}));
```

## ProgressBar（进度条）

```tsx
const ProgressBar: React.FC<{ current: number; total: number }> = ({ current, total }) => (
  <div style={{ position: "absolute", bottom: 60, left: 60, width: 960 }}>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{
          fontFamily: F, fontSize: 20,
          color: i + 1 === current ? C.accent : C.body,
          opacity: i < current ? 1 : 0.3,
        }}>
          {i + 1}/{total}
        </div>
      ))}
    </div>
    <div style={{ width: "100%", height: 6, borderRadius: 3, backgroundColor: "rgba(0,0,0,0.1)" }}>
      <div style={{
        width: `${(current / total) * 100}%`,
        height: "100%", borderRadius: 3, backgroundColor: C.accent,
      }} />
    </div>
  </div>
);
```

## Watermark（水印）

```tsx
const Watermark: React.FC = () => (
  <div style={{
    position: "absolute", top: 30, right: 40,
    fontFamily: F, fontSize: 28, color: C.body, opacity: 0.5,
  }}>
    0x00AI
  </div>
);
```

## Cover（封面）

```tsx
const Cover: React.FC<{ src: string }> = ({ src }) => (
  <AbsoluteFill style={{ backgroundColor: C.bg }}>
    <img src={src} style={{ width: 1080, height: 1920, objectFit: "cover" }} />
  </AbsoluteFill>
);
```

## renderElement（根据 type 渲染）

```tsx
function renderElement(e: any) {
  const style: React.CSSProperties = {
    position: "absolute",
    left: e._x,
    top: e._y - (e._h || 80) / 2, // _y 是行中心
    width: e._w,
    height: e._h || 80,
    display: "flex", alignItems: "center", justifyContent: "center",
  };

  switch (e.type) {
    case "title":
      return (
        <div style={{ ...style, justifyContent: "center" }}>
          <span style={{ fontFamily: F, fontSize: 64, color: C.title, lineHeight: 1.3, textAlign: "center" }}>
            {e.content}
          </span>
        </div>
      );
    case "box":
      return (
        <div style={style}>
          <BoxElement content={e.content} color={e.color} w={e._w} seed={e.seed ?? (e.row * 100 + 42)} />
        </div>
      );
    case "svg": {
      const sc = e.scale || 1;
      const svgSize = Math.round(250 * sc);
      return (
        <div style={{ ...style, height: svgSize }}>
          <Img src={staticFile(e.src)} style={{ width: svgSize, height: svgSize, objectFit: "contain" }} />
        </div>
      );
    }
    case "arrow":
      return (
        <div style={{ ...style, height: 40 }}>
          <ArrowElement w={Math.min(e._w, 60)} seed={e.seed ?? 42} />
        </div>
      );
    case "badge":
      return (
        <div style={style}>
          <div style={{
            width: 60, height: 60, borderRadius: "50%",
            backgroundColor: C[e.color]?.bg || C.accent,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: F, fontSize: 28, color: C.white, fontWeight: "bold",
          }}>
            {e.content}
          </div>
        </div>
      );
    default:
      return null;
  }
}
```
