import React, { useEffect, useRef } from "react";
import { AbsoluteFill } from "remotion";
import rough from "roughjs";
import "@fontsource/zcool-kuaile";

// ========== Design Tokens ==========
const colors = {
  background: "#F5F5F0",
  gridLine: "#E0DDD5",
  pink: { bg: "#FDE8E8", border: "#E8A0A0" },
  blue: { bg: "#E0EEFF", border: "#8BB8E8" },
  yellow: { bg: "#FFF5E0", border: "#E8C878" },
  text: { title: "#2D3748", body: "#4A5568", emphasis: "#C05050" },
  arrow: "#6B7280",
};

const fontFamily = "'ZCOOL KuaiLe', 'PingFang SC', sans-serif";

// ========== Grid Paper Background ==========
const GridPaper: React.FC = () => {
  const gridSize = 100;
  const lines: React.ReactNode[] = [];
  for (let x = 0; x <= 1080; x += gridSize) {
    lines.push(
      <line key={`v${x}`} x1={x} y1={0} x2={x} y2={1920} stroke={colors.gridLine} strokeWidth={0.5} />
    );
  }
  for (let y = 0; y <= 1920; y += gridSize) {
    lines.push(
      <line key={`h${y}`} x1={0} y1={y} x2={1080} y2={y} stroke={colors.gridLine} strokeWidth={0.5} />
    );
  }
  return (
    <svg width={1080} height={1920} style={{ position: "absolute", top: 0, left: 0 }}>
      {lines}
    </svg>
  );
};

// ========== Hand-Drawn Box (roughjs) ==========
const HandDrawnBox: React.FC<{
  x: number; y: number; width: number; height: number;
  fillColor: string; strokeColor: string;
  dashed?: boolean; seed?: number;
}> = ({ x, y, width, height, fillColor, strokeColor, dashed, seed }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const rc = rough.canvas(canvas);
    rc.rectangle(10, 10, width - 20, height - 20, {
      fill: fillColor,
      fillStyle: "solid",
      stroke: strokeColor,
      strokeWidth: 2,
      roughness: 1.5,
      bowing: 1,
      seed: seed || 42,
      strokeLineDash: dashed ? [8, 4] : undefined,
    });
  }, [width, height, fillColor, strokeColor, dashed, seed]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ position: "absolute", left: x, top: y }}
    />
  );
};

// ========== Simple Text ==========
const Title: React.FC<{ text: string; x: number; y: number; size?: number; color?: string }> = ({
  text, x, y, size = 48, color = colors.text.title,
}) => (
  <div style={{
    position: "absolute", left: x, top: y,
    fontFamily,
    fontSize: size, fontWeight: 700, color,
    lineHeight: 1.3,
  }}>
    {text}
  </div>
);

const Body: React.FC<{ text: string; x: number; y: number; size?: number; color?: string; maxWidth?: number }> = ({
  text, x, y, size = 28, color = colors.text.body, maxWidth,
}) => (
  <div style={{
    position: "absolute", left: x, top: y,
    fontFamily,
    fontSize: size, fontWeight: 400, color,
    lineHeight: 1.5, maxWidth,
  }}>
    {text}
  </div>
);

// ========== Number Badge ==========
const NumberBadge: React.FC<{ num: number; x: number; y: number; color: string }> = ({
  num, x, y, color,
}) => (
  <div style={{
    position: "absolute", left: x, top: y,
    width: 44, height: 44, borderRadius: "50%",
    backgroundColor: color, display: "flex",
    alignItems: "center", justifyContent: "center",
    fontFamily,
    fontSize: 24, fontWeight: 700, color: "white",
  }}>
    {num}
  </div>
);

// ========== Hand-Drawn Block Arrow (粗胖实心箭头，像参考图) ==========
const HandDrawnArrow: React.FC<{
  x: number; y: number; width: number; height: number;
  direction?: "down" | "right"; seed?: number;
  color?: string;
}> = ({ x, y, width, height, direction = "down", seed = 500, color = colors.arrow }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const rc = rough.canvas(canvas);

    if (direction === "down") {
      // 粗胖的向下方块箭头（宽矩形身体 + 大三角头）
      const cx = width / 2;
      const bodyW = width * 0.35;
      const headW = width * 0.8;
      const bodyH = height * 0.5;
      const headH = height * 0.5;

      // 箭头身体（粗矩形）
      rc.rectangle(cx - bodyW / 2, 4, bodyW, bodyH, {
        fill: color, fillStyle: "solid",
        stroke: color, strokeWidth: 1.5,
        roughness: 0.8, seed,
      });
      // 箭头头部（大三角）
      rc.polygon([
        [cx - headW / 2, bodyH],
        [cx + headW / 2, bodyH],
        [cx, height - 4],
      ], {
        fill: color, fillStyle: "solid",
        stroke: color, strokeWidth: 1.5,
        roughness: 0.8, seed: seed + 1,
      });
    } else {
      // 粗胖的向右方块箭头
      const cy = height / 2;
      const bodyH = height * 0.35;
      const headH = height * 0.8;
      const bodyW = width * 0.5;
      const headW = width * 0.5;

      rc.rectangle(4, cy - bodyH / 2, bodyW, bodyH, {
        fill: color, fillStyle: "solid",
        stroke: color, strokeWidth: 1.5,
        roughness: 0.8, seed,
      });
      rc.polygon([
        [bodyW, cy - headH / 2],
        [bodyW, cy + headH / 2],
        [width - 4, cy],
      ], {
        fill: color, fillStyle: "solid",
        stroke: color, strokeWidth: 1.5,
        roughness: 0.8, seed: seed + 1,
      });
    }
  }, [width, height, direction, seed, color]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ position: "absolute", left: x, top: y }}
    />
  );
};

