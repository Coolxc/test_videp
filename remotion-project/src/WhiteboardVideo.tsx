/**
 * WhiteboardVideo.tsx - SVG 白板视频主合成组件
 *
 * 用 SVGDrawAnimation 替代了旧版的 <Video> 嵌入预渲染 MP4。
 * 所有场景元素通过 SVG stroke-dashoffset 路径动画呈现"笔尖生长"效果。
 *
 * 主要变化（相对旧版）：
 *  - Video → SVGDrawAnimation（核心变化）
 *  - 背景色 #F6F1E3 → #FFFFFF（纯白纸）
 *  - Grid 移除（纯白纸无需格线）
 *  - 场景间加入 PaperPullTransition 拉纸转场
 *  - DrawingSFX 简化为单层（不再区分 sketch/colorize）
 *  - 接收 svgData prop 替代 animations/ 目录下的 MP4
 */

import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  interpolate,
  useVideoConfig,
} from "remotion";
import "@fontsource/zcool-kuaile";

import type {
  Timeline,
  SceneTimeline,
  ElementTimeline,
  StoryboardScene,
  SVGSceneData,
} from "./types";
import SVGDrawAnimation from "./SVGDrawAnimation";
import PaperPullTransition from "./PaperPullTransition";

// ========== Design Tokens ==========
const C = {
  bg: "#FFFFFF", // 纯白纸
  accent: "#C05050",
  text: "#2D3748",
  subtitleBg: "rgba(45, 55, 72, 0.85)",
  white: "#FFFFFF",
};

const FONT_FAMILY = "'ZCOOL KuaiLe', sans-serif";
const FPS = 30;

// ========== Subtitle ==========
interface SubtitleProps {
  segments: Array<{ text: string; startTime: number; endTime: number }>;
  fontSize?: number;
}

const Subtitle: React.FC<SubtitleProps> = ({ segments, fontSize = 36 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const currentSeg = segments.find(
    (s) => currentTime >= s.startTime && currentTime < s.endTime,
  );

  if (!currentSeg) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 100,
        left: 60,
        right: 60,
        display: "flex",
        justifyContent: "center",
        zIndex: 30,
      }}
    >
      <div
        style={{
          backgroundColor: C.subtitleBg,
          borderRadius: 16,
          padding: "12px 32px",
          maxWidth: 1400,
        }}
      >
        <span
          style={{
            fontFamily: FONT_FAMILY,
            fontSize,
            color: C.white,
            lineHeight: 1.4,
            textAlign: "center",
            display: "block",
          }}
        >
          {currentSeg.text}
        </span>
      </div>
    </div>
  );
};

// ========== Drawing Sound Effects (简化版，单层音效) ==========
interface DrawingSFXProps {
  elements: ElementTimeline[];
}

const DrawingSFX: React.FC<DrawingSFXProps> = ({ elements }) => (
  <>
    {elements.map((elem) => (
      <Sequence
        key={elem.id}
        from={elem.drawAtFrame}
        durationInFrames={elem.drawDurationFrames}
      >
        <Audio
          src={staticFile("assets/sfx/pen_sketch.mp3")}
          loop
          volume={(f) => {
            const dur = elem.drawDurationFrames;
            if (dur <= 0) return 0;
            const fadeIn = interpolate(f, [0, 5], [0, 0.12], {
              extrapolateRight: "clamp",
            });
            const fadeOut = interpolate(f, [dur - 5, dur], [0.12, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return Math.min(fadeIn, fadeOut);
          }}
        />
      </Sequence>
    ))}
  </>
);

// ========== Handwritten Text (逐字手写动画) ==========
interface WritingHandProps {
  chars: string[];
  startFrame: number;
  framesPerChar: number;
  fontSize: number;
}

const WritingHand: React.FC<WritingHandProps> = ({
  chars,
  startFrame,
  framesPerChar,
  fontSize,
}) => {
  const frame = useCurrentFrame();

  for (let i = chars.length - 1; i >= 0; i--) {
    const charStart = startFrame + i * framesPerChar;
    if (frame >= charStart) {
      const charProgress = (frame - charStart) / framesPerChar;
      if (charProgress < 0.5) {
        const x = 12 + i * (fontSize * 0.65);
        const y = fontSize * 0.1;
        return (
          <img
            src={staticFile("assets/writing-hand-small.png")}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: fontSize * 1.2,
              height: fontSize * 1.2,
              opacity: 0.9,
              zIndex: 20,
            }}
            alt=""
          />
        );
      }
    }
  }
  return null;
};

