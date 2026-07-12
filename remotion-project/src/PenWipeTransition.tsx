/**
 * PenWipeTransition.tsx - 马克笔转场（替换旧版 HandWipeTransition）
 *
 * 效果：白色遮罩从左向右扩展，前沿渲染 <MarkerPen> 组件，
 * 模拟白板动画的标准擦除转场。
 *
 * 核心机制：
 *   - 白色遮罩从左向右扩展，覆盖旧场景
 *   - ease-in-out 缓动
 *   - 前沿绘制 MarkerPen 笔（Y居中，角度0° = 从左到右水平擦）
 *
 * 转场时长：25 帧（~0.83 秒）
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import MarkerPen from "./MarkerPen";

interface PenWipeTransitionProps {
  startFrame: number;
  durationFrames: number;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const PenWipeTransition: React.FC<PenWipeTransitionProps> = ({
  startFrame,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const progress = Math.max(0, Math.min(1, (frame - startFrame) / durationFrames));
  if (progress <= 0) return null;

  // ease-in-out
  const eased = progress < 0.5
    ? 2 * progress * progress
    : 1 - Math.pow(-2 * progress + 2, 2) / 2;

  const wipeWidth = CANVAS_W * eased;

  // 笔尖位置：擦除前沿，Y 居中
  const penX = wipeWidth;
  const penY = CANVAS_H / 2;
  const penOpacity = progress < 0.95 ? 1 : interpolate(progress, [0.95, 1], [1, 0]);

  return (
    <AbsoluteFill style={{ zIndex: 50, pointerEvents: "none" }}>
      {/* 白色遮罩 */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: wipeWidth,
          height: CANVAS_H,
          backgroundColor: "#FFFFFF",
        }}
      />

      {/* 马克笔前沿 */}
      <MarkerPen
        x={penX}
        y={penY}
        angle={0}
        opacity={penOpacity}
      />
    </AbsoluteFill>
  );
};

// Simple linear interpolation helper
const interpolate = (val: number, inRange: [number, number], outRange: [number, number]): number => {
  const t = (val - inRange[0]) / (inRange[1] - inRange[0]);
  return outRange[0] + Math.max(0, Math.min(1, t)) * (outRange[1] - outRange[0]);
};

export default PenWipeTransition;
