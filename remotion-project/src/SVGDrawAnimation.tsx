/**
 * SVGDrawAnimation.tsx - SVG 路径动画渲染组件
 *
 * 核心机制：stroke-dasharray = path.length → stroke-dashoffset 从 length 递减到 0
 * 实现"线条从笔尖生长"的效果。
 *
 * 功能：
 * - stroke 类型路径：stroke-dashoffset 动画
 * - fill 类型路径：先描轮廓（前 60%），再淡入填充（后 40%）
 * - 按路径长度比例分配绘制时间（长路径慢画，短路径快画）
 * - 画手 SVG 笔尖跟随 + 角度旋转 + 3 帧平滑
 * - SVG viewBox → CSS 坐标精确映射
 */

import React from "react";
import {
  AbsoluteFill,
  staticFile,
  useCurrentFrame,
  Img,
  interpolate,
  Easing,
} from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";

import type { SVGElementData, SVGPathData } from "./types";

// ========== Types ==========

interface SVGDrawAnimationProps {
  elements: SVGElementData[];
  drawAtFrames: number[];
  drawDurations: number[];
  viewBox: string;
  showHand?: boolean;
}

// ViewBox dimensions (1920x1080 when normalized)
const CANVAS_W = 1920;
const CANVAS_H = 1080;

// ========== Helpers ==========

/**
 * 将 frame 限制在 [0, 1] 区间内。
 */
const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

/**
 * 解析 viewBox 字符串为数字数组。
 */
const parseViewBox = (viewBox: string): [number, number, number, number] => {
  const parts = viewBox.split(" ").map(Number);
  return [parts[0] || 0, parts[1] || 0, parts[2] || 1920, parts[3] || 1080];
};

/**
 * 计算 viewBox 坐标到 CSS 坐标的缩放和偏移。
 * 匹配 SVG preserveAspectRatio="xMidYMid meet" 的行为。
 */
const computeViewBoxTransform = (
  viewBox: string,
): { scale: number; offsetX: number; offsetY: number } => {
  const [, , vbW, vbH] = parseViewBox(viewBox);
  const scaleX = CANVAS_W / vbW;
  const scaleY = CANVAS_H / vbH;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = (CANVAS_W - vbW * scale) / 2;
  const offsetY = (CANVAS_H - vbH * scale) / 2;
  return { scale, offsetX, offsetY };
};

/**
 * 计算路径在当前绘制点的切线方向角度（度）。
 * 用于旋转画手 PNG 使其朝向绘制方向。
 */
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

  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  return angle;
};

/**
 * 判断路径复杂度（SVG 命令数），用于决定 fill 路径是否跳过描轮廓。
 */
const getPathComplexity = (d: string): number => {
  return (d.match(/[MCLQSAZ]/gi) || []).length;
};

// ========== DrawingHand 画手跟随组件 ==========

interface DrawingHandProps {
  elements: SVGElementData[];
  frame: number;
  drawAtFrames: number[];
  drawDurations: number[];
  viewBox: string;
  showHand: boolean;
}

interface ActivePathInfo {
  elementIdx: number;
  pathIdx: number;
  d: string;
  progress: number;
  pathStart: number;
  pathDuration: number;
}

/**
 * 找到当前正在绘制的路径。
 * 返回 null 表示画手应隐藏（元素间间隔或未开始/已结束）。
 */
const findCurrentPath = (
  elements: SVGElementData[],
  frame: number,
  drawAtFrames: number[],
  drawDurations: number[],
): ActivePathInfo | null => {
  for (let elemIdx = 0; elemIdx < elements.length; elemIdx++) {
    const element = elements[elemIdx];
    const elemStart = drawAtFrames[elemIdx];
    const elemDuration = drawDurations[elemIdx];
    const elemEnd = elemStart + elemDuration;

    if (frame < elemStart || frame >= elemEnd) continue;

    const paths = element.paths;
    if (!paths.length) continue;

    // 按长度比例分配时间
    const totalLength = element.totalLength || 1;
    let cumLen = 0;
    const segments: Array<{ startRatio: number; lengthRatio: number }> = [];

    for (const path of paths) {
      segments.push({
        startRatio: cumLen / totalLength,
        lengthRatio: path.length / totalLength,
      });
      cumLen += path.length;
    }

    for (let pathIdx = 0; pathIdx < paths.length; pathIdx++) {
      const seg = segments[pathIdx];
      const pathStart = elemStart + seg.startRatio * elemDuration;
      const pathDuration = Math.max(1, seg.lengthRatio * elemDuration);
      const pathEnd = pathStart + pathDuration;

      if (frame >= pathStart && frame < pathEnd) {
        const progress = clamp((frame - pathStart) / pathDuration, 0, 1);
        return {
          elementIdx: elemIdx,
          pathIdx,
          d: paths[pathIdx].d,
          progress,
          pathStart,
          pathDuration,
        };
      }
    }
  }
  return null;
};

