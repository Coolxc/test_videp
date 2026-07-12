/**
 * MaskRevealAnimation.tsx - V2 蒙版揭示动画组件（轮廓驱动笔尖 + 空间邻近蒙版）
 *
 * V2 核心变化：
 *   - 笔尖跟踪只使用 outline 路径（Canny 轮廓）
 *   - 蒙版揭示使用 skeleton 路径（skeletonize 中心线），通过空间邻近
 *     映射跟随笔尖位置
 *   - 笔形态切换：marker（默认矢量）/ hand（手图片）/ debug（十字标）
 *   - 抬笔/落笔过渡（路径端点距离 > 50px 时）
 *   - 旋转系数从 0.3 → 1.0（marker 笔完全跟随方向）
 *
 * 数据流：
 *   drawingPaths[] -- 含 layer 字段（outline / skeleton）
 *   drawAtFrames[]  -- 每个 element 在场景内的起始帧
 *   drawDurations[] -- 每个 element 的绘制持续帧数
 */

import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";
import MarkerPen from "./MarkerPen";
import type { DrawingPathV2 } from "./types";

// ========== Types ==========

interface MaskRevealV2Props {
  imageSrc: string;                   // 场景 PNG 图片路径
  drawingPaths: DrawingPathV2[];      // 含 layer 字段的路径
  drawAtFrames: number[];             // 每组路径的起始帧（scene-relative）
  drawDurations: number[];            // 每组路径的绘制帧数
  elementIds?: string[];              // 元素 ID 顺序
  brushRadius?: number;               // 蒙版笔刷半径 (px)，默认 50
  penStyle?: "marker" | "hand" | "debug";  // 笔形态，默认 "marker"
  showHand?: boolean;                 // 兼容旧配置
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

// 抬笔/落笔阈值（px）
const PEN_LIFT_THRESHOLD = 50;
// 过渡帧数
const TRANSITION_FRAMES = 4;

// ========== Helpers ==========

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

const computeAngle = (d: string, progress: number): number => {
  const length = getLength(d);
  const currentLen = length * progress;
  const epsilon = Math.min(2, length * 0.01);

  const p1 = getPointAtLength(d, Math.max(0, currentLen - epsilon));
  const p2 = getPointAtLength(d, Math.min(length, currentLen + epsilon));

  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;

  if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) {
    return 0;
  }

  return Math.atan2(dy, dx) * (180 / Math.PI);
};

/**
 * 获取 SVG path 的中心点（估算）。
 */
function getPathCenter(d: string): { x: number; y: number } {
  try {
    const length = getLength(d);
    return getPointAtLength(d, length * 0.5);
  } catch {
    return { x: CANVAS_W / 2, y: CANVAS_H / 2 };
  }
}

// ========== Pen Tracking (Outline Only) ==========

interface ActivePathInfo {
  path: DrawingPathV2;
  pathStart: number;
  pathDuration: number;
  progress: number;
}

/**
 * 找到当前正在绘制的路径。
 * 只遍历 layer === "outline" 的路径。
 */
const findCurrentOutlinePath = (
  drawingPaths: DrawingPathV2[],
  frame: number,
  drawAtFrames: number[],
  drawDurations: number[],
  elementOrder: string[],
): ActivePathInfo | null => {
  // 只取 outline 路径（无 layer 字段的视为 outline，兼容旧数据）
  const outlinePaths = drawingPaths.filter(p => p.layer !== "skeleton");
  if (!outlinePaths.length) return null;

  for (let elemIdx = 0; elemIdx < elementOrder.length; elemIdx++) {
    const elemId = elementOrder[elemIdx];
    const elemStart = drawAtFrames[elemIdx] || 0;
    const elemDuration = drawDurations[elemIdx] || 1;
    const elemEnd = elemStart + elemDuration;

    if (frame < elemStart || frame >= elemEnd) continue;

    const elemPaths = outlinePaths.filter(p => p.elementId === elemId);
    if (!elemPaths.length) continue;

    // 按路径长度比例分配 element 内的绘制时间
    const totalPathLen = elemPaths.reduce(
      (sum, p) => {
        try { return sum + getLength(p.d); }
        catch { return sum + 1; }
      },
      0,
    );
    if (totalPathLen <= 0) continue;

    let cumLen = 0;
    for (const path of elemPaths) {
      let pathLen: number;
      try { pathLen = getLength(path.d); }
      catch { pathLen = 1; }

      const startRatio = cumLen / totalPathLen;
      const lengthRatio = pathLen / totalPathLen;
      const pathStart = elemStart + startRatio * elemDuration;
      const pathDuration = Math.max(1, lengthRatio * elemDuration);

      if (frame >= pathStart && frame < pathStart + pathDuration) {
        const progress = clamp(
          (frame - pathStart) / pathDuration, 0, 1,
        );
        return { path, pathStart, pathDuration, progress };
      }
      cumLen += pathLen;
    }
  }

  return null;
};