interface HandwrittenTextProps {
  text: string;
  startFrame: number;
  durationFrames: number;
  x: number;
  y: number;
  fontSize: number;
  color: string;
}

const HandwrittenText: React.FC<HandwrittenTextProps> = ({
  text,
  startFrame,
  durationFrames,
  x,
  y,
  fontSize,
  color,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const chars = [...text];
  const framesPerChar = Math.max(1, durationFrames / chars.length);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: "translate(-50%, -50%)",
        display: "flex",
        zIndex: 15,
      }}
    >
      {chars.map((char, i) => {
        const charStart = startFrame + i * framesPerChar;
        const age = frame - charStart;

        const opacity =
          age < 0
            ? 0
            : interpolate(age, [0, 4], [0, 1], { extrapolateRight: "clamp" });

        return (
          <span
            key={i}
            style={{
              fontFamily: FONT_FAMILY,
              fontSize,
              color,
              visibility: age < 0 ? "hidden" : "visible",
              opacity,
              display: "inline",
            }}
          >
            {char}
          </span>
        );
      })}
      <WritingHand
        chars={chars}
        startFrame={startFrame}
        framesPerChar={framesPerChar}
        fontSize={fontSize}
      />
    </div>
  );
};

// ========== Text Overlay Wrapper ==========
interface TextOverlayProps {
  config: any;
  sceneDurationFrames: number;
}

const TextOverlay: React.FC<TextOverlayProps> = ({
  config,
  sceneDurationFrames,
}) => {
  const { fps } = useVideoConfig();
  const drawAtFrame = (config.drawAt ?? 0) * fps;
  const durationFrames = (config.duration ?? config.text.length * 0.3) * fps;

  if (config.style === "fade") {
    return (
      <FadeOverlay
        config={config}
        startFrame={drawAtFrame}
        durationFrames={durationFrames}
      />
    );
  }

  return (
    <HandwrittenText
      text={config.text}
      startFrame={drawAtFrame}
      durationFrames={durationFrames}
      x={config.x}
      y={config.y}
      fontSize={config.fontSize}
      color={config.color}
    />
  );
};

const FadeOverlay: React.FC<{
  config: any;
  startFrame: number;
  durationFrames: number;
}> = ({ config, startFrame, durationFrames }) => {
  const frame = useCurrentFrame();
  const age = frame - startFrame;

  const opacity = interpolate(
    age,
    [0, 10, durationFrames - 10, durationFrames],
    [0, 1, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  return (
    <div
      style={{
        position: "absolute",
        left: config.x,
        top: config.y,
        transform: "translate(-50%, -50%)",
        fontFamily: FONT_FAMILY,
        fontSize: config.fontSize,
        color: config.color,
        opacity,
        zIndex: 15,
      }}
    >
      {config.text}
    </div>
  );
};

// ========== Progress Bar ==========
interface ProgressBarProps {
  current: number;
  total: number;
}

const ProgressBar: React.FC<ProgressBarProps> = ({ current, total }) => (
  <div
    style={{
      position: "absolute",
      bottom: 40,
      left: 80,
      width: 1760,
      zIndex: 40,
    }}
  >
    <div
      style={{ display: "flex", justifyContent: "flex-start", gap: 8, marginBottom: 6 }}
    >
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          style={{
            fontFamily: FONT_FAMILY,
            fontSize: 16,
            color: i + 1 === current ? C.accent : "#888",
            opacity: i < current ? 1 : 0.3,
            marginRight: 8,
          }}
        >
          {i + 1}/{total}
        </div>
      ))}
    </div>
    <div
      style={{
        width: "100%",
        height: 4,
        borderRadius: 2,
        backgroundColor: "rgba(0,0,0,0.08)",
      }}
    >
      <div
        style={{
          width: `${(current / total) * 100}%`,
          height: "100%",
          borderRadius: 2,
          backgroundColor: C.accent,
          transition: "width 0.3s",
        }}
      />
    </div>
  </div>
);

