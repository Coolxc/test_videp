/**
 * PostDrawAnimation.tsx - 元素画完后动画系统
 *
 * 在元素绘制完成后，对其应用 CSS Transform 动画。
 * 使用 clip-path 隔离每个元素，只对元素区域做变换。
 *
 * 9 种动画类型：
 *   pulse, breathe, rotate, seesaw, bounce,
 *   shake, float, emphasis, wave
 *
 * 3 档速度：slow, normal, fast
 *
 * 触发逻辑：
 *   frame < triggerFrame → 不渲染
 *   frame > freezeFrame → 使用 freezeFrame 时刻的 transform（静止）
 */

import React from "react";
import { useCurrentFrame, interpolate, Easing } from "remotion";

import type { AnimationType, AnimationSpeed } from "./types";

// ========== Types ==========

interface PostDrawAnimationProps {
  imageSrc: string;
  bbox: { x: number; y: number; w: number; h: number };
  animation: { type: AnimationType; speed: AnimationSpeed };
  triggerFrame: number;   // 动画开始帧（scene-relative）
  freezeFrame: number;    // 动画冻结帧（scene-relative）
}

// ========== Animation Parameter Tables ==========

interface AnimParams {
  freq: number;
  amp: number;
}

const PARAMS: Record<AnimationSpeed, Record<string, AnimParams>> = {
  slow: {
    pulse:    { freq: 1.0, amp: 0.03 },
    breathe:  { freq: 0.5, amp: 0.02 },
    rotate:   { freq: 0,   amp: 30 },    // deg/s
    seesaw:   { freq: 0.4, amp: 3 },     // deg
    bounce:   { freq: 1.0, amp: 8 },
    shake:    { freq: 4.0, amp: 2 },
    float:    { freq: 0.5, amp: 5 },
    emphasis: { freq: 0,   amp: 0.1 },
    wave:     { freq: 0.8, amp: 2 },     // deg
  },
  normal: {
    pulse:    { freq: 1.5, amp: 0.05 },
    breathe:  { freq: 0.8, amp: 0.03 },
    rotate:   { freq: 0,   amp: 60 },
    seesaw:   { freq: 0.8, amp: 5 },
    bounce:   { freq: 2.0, amp: 15 },
    shake:    { freq: 8.0, amp: 4 },
    float:    { freq: 1.0, amp: 10 },
    emphasis: { freq: 0,   amp: 0.2 },
    wave:     { freq: 1.5, amp: 4 },
  },
  fast: {
    pulse:    { freq: 2.5, amp: 0.08 },
    breathe:  { freq: 1.2, amp: 0.05 },
    rotate:   { freq: 0,   amp: 120 },
    seesaw:   { freq: 1.5, amp: 8 },
    bounce:   { freq: 3.0, amp: 25 },
    shake:    { freq: 15,  amp: 8 },
    float:    { freq: 1.5, amp: 18 },
    emphasis: { freq: 0,   amp: 0.35 },
    wave:     { freq: 2.5, amp: 7 },
  },
};

// ========== Spring-like emphasis (one-shot decay) ==========

function springDecay(t: number, damping: number = 3): number {
  // Decaying sine wave: exp(-damping * t) * sin(t * PI * 3)
  if (t <= 0) return 0;
  return Math.exp(-damping * t) * Math.sin(t * Math.PI * 3);
}

// ========== Transform Computation ==========

function computeTransform(
  type: AnimationType,
  speed: AnimationSpeed,
  age: number,  // frames since trigger
  fps: number,
): string {
  const p = PARAMS[speed][type];
  if (!p) return "none";

  // age 转换为秒（大多数动画用秒描述更自然）
  const t = age / fps;

  switch (type) {
    case "pulse": {
      const scale = 1 + Math.abs(Math.sin(t * Math.PI * p.freq)) * p.amp;
      return `scale(${scale})`;
    }

    case "breathe": {
      const scaleY = 1 + Math.sin(t * Math.PI * p.freq) * p.amp;
      return `scaleY(${scaleY})`;
    }

    case "rotate": {
      const deg = t * p.amp;
      return `rotate(${deg}deg)`;
    }

    case "seesaw": {
      const deg = Math.sin(t * Math.PI * p.freq) * p.amp;
      return `rotate(${deg}deg)`;
    }

    case "bounce": {
      const translateY = Math.abs(Math.sin(t * Math.PI * p.freq)) * -p.amp;
      return `translateY(${translateY}px)`;
    }

    case "shake": {
      const translateX = Math.sin(t * Math.PI * p.freq) * p.amp;
      return `translateX(${translateX}px)`;
    }

    case "float": {
      const translateY = Math.sin(t * Math.PI * p.freq) * p.amp;
      return `translateY(${translateY}px)`;
    }

    case "emphasis": {
      const scale = 1 + springDecay(t) * p.amp;
      return `scale(${scale})`;
    }

    case "wave": {
      const skewX = Math.sin(t * Math.PI * p.freq) * p.amp;
      return `skewX(${skewX}deg)`;
    }

    default:
      return "none";
  }
}

// ========== Component ==========

const PostDrawAnimation: React.FC<PostDrawAnimationProps> = ({
  imageSrc,
  bbox,
  animation,
  triggerFrame,
  freezeFrame,
}) => {
  const frame = useCurrentFrame();
  const fps = 30; // hard-coded for consistency

  // Not yet triggered
  if (frame < triggerFrame) return null;

  // Determine age and whether we're past freeze
  const isFrozen = frame > freezeFrame;
  const age = isFrozen
    ? freezeFrame - triggerFrame
    : frame - triggerFrame;

  const transform = computeTransform(
    animation.type,
    animation.speed,
    age,
    fps,
  );

  return (
    <div
      style={{
        position: "absolute",
        left: bbox.x,
        top: bbox.y,
        width: bbox.w,
        height: bbox.h,
        overflow: "hidden",
        zIndex: 10,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: -bbox.x,
          top: -bbox.y,
          width: 1920,
          height: 1080,
          transform,
          transformOrigin: `${bbox.x + bbox.w / 2}px ${bbox.y + bbox.h / 2}px`,
        }}
      >
        <img
          src={imageSrc}
          style={{
            width: 1920,
            height: 1080,
            display: "block",
          }}
          alt=""
        />
      </div>
    </div>
  );
};

export default PostDrawAnimation;