/**
 * 获取当前笔位置和方向信息（仅基于 outline 路径）。
 */
function usePenInfo(
  drawingPaths: DrawingPathV2[],
  frame: number,
  drawAtFrames: number[],
  drawDurations: number[],
  elementOrder: string[],
): {
  penPosition: { x: number; y: number } | null;
  penAngle: number;
  penOpacity: number;
  lastPenPosition: { x: number; y: number } | null;
} {
  return useMemo(() => {
    const currentPath = findCurrentOutlinePath(
      drawingPaths, frame, drawAtFrames, drawDurations, elementOrder,
    );

    if (!currentPath) {
      return { penPosition: null, penAngle: 0, penOpacity: 0, lastPenPosition: null };
    }

    const { path, pathStart, progress } = currentPath;
    const d = path.d;

    let length: number;
    try { length = getLength(d); }
    catch { return { penPosition: null, penAngle: 0, penOpacity: 0, lastPenPosition: null }; }
    if (length <= 0) {
      return { penPosition: null, penAngle: 0, penOpacity: 0, lastPenPosition: null };
    }

    const point = getPointAtLength(d, length * progress);

    // 角度平滑（3 帧）
    const angles = [-2, -1, 0].map((offset) => {
      const f = Math.max(0, frame + offset);
      const prog = clamp((f - pathStart) / currentPath.pathDuration, 0, 1);
      return computeAngle(d, prog);
    });
    const smoothedAngle = angles.reduce((a, b) => a + b) / angles.length;

    // 抬笔/落笔检测：路径端点距离
    const prevProgress = Math.max(0, progress - 0.02);
    const prevPoint = getPointAtLength(d, length * prevProgress);
    const dist = Math.hypot(point.x - prevPoint.x, point.y - prevPoint.y);
    const isLifting = dist > PEN_LIFT_THRESHOLD;

    // 过渡区：渐变透明
    const pathAge = frame - currentPath.pathStart;
    const isEntering = pathAge < TRANSITION_FRAMES && progress < 0.1;
    const isExiting = progress > 0.9 && pathAge > currentPath.pathDuration - TRANSITION_FRAMES;

    let penOpacity = 1;
    if (isEntering) {
      penOpacity = clamp(pathAge / TRANSITION_FRAMES, 0, 1);
    } else if (isExiting) {
      penOpacity = clamp((currentPath.pathDuration - pathAge) / TRANSITION_FRAMES, 0, 1);
    } else if (isLifting) {
      penOpacity = 0.3;
    }

    return {
      penPosition: point,
      penAngle: smoothedAngle,
      penOpacity,
      lastPenPosition: null,
    };
  }, [drawingPaths, frame, drawAtFrames, drawDurations, elementOrder]);
}

// ========== Skeleton Reveal (Spatial Proximity) ==========

/**
 * 计算骨架路径的空间邻近揭示进度。
 * 笔尖周围半径 R 内的骨架路径按距离渐进揭示。
 * 已揭示路径（reveal 曾达 1.0）保持揭示。
 */
function computeSkeletonReveal(
  skeletonPath: DrawingPathV2,
  penPosition: { x: number; y: number } | null,
  brushRadius: number,
  wasRevealed: boolean,
): number {
  if (!penPosition) return wasRevealed ? 1 : 0;
  if (wasRevealed) return 1; // 已揭示保持揭示

  const center = getPathCenter(skeletonPath.d);
  const dist = Math.hypot(
    center.x - penPosition.x,
    center.y - penPosition.y,
  );

  if (dist <= brushRadius) return 1;
  if (dist >= brushRadius * 2) return 0;
  return 1 - (dist - brushRadius) / brushRadius;
}

// ========== Path Timing (All Paths) ==========

