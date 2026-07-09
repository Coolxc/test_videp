/**
 * PaperPullTransition.tsx - 手拉新纸场景转场
 *
 * 效果：一张纯白纸从上方滑入覆盖旧画面，模拟画师画完后拉起纸张露出新一页。
 *
 * 设计决定（基于 Red Team 分析）：
 * - 不使用 drawing-hand.png 做拉纸（握笔姿势拉纸不自然）
 * - 纯白纸滑入 + 底边阴影，视觉效果更干净
 * - 使用 ease-out cubic 缓动（无 spring 过冲）
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";

interface PaperPullTransitionProps {
  startFrame: number;
  durationFrames: number;
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const PaperPullTransition: React.FC<PaperPullTransitionProps> = ({
  startFrame,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = Math.max(
    0,
    Math.min(1, (frame - startFrame) / durationFrames),
  );

  if (progress <= 0) return null;

  // ease-out cubic 缓动：纸先快后慢滑入，无过冲
  const eased =
    progress < 1 ? 1 - Math.pow(1 - progress, 3) : 1;

  // 白纸从 y=-CANVAS_H 滑到 y=0
  const paperY = -CANVAS_H + CANVAS_H * eased;

  return (
    <AbsoluteFill style={{ zIndex: 50, pointerEvents: "none" }}>
      {/* 白纸 */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: paperY,
          width: CANVAS_W,
          height: CANVAS_H,
          backgroundColor: "#FFFFFF",
        }}
      >
        {/* 纸张底边阴影 */}
        <div
          style={{
            position: "absolute",
            left: 0,
            bottom: -8,
            width: CANVAS_W,
            height: 8,
            background:
              "linear-gradient(to bottom, rgba(0,0,0,0.08), transparent)",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export default PaperPullTransition;