// ========== Scene Background Wrapper ==========
interface SceneBackgroundProps {
  children: React.ReactNode;
}

const SceneBackground: React.FC<SceneBackgroundProps> = ({ children }) => (
  <AbsoluteFill style={{ backgroundColor: C.bg }}>{children}</AbsoluteFill>
);

// ========== Main Composition ==========
interface WhiteboardVideoProps {
  timeline: Timeline;
  storyboard: any;
  svgData: Record<string, SVGSceneData>;
}

export const WhiteboardVideo: React.FC<WhiteboardVideoProps> = ({
  timeline,
  storyboard,
  svgData,
}) => {
  const totalF = timeline.totalFrames;
  const hasAudio = storyboard.meta.pipeline.mode === "full";
  const fps = timeline.fps;
  const subtitleFontSize = storyboard.meta.subtitle?.fontSize || 36;
  const transitionFrames = timeline.transitionDurationFrames || 25;

  const bgmVolume = (frame: number) => {
    const fadeIn = interpolate(frame, [0, 30], [0, 0.03], {
      extrapolateRight: "clamp",
    });
    const fadeOut = interpolate(frame, [totalF - 30, totalF], [0.03, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return Math.min(fadeIn, fadeOut);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {/* Background music */}
      {storyboard.meta.pipeline.mode !== "full" && (
        <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />
      )}

      {/* Scenes */}
      {timeline.scenes.map((tScene, i) => {
        const scene = storyboard.scenes.find(
          (s: StoryboardScene) => s.id === tScene.id,
        );
        if (!scene) return null;

        const isLast = i === timeline.scenes.length - 1;

        // SVG 路径数据
        const sceneSvg = svgData[tScene.id];
        const hasSvgData = sceneSvg && sceneSvg.elements && sceneSvg.elements.length > 0;

        // Build subtitle segments from element narrations
        const subSegs = tScene.elements
          ? tScene.elements
              .filter((e: ElementTimeline) => e.narration)
              .map((elem: ElementTimeline) => ({
                text: elem.narration,
                startTime: elem.drawAtFrame / fps,
                endTime: (elem.drawAtFrame + elem.drawDurationFrames) / fps,
              }))
          : [
              {
                text: scene.voiceText || "",
                startTime: 0,
                endTime: tScene.durationFrames / fps,
              },
            ];

        const filteredSubs = subSegs.filter((s: any) => s.text);

        return (
          <Sequence
            key={tScene.id}
            from={tScene.startFrame}
            durationInFrames={tScene.durationFrames}
          >
            <SceneBackground>
              {/* SVG 路径动画（替代旧版 Video） */}
              {hasSvgData ? (
                <SVGDrawAnimation
                  elements={sceneSvg.elements}
                  drawAtFrames={tScene.elements?.map((e) => e.drawAtFrame) || []}
                  drawDurations={
                    tScene.elements?.map((e) => e.drawDurationFrames) || []
                  }
                  viewBox={sceneSvg.viewBox}
                  showHand={!storyboard.meta?.noHand}
                />
              ) : (
                /* Fallback: show empty white background */
                null
              )}

              {/* Subtitles */}
              {filteredSubs.length > 0 && (
                <Subtitle segments={filteredSubs} fontSize={subtitleFontSize} />
              )}

              {/* Drawing sound effects (单层) */}
              {tScene.elements && tScene.elements.length > 0 && (
                <DrawingSFX elements={tScene.elements} />
              )}

              {/* Scene audio (TTS for full mode) */}
              {hasAudio && (
                <Audio
                  src={staticFile(`audio/${scene.id}_mixed.wav`)}
                  volume={5.0}
                />
              )}

              {/* Text overlay (handwritten text) */}
              {scene.textOverlay && (
                <TextOverlay
                  config={scene.textOverlay}
                  sceneDurationFrames={tScene.durationFrames}
                />
              )}

              {/* Paper pull transition (场景间转场) */}
              {!isLast && (
                <PaperPullTransition
                  startFrame={tScene.durationFrames - transitionFrames}
                  durationFrames={transitionFrames}
                />
              )}

              {/* Progress bar */}
              <ProgressBar
                current={i + 1}
                total={timeline.scenes.length}
              />
            </SceneBackground>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
