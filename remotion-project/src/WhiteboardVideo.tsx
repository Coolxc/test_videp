/**
 * WhiteboardVideo.tsx - 白板视频主合成组件（V2：轮廓驱动 + 后画动画 + PenWipe）
 *
 * V2 核心变化：
 *  - MaskRevealAnimation V2：轮廓驱动笔尖 + 空间邻近蒙版
 *  - PostDrawAnimation：元素画完后 9 种 Transform 动画
 *  - PenWipeTransition：马克笔转场（替代旧版 HandWipeTransition）
 *  - 数据格式：DrawingPathV2（含 layer 字段）
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
  DrawingSceneData,
  ElementTimelineV2,
  DrawingPathV2,
} from "./types";
import MaskRevealAnimation from "./MaskRevealAnimation";
import PostDrawAnimation from "./PostDrawAnimation";
import PenWipeTransition from "./PenWipeTransition";

// ========== Design Tokens ==========
const C = {
  bg: "#FFFFFF",
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

// ========== Drawing Sound Effects ==========
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

// ========== Handwritten Text (unchanged) ==========
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
  if (!config || !config.text) {
    return null;
  }
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

// ========== Build element bbox map from storyboard ==========

function buildBboxMap(scene: StoryboardScene): Record<string, { x: number; y: number; w: number; h: number }> {
  const map: Record<string, { x: number; y: number; w: number; h: number }> = {};
  for (const elem of scene.elements || []) {
    if (elem.bbox) {
      map[elem.id] = elem.bbox;
    }
  }
  return map;
}

// ========== Main Composition ==========
interface WhiteboardVideoProps {
  timeline: Timeline;
  storyboard: any;
  drawingPathsData: Record<string, DrawingSceneData>;
}

export const WhiteboardVideo: React.FC<WhiteboardVideoProps> = ({
  timeline,
  storyboard,
  drawingPathsData,
}) => {
  const totalF = timeline.totalFrames;
  const hasAudio = storyboard.meta.pipeline.mode === "full";
  const fps = timeline.fps;
  const subtitleFontSize = storyboard.meta.subtitle?.fontSize || 36;
  const transitionFrames = timeline.transitionDurationFrames || 25;
  const penStyle = storyboard.meta.penStyle || "marker";

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

        // 蒙版路径数据
        const scenePaths = drawingPathsData[tScene.id];
        const hasDrawingPaths = scenePaths && scenePaths.paths && scenePaths.paths.length > 0;

        // 元素 bbox 映射（后画动画需要）
        const elementBboxMap = buildBboxMap(scene);

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
              {/* PNG 蒙版揭示动画（V2：轮廓驱动 + 空间邻近蒙版） */}
              {hasDrawingPaths ? (
                <MaskRevealAnimation
                  imageSrc={staticFile(`images/${tScene.id}.png`)}
                  drawingPaths={scenePaths.paths as DrawingPathV2[]}
                  drawAtFrames={tScene.elements?.map((e) => e.drawAtFrame) || []}
                  drawDurations={
                    tScene.elements?.map((e) => e.drawDurationFrames) || []
                  }
                  elementIds={tScene.elements?.map((e) => e.id) || []}
                  brushRadius={50}
                  penStyle={penStyle}
                  showHand={!storyboard.meta?.noHand}
                />
              ) : (
                null
              )}

              {/* 后画动画（元素画完后独立触发） */}
              {tScene.elements?.filter((e: ElementTimelineV2) => e.postAnimation).map((elem: ElementTimelineV2) => (
                <PostDrawAnimation
                  key={`anim-${elem.id}`}
                  imageSrc={staticFile(`images/${tScene.id}.png`)}
                  bbox={elementBboxMap[elem.id] || { x: 0, y: 0, w: 1920, h: 1080 }}
                  animation={elem.postAnimation!}
                  triggerFrame={elem.animationStartFrame ?? 0}
                  freezeFrame={elem.animationFreezeFrame ?? tScene.durationFrames}
                />
              ))}

              {/* Subtitles */}
              {filteredSubs.length > 0 && (
                <Subtitle segments={filteredSubs} fontSize={subtitleFontSize} />
              )}

              {/* Drawing sound effects */}
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

              {/* Pen wipe transition (马克笔转场，替代旧版 HandWipeTransition) */}
              {!isLast && (
                <PenWipeTransition
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