interface TimedPath {
  path: DrawingPathV2;
  pathStart: number;
  pathDuration: number;
  isOutline: boolean;
}

function computeAllPathTiming(
  drawingPaths: DrawingPathV2[],
  drawAtFrames: number[],
  drawDurations: number[],
  elementOrder: string[],
): TimedPath[] {
  const result: TimedPath[] = [];

  for (let elemIdx = 0; elemIdx < elementOrder.length; elemIdx++) {
    const elemId = elementOrder[elemIdx];
    const elemStart = drawAtFrames[elemIdx] || 0;
    const elemDuration = drawDurations[elemIdx] || 1;

    const elemPaths = drawingPaths.filter(p => p.elementId === elemId);
    if (!elemPaths.length) continue;

    // 按 outline 路径总长度分配时间（skeleton 路径跟随 outline 时钟）
    // 无 layer 字段的路径视为 outline（兼容旧数据）
    const outlinePaths = elemPaths.filter(p => p.layer !== "skeleton");
    const skeletonPaths = elemPaths.filter(p => p.layer === "skeleton");
    const totalOutlineLen = outlinePaths.reduce(
      (sum, p) => {
        try { return sum + getLength(p.d); }
        catch { return sum + 1; }
      },
      0,
    );
    const totalLen = Math.max(1, totalOutlineLen);

    // Outline 路径按长度比例分配时间
    let cumLen = 0;
    for (const path of outlinePaths) {
      let pathLen: number;
      try { pathLen = getLength(path.d); }
      catch { pathLen = 1; }

      const startRatio = cumLen / totalLen;
      const lengthRatio = pathLen / totalLen;
      const pathStart = elemStart + startRatio * elemDuration;
      const pathDuration = Math.max(1, lengthRatio * elemDuration);
      cumLen += pathLen;

      result.push({ path, pathStart, pathDuration, isOutline: true });
    }

    // Skeleton 路径绑定到对应 outline 时间的中间
    const outlineEndFrame = elemStart + elemDuration;
    for (const path of skeletonPaths) {
      result.push({
        path,
        pathStart: elemStart,
        pathDuration: elemDuration,
        isOutline: false,
      });
    }
  }

  return result;
}

// ========== Pen Components ==========

interface PenRendererProps {
  penPosition: { x: number; y: number } | null;
  penAngle: number;
  penOpacity: number;
  penStyle: "marker" | "hand" | "debug";
}

const PenRenderer: React.FC<PenRendererProps> = ({
  penPosition,
  penAngle,
  penOpacity,
  penStyle,
}) => {
  if (!penPosition || penOpacity <= 0) return null;

  switch (penStyle) {
    case "marker":
      return (
        <MarkerPen
          x={penPosition.x}
          y={penPosition.y}
          angle={penAngle}
          opacity={penOpacity}
        />
      );

    case "hand":
      return (
        <Img
          src={staticFile("assets/writing-hand-small.png")}
          style={{
            position: "absolute",
            left: penPosition.x - 48,
            top: penPosition.y - 23,
            width: 500,
            height: 688,
            transform: `rotate(${penAngle * 0.3}deg)`,
            transformOrigin: "48px 23px",
            zIndex: 100,
            pointerEvents: "none",
            opacity: penOpacity,
          }}
        />
      );

    case "debug":
      return (
        <div
          style={{
            position: "absolute",
            left: penPosition.x - 8,
            top: penPosition.y - 8,
            width: 16,
            height: 16,
            borderRadius: "50%",
            backgroundColor: "rgba(255, 0, 0, 0.8)",
            border: "2px solid white",
            zIndex: 100,
            pointerEvents: "none",
            opacity: penOpacity,
          }}
        />
      );

    default:
      return null;
  }
};

// ========== MaskRevealAnimation V2 ==========

