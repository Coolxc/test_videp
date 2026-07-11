/**
 * HandWipeTransition.tsx - 手擦除转场
 *
 * 效果：一只手从左向右擦过画面，旧内容被擦除，露出干净白板。
 * 替代 PaperPullTransition（白纸从上向下滑入）。
 *
 * 核心机制：
 *   - 白色遮罩从左向右扩展，覆盖旧场景
 *   - 手图片始终在遮罩右边缘，模拟擦除动作
 *   - ease-in-out 缓动：开始慢 → 中间快 → 结束慢
 *
 * 设计决定：
 *   - 使用 writing-hand-small.png（掌心朝画面，像在擦白板）
 *   - 手旋转约 90° 让手掌面朝右侧
 *   - 转场时长 25 帧（~0.83 秒），比旧转场更长更自然
 */

import React from "react";
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
} from "remotion";

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

  const progress = Math.max(
    0,
    Math.min(1, (frame - startFrame) / durationFrames),
  );

  if (progress <= 0) return null;

  // ease-in-out 缓动：开始慢 → 中间快 → 结束慢
  const eased =
    progress < 0.5
      ? 2 * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 2) / 2;

  const wipeX = CANVAS_W * eased; // 白色遮罩右边缘 x 坐标

  return (
    <AbsoluteFill style={{ zIndex: 50, pointerEvents: "none" }}>
      {/* 白色遮罩：从左向右扩展 */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: wipeX,
          height: CANVAS_H,
          backgroundColor: "#FFFFFF",
        }}
      />
      {/* 手：在遮罩右边缘，模拟擦除动作 */}
      <Img
        src={staticFile("assets/writing-hand-small.png")}
        style={{
          position: "absolute",
          left: wipeX - 100,    // 手掌对齐遮罩边缘
          top: CANVAS_H / 2 - 200,  // 垂直居中
          width: 280,
          height: 385,
          transform: "rotate(90deg)",  // 手掌朝右，像在擦白板
          zIndex: 51,
        }}
        alt=""
      />
    </AbsoluteFill>
  );
};

export default HandWipeTransition;