// ========== Tag / Badge ==========
const Tag: React.FC<{ text: string; x: number; y: number; bg: string; border: string }> = ({
  text, x, y, bg, border,
}) => (
  <div style={{
    position: "absolute", left: x, top: y,
    padding: "8px 20px", borderRadius: 8,
    backgroundColor: bg, border: `2px solid ${border}`,
    fontFamily,
    fontSize: 26, fontWeight: 600, color: colors.text.title,
  }}>
    {text}
  </div>
);

// ========== Illustration Placeholder (模拟贴图效果) ==========
const IllustrationPlaceholder: React.FC<{
  x: number; y: number; width: number; height: number;
  label: string; seed?: number;
}> = ({ x, y, width, height, label, seed = 600 }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const rc = rough.canvas(canvas);
    // 圆形底座
    rc.circle(width / 2, height / 2 - 15, Math.min(width, height) * 0.7, {
      fill: "#E0EEFF",
      fillStyle: "solid",
      stroke: colors.blue.border,
      strokeWidth: 3,
      roughness: 1.2,
      seed,
    });
    // 内部装饰线条（模拟复杂图标）
    const cx = width / 2;
    const cy = height / 2 - 15;
    const r = Math.min(width, height) * 0.2;
    // 小圆点阵列
    for (let i = 0; i < 5; i++) {
      const angle = (i / 5) * Math.PI * 2 - Math.PI / 2;
      const px = cx + r * Math.cos(angle);
      const py = cy + r * Math.sin(angle);
      rc.circle(px, py, 14, {
        fill: i % 2 === 0 ? "#E8A0A0" : "#8BB8E8",
        fillStyle: "solid",
        stroke: "#2D3748",
        strokeWidth: 2,
        roughness: 0.8,
        seed: seed + i + 10,
      });
      // 连线到中心
      rc.line(cx, cy, px, py, {
        stroke: "#2D3748",
        strokeWidth: 2.5,
        roughness: 0.6,
        seed: seed + i + 20,
      });
    }
    // 节点之间的连线
    for (let i = 0; i < 5; i++) {
      const a1 = (i / 5) * Math.PI * 2 - Math.PI / 2;
      const a2 = ((i + 2) / 5) * Math.PI * 2 - Math.PI / 2;
      rc.line(
        cx + r * Math.cos(a1), cy + r * Math.sin(a1),
        cx + r * Math.cos(a2), cy + r * Math.sin(a2),
        { stroke: "#2D3748", strokeWidth: 2, roughness: 0.6, seed: seed + i + 30 }
      );
    }
    // 中心点
    rc.circle(cx, cy, 16, {
      fill: "#FDE8E8", fillStyle: "solid",
      stroke: "#2D3748", strokeWidth: 2, roughness: 0.8, seed: seed + 50,
    });
  }, [width, height, seed]);

  return (
    <div style={{ position: "absolute", left: x, top: y, textAlign: "center" }}>
      <canvas ref={canvasRef} width={width} height={height} />
      <div style={{
        fontFamily, fontSize: 26, color: colors.text.body,
        marginTop: -10,
      }}>
        {label}
      </div>
    </div>
  );
};

// ========== Main Prototype Scene ==========
export const Prototype: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      <GridPaper />

      {/* === 场景标题 === */}
      <Title text="单 Agent 架构的现状" x={80} y={80} size={64} />

      {/* === 插图区域：Agent 网络示意 === */}
      <IllustrationPlaceholder x={330} y={200} width={400} height={380} label="Agent 架构" seed={601} />

      {/* === 核心要点（框图 + 文字） === */}
      <HandDrawnBox x={60} y={640} width={960} height={480}
        fillColor={colors.pink.bg} strokeColor={colors.pink.border} dashed seed={101} />

      <NumberBadge num={1} x={100} y={700} color={colors.blue.border} />
      <Body text="全局 AgentRunner 单例" x={170} y={695} size={40} />
      <Body text="绑定唯一 WORKING_DIR" x={170} y={750} size={26} color="#999" />

      <NumberBadge num={2} x={100} y={840} color={colors.blue.border} />
      <Body text="身份 = md 文件" x={170} y={835} size={40} />
      <Body text="AGENTS.md / SOUL.md / IDENTITY.md" x={170} y={890} size={26} color="#999" />

      <NumberBadge num={3} x={100} y={980} color={colors.blue.border} />
      <Body text="无 Agent 注册表" x={170} y={975} size={40} />
      <Body text="无列表、无管理机制" x={170} y={1030} size={26} color="#999" />

      {/* === 大箭头 === */}
      <HandDrawnArrow x={480} y={1170} width={120} height={100} direction="down" seed={501} />

      {/* === 目标区域 === */}
      <HandDrawnBox x={60} y={1320} width={960} height={280}
        fillColor={colors.blue.bg} strokeColor={colors.blue.border} seed={201} />
      <Title text="目标：Agent CRUD" x={120} y={1360} size={64} />
      <Title text="+ Workspace 隔离" x={120} y={1440} size={64} />

      {/* === 底部留白：字幕 / 进度条 === */}
    </AbsoluteFill>
  );
};
