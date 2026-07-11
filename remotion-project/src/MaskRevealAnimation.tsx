/**
 * MaskRevealAnimation.tsx - PNG 蒙版揭示动画组件
 *
 * 核心机制：SVG <mask> 内的白色笔刷路径沿中心线展开，
 * 原始 PNG 图片被蒙版裁剪，实现"图片随着画笔轨迹渐进出现"的效果。
 *
 * 与旧 SVGDrawAnimation 的根本区别：
 *  - 可见内容是原始 PNG 图片（零质量损失）
 *  - SVG 路径只用作蒙版（不是可见内容）
 *  - 路径精度要求低（蒙版笔刷 80-100px 宽）
 *
 * 数据流：
 *   drawingPaths[] -- 中心线路径 (SVG polyline d 属性)
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

// ========== Types ==========

interface DrawingPath {
  d: string;           // SVG path d 属性（中心线 polyline）
  elementId: string;   // 归属元素 ID
}

interface MaskRevealProps {
  imageSrc: string;               // 场景 PNG 图片路径
  drawingPaths: DrawingPath[];    // 中心线路径列表
  drawAtFrames: number[];         // 每组路径的起始帧（scene-relative）
  drawDurations: number[];        // 每组路径的绘制帧数
  elementIds?: string[];          // 元素 ID 顺序（与 drawAtFrames 对齐）
  brushRadius?: number;           // 蒙版笔刷半径 (px)
  showHand?: boolean;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

// ========== Helpers ==========

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

const computeHandAngle = (d: string, progress: number): number => {
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

// ========== DrawingHand 画手跟随组件 ==========

interface ActivePathInfo {
  path: DrawingPath;
  pathStart: number;
  pathDuration: number;
  progress: number;
}

/**
 * 找到当前正在绘制的路径。
 * drawAtFrames[i] 对应 elementId = elementOrder[i]。
 */
const findCurrentPath = (
  drawingPaths: DrawingPath[],
  frame: number,
  drawAtFrames: number[],
  drawDurations: number[],
  elementOrder: string[],
): ActivePathInfo | null => {
  for (let elemIdx = 0; elemIdx < elementOrder.length; elemIdx++) {
    const elemId = elementOrder[elemIdx];
    const elemStart = drawAtFrames[elemIdx] || 0;
    const elemDuration = drawDurations[elemIdx] || 1;
    const elemEnd = elemStart + elemDuration;

    if (frame < elemStart || frame >= elemEnd) continue;

    const elemPaths = drawingPaths.filter(p => p.elementId === elemId);
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

interface DrawingHandProps {
  drawingPaths: DrawingPath[];
  frame: number;
  drawAtFrames: number[];
  drawDurations: number[];
  elementOrder: string[];
  showHand: boolean;
}

const DrawingHand: React.FC<DrawingHandProps> = ({
  drawingPaths,
  frame,
  drawAtFrames,
  drawDurations,
  elementOrder,
  showHand,
}) => {
  if (!showHand) return null;

  const currentPath = findCurrentPath(
    drawingPaths, frame, drawAtFrames, drawDurations, elementOrder,
  );
  if (!currentPath) return null;

  const { path, pathStart, pathDuration } = currentPath;
  let { progress } = currentPath;
  const d = path.d;

  // 保护性检查：getLength 失败时静默隐藏画手
  let length: number;
  try { length = getLength(d); }
  catch { return null; }
  if (length <= 0) return null;

  const point = getPointAtLength(d, length * progress);

  // 3 帧角度平滑
  const angles = [-2, -1, 0].map((offset) => {
    const f = Math.max(0, frame + offset);
    const prog = clamp((f - pathStart) / pathDuration, 0, 1);
    return computeHandAngle(d, prog);
  });
  const smoothedAngle = angles.reduce((a, b) => a + b) / angles.length;

  return (
    <Img
      src={staticFile("assets/writing-hand-small.png")}
      style={{
        position: "absolute",
        left: point.x - 60,          // 笔尖 X 偏移（原图比例 17%）
        top: point.y - 22,           // 笔尖 Y 偏移（原图比例 4.6%）
        width: 350,                   // 手宽度占画面 18%（YouTube 标准）
        height: 481,                  // 保持原始宽高比（872:1200）
        transform: `rotate(${smoothedAngle * 0.3}deg)`,  // 柔和旋转（30% 角度）
        transformOrigin: "60px 22px", // 旋转中心 = 笔尖位置
        zIndex: 100,
        pointerEvents: "none",
      }}
    />
  );
};

/**
 * 计算 paths 在 element 内的分配。
 * 返回每个 element 的路径列表 + 每条路径的时间范围。
 */
interface TimedPath {
  path: DrawingPath;
  pathStart: number;
  pathDuration: number;
}

function computePathTiming(
  drawingPaths: DrawingPath[],
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

    const totalPathLen = elemPaths.reduce(
      (sum, p) => {
        try { return sum + getLength(p.d); }
        catch { return sum + 1; }
      },
      0,
    );
    const totalLen = Math.max(1, totalPathLen);

    let cumLen = 0;
    for (const path of elemPaths) {
      let pathLen: number;
      try { pathLen = getLength(path.d); }
      catch { pathLen = 1; }

      const startRatio = cumLen / totalLen;
      const lengthRatio = pathLen / totalLen;
      const pathStart = elemStart + startRatio * elemDuration;
      const pathDuration = Math.max(1, lengthRatio * elemDuration);
      cumLen += pathLen;

      result.push({ path, pathStart, pathDuration });
    }
  }

  return result;
}

// ========== MaskRevealAnimation 主组件 ==========

const MaskRevealAnimation: React.FC<MaskRevealProps> = ({
  imageSrc,
  drawingPaths,
  drawAtFrames,
  drawDurations,
  elementIds,        // 新增
  brushRadius = 50,
  showHand = true,
}) => {
  const frame = useCurrentFrame();
  const maskId = `reveal-mask-${frame}`;

  // 确定 elementId 顺序（优先使用传入的 elementIds，与时间轴对齐）
  const elementOrder = useMemo(() => {
    if (elementIds && elementIds.length > 0) {
      return elementIds;
    }
    // fallback：从路径数据推导（保持 drawingPaths 中的首次出现顺序）
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
    () => computePathTiming(drawingPaths, drawAtFrames, drawDurations, elementOrder),
    [drawingPaths, drawAtFrames, drawDurations, elementOrder],
  );

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
              const pathLen = getLength(tp.path.d);
              const pathEnd = tp.pathStart + tp.pathDuration;

              // 尚未开始
              if (frame < tp.pathStart) return null;

              const progress = clamp(
                (frame - tp.pathStart) / tp.pathDuration,
                0,
                1,
              );

              // 完成：完全揭示
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

              // 进行中：dashoffset 控制揭示长度
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

      {/* 画手层 */}
      <DrawingHand
        drawingPaths={drawingPaths}
        frame={frame}
        drawAtFrames={drawAtFrames}
        drawDurations={drawDurations}
        elementOrder={elementOrder}
        showHand={showHand}
      />
    </AbsoluteFill>
  );
};

export default MaskRevealAnimation;
