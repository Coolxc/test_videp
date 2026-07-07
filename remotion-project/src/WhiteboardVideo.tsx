import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  interpolate,
  spring,
  useVideoConfig,
  Img,
  Video,
} from "remotion";
import "@fontsource/zcool-kuaile";

import { Timeline, SceneTimeline, ElementTimeline, TextOverlayConfig } from "./types";

// ========== Design Tokens ==========
const C = {
  bg: "#F6F1E3",
  grid: "#E0DDD5",
  accent: "#C05050",
  text: "#2D3748",
  subtitleBg: "rgba(45, 55, 72, 0.85)",
  white: "#FFFFFF",
};

const FONT_FAMILY = "'ZCOOL KuaiLe', sans-serif";
const FPS = 30;

// ========== Grid Background ==========
const Grid: React.FC = () => {
  const lines: React.ReactNode[] = [];
  for (let x = 0; x <= 1920; x += 100) {
    lines.push(
      <line key={`v${x}`} x1={x} y1={0} x2={x} y2={1080} stroke={C.grid} strokeWidth={0.5} />
    );
  }
  for (let y = 0; y <= 1080; y += 100) {
    lines.push(
      <line key={`h${y}`} x1={0} y1={y} x2={1920} y2={y} stroke={C.grid} strokeWidth={0.5} />
    );
  }
  return <svg width={1920} height={1080} style={{ position: "absolute" }}>{lines}</svg>;
};

// ========== Subtitle ==========
interface SubtitleProps {
  segments: Array<{ text: string; startTime: number; endTime: number }>;
}

const Subtitle: React.FC<SubtitleProps> = ({ segments }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const currentSeg = segments.find(
    (s) => currentTime >= s.startTime && currentTime < s.endTime
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
            fontSize: 36,
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
      <React.Fragment key={elem.id}>
        {/* Pen sketch SFX */}
        <Sequence from={elem.sketchAtFrame} durationInFrames={elem.sketchDurationFrames}>
          <Audio
            src={staticFile("assets/sfx/pen_sketch.mp3")}
            loop
            volume={(f) => {
              const dur = elem.sketchDurationFrames;
              if (dur <= 0) return 0;
              const fadeIn = interpolate(f, [0, 5], [0, 0.12], { extrapolateRight: "clamp" });
              const fadeOut = interpolate(f, [dur - 5, dur], [0.12, 0], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              return Math.min(fadeIn, fadeOut);
            }}
          />
        </Sequence>

        {/* Marker colorize SFX */}
        <Sequence from={elem.colorizeAtFrame} durationInFrames={elem.colorizeDurationFrames}>
          <Audio
            src={staticFile("assets/sfx/marker_color.mp3")}
            loop
            volume={(f) => {
              const dur = elem.colorizeDurationFrames;
              if (dur <= 0) return 0;
              const fadeIn = interpolate(f, [0, 5], [0, 0.08], { extrapolateRight: "clamp" });
              const fadeOut = interpolate(f, [dur - 5, dur], [0.08, 0], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              return Math.min(fadeIn, fadeOut);
            }}
          />
        </Sequence>
      </React.Fragment>
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

const WritingHand: React.FC<WritingHandProps> = ({ chars, startFrame, framesPerChar, fontSize }) => {
  const frame = useCurrentFrame();

  // Find which char is currently being written
  for (let i = chars.length - 1; i >= 0; i--) {
    const charStart = startFrame + i * framesPerChar;
    if (frame >= charStart) {
      const charProgress = (frame - charStart) / framesPerChar;
      if (charProgress < 0.5) {
        // Show hand near this character
        const x = 12 + i * (fontSize * 0.65);
        const y = fontSize * 0.1;
        return (
          <Img
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
  const chars = [...text]; // Correctly splits CJK characters
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

        const scale =
          age < 0
            ? 0
            : spring({
                frame: Math.max(0, age),
                fps,
                config: { stiffness: 300, damping: 20 },
              });

        return (
          <span
            key={i}
            style={{
              fontFamily: FONT_FAMILY,
              fontSize,
              color,
              visibility: age < 0 ? "hidden" : "visible",
              opacity,
              transform: `scale(${scale})`,
              transformOrigin: "center bottom",
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
  config: TextOverlayConfig;
  sceneDurationFrames: number;
}

const TextOverlay: React.FC<TextOverlayProps> = ({ config, sceneDurationFrames }) => {
  const { fps } = useVideoConfig();
  const drawAtFrame = (config.drawAt ?? 0) * fps;
  const durationFrames = (config.duration ?? config.text.length * 0.3) * fps;

  if (config.style === "fade") {
    return <FadeOverlay config={config} startFrame={drawAtFrame} durationFrames={durationFrames} />;
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
  config: TextOverlayConfig;
  startFrame: number;
  durationFrames: number;
}> = ({ config, startFrame, durationFrames }) => {
  const frame = useCurrentFrame();
  const age = frame - startFrame;

  const opacity = interpolate(age, [0, 10, durationFrames - 10, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

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
    <div style={{ display: "flex", justifyContent: "flex-start", gap: 8, marginBottom: 6 }}>
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
  <AbsoluteFill style={{ backgroundColor: C.bg }}>
    <Grid />
    {children}
  </AbsoluteFill>
);

// ========== Main Composition ==========
interface WhiteboardVideoProps {
  timeline: Timeline;
  storyboard: any;
}

export const WhiteboardVideo: React.FC<WhiteboardVideoProps> = ({ timeline, storyboard }) => {
  const totalF = timeline.totalFrames;
  const hasAudio = storyboard.meta.pipeline.mode === "full";
  const fps = timeline.fps;

  const bgmVolume = (frame: number) => {
    const fadeIn = interpolate(frame, [0, 30], [0, 0.03], { extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [totalF - 30, totalF], [0.03, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return Math.min(fadeIn, fadeOut);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {/* Background music */}
      <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />

      {/* Scenes */}
      {timeline.scenes.map((tScene, i) => {
        const scene = storyboard.scenes[i];
        if (!scene) return null;

        // Build subtitle segments from element narrations
        const subSegs = tScene.elements
          ? tScene.elements
              .filter((e: ElementTimeline) => e.narration)
              .map((elem: ElementTimeline) => ({
                text: elem.narration,
                startTime: elem.sketchAtFrame / fps,
                endTime: (elem.sketchAtFrame + elem.sketchDurationFrames) / fps,
              }))
          : [
              {
                text: scene.voiceText || "",
                startTime: 0,
                endTime: tScene.durationFrames / fps,
              },
            ];

        // Remove empty subtitle entries
        const filteredSubs = subSegs.filter((s: any) => s.text);

        return (
          <Sequence
            key={tScene.id}
            from={tScene.startFrame}
            durationInFrames={tScene.durationFrames}
          >
            <SceneBackground>
              {/* Whiteboard animation video */}
              <Video
                src={staticFile(`animations/${scene.id}_final.mp4`)}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                }}
              />

              {/* Subtitles */}
              {filteredSubs.length > 0 && <Subtitle segments={filteredSubs} />}

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

              {/* Progress bar */}
              <ProgressBar current={i + 1} total={timeline.scenes.length} />
            </SceneBackground>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