const MaskRevealAnimation: React.FC<MaskRevealV2Props> = ({
  imageSrc,
  drawingPaths,
  drawAtFrames,
  drawDurations,
  elementIds,
  brushRadius = 50,
  penStyle = "marker",
  showHand = true,
}) => {
  const frame = useCurrentFrame();
  const maskId = `reveal-mask-v2-${frame}`;

  // 确定 elementId 顺序
  const elementOrder = useMemo(() => {
    if (elementIds && elementIds.length > 0) {
      return elementIds;
    }
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

  // 预计算所有路径的时间分配
  const timedPaths = useMemo(
    () => computeAllPathTiming(drawingPaths, drawAtFrames, drawDurations, elementOrder),
    [drawingPaths, drawAtFrames, drawDurations, elementOrder],
  );

  // 笔信息（仅基于 outline 路径）
  const penInfo = usePenInfo(
    drawingPaths, frame, drawAtFrames, drawDurations, elementOrder,
  );

  // 追踪已揭示的骨架路径
  const [revealedSet, setRevealedSet] = React.useState<Set<number>>(new Set());

  // 每帧更新 revealedSet
  React.useEffect(() => {
    const newRevealed = new Set(revealedSet);
    let changed = false;

    timedPaths.forEach((tp, idx) => {
      if (!tp.isOutline && tp.path.layer === "skeleton") {
        const reveal = computeSkeletonReveal(
          tp.path,
          penInfo.penPosition,
          brushRadius,
          newRevealed.has(idx),
        );
        if (reveal >= 1 && !newRevealed.has(idx)) {
          newRevealed.add(idx);
          changed = true;
        }
      }
    });

    if (changed) {
      setRevealedSet(newRevealed);
    }
  }, [frame, timedPaths, penInfo.penPosition, brushRadius]);

  // 实际的 penStyle
  const effectivePenStyle = !showHand && penStyle === "hand" ? "marker" : penStyle;

  return (
    <AbsoluteFill>
      {/* SVG 蒙版层 */}
      <svg
        width={CANVAS_W}
        height={CANVAS_H}
        viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
        }}
      >
        <defs>
          <mask id={maskId}>
            {/* 黑色背景 = 完全遮挡 */}
            <rect width={CANVAS_W} height={CANVAS_H} fill="black" />

            {/* 白色蒙版路径 = 揭示区域 */}
            {timedPaths.map((tp, idx) => {
              if (tp.isOutline) {
                // Outline 路径：用 strokeDashoffset 控制揭示（笔尖已跟踪 outline）
                try {
                  const pathLen = getLength(tp.path.d);
                  const endFrame = tp.pathStart + tp.pathDuration;

                  if (frame < tp.pathStart) return null;

                  const progress = clamp(
                    (frame - tp.pathStart) / tp.pathDuration, 0, 1,
                  );

                  if (progress >= 1) {
                    return (
                      <path
                        key={idx}
                        d={tp.path.d}
                        stroke="white"
                        strokeWidth={brushRadius * 2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    );
                  }

                  const dashOffset = pathLen * (1 - progress);
                  return (
                    <path
                      key={idx}
                      d={tp.path.d}
                      stroke="white"
                      strokeWidth={brushRadius * 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                      strokeDasharray={pathLen}
                      strokeDashoffset={dashOffset}
                    />
                  );
                } catch {
                  return null;
                }
              } else {
                // Skeleton 路径：空间邻近驱动揭示
                const isRevealed = revealedSet.has(idx);
                const reveal = computeSkeletonReveal(
                  tp.path,
                  penInfo.penPosition,
                  brushRadius,
                  isRevealed,
                );

                if (reveal <= 0) return null;

                if (reveal >= 1) {
                  return (
                    <path
                      key={idx}
                      d={tp.path.d}
                      stroke="white"
                      strokeWidth={brushRadius * 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                    />
                  );
                }

                // 部分揭示：用 dashoffset
                try {
                  const pathLen = getLength(tp.path.d);
                  const dashOffset = pathLen * (1 - reveal);
                  return (
                    <path
                      key={idx}
                      d={tp.path.d}
                      stroke="white"
                      strokeWidth={brushRadius * 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                      strokeDasharray={pathLen}
                      strokeDashoffset={dashOffset}
                    />
                  );
                } catch {
                  return null;
                }
              }
            })}
          </mask>
        </defs>

        {/* 应用蒙版的 PNG 原图 */}
        <image
          href={imageSrc}
          width={CANVAS_W}
          height={CANVAS_H}
          mask={`url(#${maskId})`}
          style={{ width: "100%", height: "100%" }}
        />
      </svg>

      {/* 笔层 */}
      <PenRenderer
        penPosition={penInfo.penPosition}
        penAngle={penInfo.penAngle}
        penOpacity={penInfo.penOpacity}
        penStyle={effectivePenStyle}
      />
    </AbsoluteFill>
  );
};

export default MaskRevealAnimation;
