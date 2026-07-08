import React from "react";
import {
  AbsoluteFill, Audio, Img, Sequence, staticFile,
  useCurrentFrame, interpolate, spring, useVideoConfig,
} from "remotion";
import "@fontsource/zcool-kuaile";

import sceneConfig from "./scene-config.json";
import timeline from "./timeline.json";

// ========== Design Tokens ==========
const C: Record<string, any> = {
  bg: "#F5F5F0", grid: "#E0DDD5",
  pink: { bg: "#FDE8E8", border: "#E8A0A0" },
  blue: { bg: "#E0EEFF", border: "#8BB8E8" },
  yellow: { bg: "#FFF5E0", border: "#E8C878" },
  dark: { bg: "#2D3748", border: "#1A202C" },
  title: "#2D3748", body: "#4A5568", accent: "#C05050",
  white: "#FFFFFF", arrow: "#6B7280",
};
const F = "'ZCOOL KuaiLe', sans-serif";
const FPS = 30;
const NARRATION_VOL = sceneConfig.meta.ttsProvider === "tencent" ? 5.0 : 1.0;

// ========== Auto Layout Engine ==========
const CONTENT_TOP = 80;
const CONTENT_BOTTOM = 1600;
const CONTENT_HEIGHT = CONTENT_BOTTOM - CONTENT_TOP;
const CANVAS_WIDTH = 1080;
const H_PADDING = 80;
const ITEM_GAP = 40;

const TYPE_HEIGHT: Record<string, number> = {
  title: 80, box: 80, svg: 250, image: 200, stamp: 120, arrow: 40, badge: 60,
};