const DrawingHand: React.FC<DrawingHandProps> = ({
  elements,
  frame,
  drawAtFrames,
  drawDurations,
  viewBox,
  showHand,
}) => {
  if (!showHand) return null;

  const currentPath = findCurrentPath(
    elements,
    frame,
    drawAtFrames,
    drawDurations,
  );
  if (!currentPath) return null;

  const { d, progress, pathStart, pathDuration } = currentPath;

  // 计算 viewBox → CSS 映射
  const { scale, offsetX, offsetY } = computeViewBoxTransform(viewBox);

  // 获取当前绘制点的 viewBox 坐标
  const length = getLength(d);
  const point = getPointAtLength(d, length * progress);

  // 转换为 CSS 坐标
  const cssX = point.x * scale + offsetX;
  const cssY = point.y * scale + offsetY;

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
        left: cssX - 10,
        top: cssY - 30,
        width: 120,
        height: 120,
        transform: `rotate(${smoothedAngle}deg)`,
        transformOrigin: "10px 30px",
        zIndex: 100,
        pointerEvents: "none",
      }}
    />
  );
};

// ========== SVGDrawAnimation 主组件 ==========

const SVGDrawAnimation: React.FC<SVGDrawAnimationProps> = ({
  elements,
  drawAtFrames,
  drawDurations,
  viewBox,
  showHand = true,
}) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill>
      {/* SVG 层 */}
      <svg
        viewBox={viewBox}
        style={{
          width: "100%",
          height: "100%",
          position: "absolute",
          top: 0,
          left: 0,
        }}
      >
        {elements.map((element, elemIdx) => {
          const elemStart = drawAtFrames[elemIdx];
          const elemDuration = drawDurations[elemIdx];
          const elemEnd = elemStart + elemDuration;

          // 元素尚未开始绘制 → 跳过
          if (frame < elemStart) return null;

          const paths = element.paths;
          if (!paths.length) return null;

          // 预计算每个路径的时间分配（按长度比例）
          const totalLength = element.totalLength || 1;
          let cumLen = 0;
          const segments: Array<{
            startRatio: number;
            lengthRatio: number;
          }> = [];

          for (const path of paths) {
            segments.push({
              startRatio: cumLen / totalLength,
              lengthRatio: path.length / totalLength,
            });
            cumLen += path.length;
          }

          return (
            <g key={`elem-${elemIdx}`}>
              {paths.map((path, pathIdx) => {
                const seg = segments[pathIdx];
                const pathStart = elemStart + seg.startRatio * elemDuration;
                const pathDuration = Math.max(
                  1,
                  seg.lengthRatio * elemDuration,
                );
                const pathProgress = clamp(
                  (frame - pathStart) / pathDuration,
                  0,
                  1,
                );

                // 尚未开始
                if (pathProgress <= 0) return null;

                // 完全完成 → 显示完整路径
                if (pathProgress >= 1) {
                  if (path.type === "fill") {
                    return (
                      <path
                        key={`${elemIdx}-${pathIdx}`}
                        d={path.d}
                        fill={path.fill || "#000"}
                        stroke="none"
                      />
                    );
                  }
                  return (
                    <path
                      key={`${elemIdx}-${pathIdx}`}
                      d={path.d}
                      stroke={path.stroke}
                      strokeWidth={path.strokeWidth}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      fill="none"
                    />
                  );
                }

                // 动画进行中
                if (path.type === "stroke") {
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
                }

                // fill 类型
                const complexity = getPathComplexity(path.d);
                const useOutlineAnimation = complexity < 30;

                if (useOutlineAnimation) {
                  // 先描轮廓（前 60%），再淡入填充（后 40%）
                  const outlineProgress = clamp(pathProgress / 0.6, 0, 1);
                  const fillProgress = clamp(
                    (pathProgress - 0.6) / 0.4,
                    0,
                    1,
                  );
                  return (
                    <g key={`${elemIdx}-${pathIdx}`}>
                      <path
                        d={path.d}
                        stroke={path.stroke || "#000"}
                        strokeWidth={2}
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeDasharray={path.length}
                        strokeDashoffset={path.length * (1 - outlineProgress)}
                      />
                      <path
                        d={path.d}
                        fill={path.fill || "#000"}
                        stroke="none"
                        opacity={fillProgress}
                      />
                    </g>
                  );
                }

                // 复杂填充路径：直接淡入
                return (
                  <path
                    key={`${elemIdx}-${pathIdx}`}
                    d={path.d}
                    fill={path.fill || "#000"}
                    stroke="none"
                    opacity={pathProgress}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* 画手跟随 */}
      <DrawingHand
        elements={elements}
        frame={frame}
        drawAtFrames={drawAtFrames}
        drawDurations={drawDurations}
        viewBox={viewBox}
        showHand={showHand}
      />
    </AbsoluteFill>
  );
};

export default SVGDrawAnimation;
