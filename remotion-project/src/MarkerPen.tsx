/**
 * MarkerPen.tsx - SVG 矢量马克笔组件
 *
 * 纯 SVG 实现的马克笔，笔尖固定在 (0,0) 原点，
 * 笔杆向右下延伸约 120px。
 * 整体按运动方向 angle 旋转。
 *
 * 与旧版 DrawingHand 图片手相比：
 *  - 纯矢量，完美跟随任意角度旋转（不存在朝向问题）
 *  - 与白板手绘风格完全匹配
 *  - 支持抬笔/落笔透明度过渡
 */

import React from "react";
import { AbsoluteFill } from "remotion";

interface MarkerPenProps {
  x: number;       // 笔尖 X 坐标
  y: number;       // 笔尖 Y 坐标
  angle: number;   // 运动方向角度（度）
  opacity: number; // 0=抬笔, 1=落笔
}

const CANVAS_W = 1920;
const CANVAS_H = 1080;

const MarkerPen: React.FC<MarkerPenProps> = ({ x, y, angle, opacity }) => {
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        zIndex: 100,
      }}
    >
      <svg
        width={CANVAS_W}
        height={CANVAS_H}
        viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
        }}
      >
        <g
          transform={`translate(${x}, ${y}) rotate(${angle})`}
          style={{ opacity }}
        >
          {/* 笔尖 — 椭圆，深灰色 */}
          <ellipse
            cx={0}
            cy={0}
            rx={8}
            ry={4}
            fill="#333"
          />

          {/* 笔杆 — 矩形，灰色 */}
          <rect
            x={0}
            y={-3}
            width={120}
            height={6}
            rx={3}
            ry={3}
            fill="#888"
          />

          {/* 笔杆高光 */}
          <rect
            x={5}
            y={-1}
            width={100}
            height={2}
            rx={1}
            ry={1}
            fill="#AAA"
            opacity={0.5}
          />

          {/* 笔帽 — 圆角矩形，深灰色 */}
          <rect
            x={100}
            y={-4}
            width={25}
            height={8}
            rx={2}
            ry={2}
            fill="#555"
          />

          {/* 笔夹 */}
          <rect
            x={108}
            y={-6}
            width={4}
            height={3}
            rx={1}
            ry={1}
            fill="#666"
          />
        </g>
      </svg>
    </AbsoluteFill>
  );
};

export default MarkerPen;