function layoutScene(elements: any[]) {
  const rowMap: Record<number, { idx: number; elem: any }[]> = {};
  elements.forEach((e, idx) => {
    (rowMap[e.row] ??= []).push({ idx, elem: e });
  });
  const rowKeys = Object.keys(rowMap).map(Number).sort((a, b) => a - b);
  const rowCount = rowKeys.length;
  const rowHeights = rowKeys.map(key =>
    Math.max(...rowMap[key].map(({ elem }) => {
      const base = TYPE_HEIGHT[elem.type] || 80;
      return (elem.type === "svg" || elem.type === "image") ? base * (elem.scale || 1) : base;
    }))
  );
  const totalContentH = rowHeights.reduce((a, b) => a + b, 0);
  const gap = Math.max(30, (CONTENT_HEIGHT - totalContentH) / (rowCount + 1));

  let currentY = CONTENT_TOP + gap;
  const rowCenters = rowHeights.map(h => {
    const cy = currentY + h / 2;
    currentY += h + gap;
    return cy;
  });

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

// ========== Components ==========
const Grid: React.FC = () => {
  const lines: React.ReactNode[] = [];
  for (let x = 0; x <= 1080; x += 100)
    lines.push(<line key={`v${x}`} x1={x} y1={0} x2={x} y2={1920} stroke={C.grid} strokeWidth={0.5} />);
  for (let y = 0; y <= 1920; y += 100)
    lines.push(<line key={`h${y}`} x1={0} y1={y} x2={1080} y2={y} stroke={C.grid} strokeWidth={0.5} />);
  return <svg width={1080} height={1920} style={{ position: "absolute" }}>{lines}</svg>;
};

const Fade: React.FC<{ delay?: number; children: React.ReactNode }> = ({ delay = 0, children }) => {
  const f = useCurrentFrame();
  const d = delay * FPS;
  const o = interpolate(f, [d, d + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ty = interpolate(f, [d, d + 12], [40, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ opacity: o, transform: `translateY(${ty}px)` }}>{children}</div>;
};

const Pop: React.FC<{ delay?: number; children: React.ReactNode }> = ({ delay = 0, children }) => {
  const f = useCurrentFrame();
  const d = Math.floor(delay * FPS);
  const s = spring({ frame: f - d, fps: FPS, config: { stiffness: 120, damping: 14 } });
  return <div style={{ transform: `scale(${f < d ? 0 : s})`, transformOrigin: "center" }}>{children}</div>;
};

const StampIn: React.FC<{ delay?: number; children: React.ReactNode }> = ({ delay = 0, children }) => {
  const f = useCurrentFrame();
  const d = Math.floor(delay * FPS);
  const s = spring({ frame: f - d, fps: FPS, config: { stiffness: 200, damping: 12 } });
  const scale = f < d ? 0 : interpolate(s, [0, 1], [2.5, 1]);
  const rotate = f < d ? 0 : interpolate(s, [0, 1], [-30, 0]);
  return (
    <div style={{
      transform: `scale(${f < d ? 0 : scale}) rotate(${rotate}deg)`,
      transformOrigin: "center",
      opacity: f < d ? 0 : 1,
    }}>
      {children}
    </div>
  );
};

const RoughBox: React.FC<{
  w: number; h: number; fill: string; stroke: string; seed?: number;
}> = ({ w, h, fill, stroke, seed = 42 }) => {
  // Use inline SVG instead of canvas to avoid flickering in Remotion
  const r = 8;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      <rect
        x={r} y={r} width={w - r * 2} height={h - r * 2}
        rx={8} ry={8}
        fill={fill} stroke={stroke} strokeWidth={2.5}
      />
      <rect
        x={r + 3} y={r + 3} width={w - r * 2 - 6} height={4}
        rx={2} fill="rgba(255,255,255,0.25)"
      />
    </svg>
  );
};

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

const ArrowElement: React.FC<{ w: number; seed?: number }> = ({ w, seed = 42 }) => {
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

const Subtitle: React.FC<{
  segments: Array<{ text: string; startTime: number; endTime: number }>;
  duration: number;
}> = ({ segments, duration }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;
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

const Watermark: React.FC = () => (
  <div style={{
    position: "absolute", top: 30, right: 40,
    fontFamily: F, fontSize: 28, color: C.body, opacity: 0.5,
  }}>
    0x00AI
  </div>
);

const Cover: React.FC<{ src: string }> = ({ src }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <img src={src} style={{
        width: 1080, height: 1920, objectFit: "cover",
      }} />
    </AbsoluteFill>
  );
};

// ========== Render Element ==========
function renderElement(e: any) {
  const style: React.CSSProperties = {
    position: "absolute",
    left: e._x,
    top: e._y - (e._h || 80) / 2,
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
    case "image": {
      const sc = e.scale || 1;
      const imgSize = Math.round(200 * sc);
      return (
        <div style={{ ...style, height: imgSize }}>
          <Img src={staticFile(e.src)} style={{ width: imgSize, height: imgSize, objectFit: "contain" }} />
        </div>
      );
    }
    case "stamp": {
      // 印章样式：圆形+粗边框+衬线体+微倾斜，参照video-newspaper
      const stampColors: Record<string, { border: string; text: string }> = {
        "夯": { border: "#C02020", text: "#C02020" },
        "顶级": { border: "#B8860B", text: "#B8860B" },
        "人上人": { border: "#1565C0", text: "#1565C0" },
        "NPC": { border: "#616A6B", text: "#616A6B" },
        "拉完了": { border: "#2C3E50", text: "#2C3E50" },
      };
      const sc = e.scale || 1;
      const sz = Math.round(140 * sc);
      const colors = stampColors[e.content] || stampColors["NPC"];
      const fontSize = e.content.length <= 2 ? Math.round(sz * 0.36) : Math.round(sz * 0.26);
      return (
        <div style={{ ...style, height: sz }}>
          <div style={{
            width: sz, height: sz,
            border: `4px solid ${colors.border}`,
            borderRadius: "50%",
            display: "flex", alignItems: "center", justifyContent: "center",
            transform: "rotate(-15deg)",
          }}>
            <span style={{
              fontFamily: "'Noto Serif SC', serif",
              fontSize, color: colors.text,
              fontWeight: 900, lineHeight: 1.2, textAlign: "center",
              whiteSpace: "pre-line",
            }}>
              {e.content}
            </span>
          </div>
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

// ========== Main Composition ==========
// 这是"canonical 数据驱动渲染器"——所有视频数据来自 scene-config.json 和 timeline.json
// 重命名这个组件时，同步更新 index.tsx 的 component 引用
export const LightclawaceVideo: React.FC = () => {
  const totalF = timeline.totalFrames;
  const topic = (sceneConfig as any).meta?.topic || "lightclawace";

  const bgmVolume = (frame: number) => {
    const fadeIn = interpolate(frame, [0, 30], [0, 0.03], { extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [totalF - 30, totalF], [0.03, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return Math.min(fadeIn, fadeOut);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Grid />
      <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />
      <Watermark />

      {/* Cover */}
      {timeline.cover && sceneConfig.meta.cover && (
        <Sequence from={0} durationInFrames={timeline.cover.durationFrames}>
          <Cover src={staticFile(`assets/cover_${topic}.png`)} />
        </Sequence>
      )}

      {/* Scenes */}
      {timeline.scenes.map((tScene, i) => {
        const sConfig = sceneConfig.scenes[i];
        const laid = layoutScene(sConfig.elements);
        const sceneDur = sConfig.duration;
        const subs = sConfig.subtitles;
        const subCount = subs.length;
        const subSegs = subs.map((s: any, si: number) => ({
          text: s.text,
          startTime: (si / subCount) * sceneDur,
          endTime: ((si + 1) / subCount) * sceneDur,
        }));

        return (
          <Sequence key={tScene.id} from={tScene.startFrame} durationInFrames={tScene.durationFrames}>
            <AbsoluteFill style={{ backgroundColor: C.bg }}>
              <Grid />
              <Audio src={staticFile(sConfig.audio)} volume={NARRATION_VOL} />

              {laid.map((config, j) => {
                const trigger = sConfig.elements[j].trigger;
                const delay = (trigger / subCount) * sceneDur;
                const anim = sConfig.elements[j].animation;
                const AnimComp = anim === "stampIn" ? StampIn : anim === "pop" ? Pop : Fade;
                return (
                  <AnimComp key={j} delay={delay}>
                    {renderElement(config)}
                  </AnimComp>
                );
              })}

              <Subtitle segments={subSegs} duration={sceneDur} />
              <ProgressBar current={i + 1} total={timeline.scenes.length} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
