/**
 * HandWipeTransition.tsx - 手擦除转场
 *
 * 效果：白色遮罩从左向右扩展，擦除旧场景内容。
 * 不再包含手图片——转场期间不显示手。
 *
 * 核心机制：
 *   - 白色遮罩从左向右扩展，覆盖旧场景
 *   - ease-in-out 缓动：开始慢 → 中间快 → 结束慢
 *
 * 设计决定：
 *   - 纯白遮罩，无手图片（手只在 MaskRevealAnimation 中绘画时出现）
 *   - 转场时长 25 帧（~0.83 秒）
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

interface HandWipeTransitionProps {
  startFrame: number;
  durationFrames: number;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const HandWipeTransition: React.FC<HandWipeTransitionProps> = ({
  startFrame,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const progress = Math.max(0, Math.min(1, (frame - startFrame) / durationFrames));
  if (progress <= 0) return null;

  const eased = progress < 0.5
    ? 2 * progress * progress
    : 1 - Math.pow(-2 * progress + 2, 2) / 2;

  return (
    <AbsoluteFill style={{ zIndex: 50, pointerEvents: "none" }}>
      <div style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: CANVAS_W * eased,
        height: CANVAS_H,
        backgroundColor: "#FFFFFF",
      }} />
    </AbsoluteFill>
  );
};

export default HandWipeTransition;
