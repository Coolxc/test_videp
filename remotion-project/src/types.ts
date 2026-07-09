/**
 * types.ts - TypeScript type definitions for the SVG whiteboard video pipeline.
 *
 * All types use scene-relative frame references (not global frame numbers)
 * for per-Scene internal timing.
 *
 * Major changes from old pipeline:
 *  - SVGPathData / SVGElementData / SVGSceneData for SVG path animation
 *  - ElementTimeline simplified: drawAtFrame/drawDurationFrames only (no sketch/colorize)
 *  - Timeline gains transitionDurationFrames, drawMode fixed to "sequential"
 */

// ========== SVG Path Animation Types ==========

export interface SVGPathData {
  d: string;           // SVG path data
  stroke: string;      // 描边颜色
  strokeWidth: number;
  fill: string;        // "none" 或颜色
  length: number;      // 路径总长度（用于 stroke-dashoffset 动画）
  type: "stroke" | "fill";
}

export interface SVGElementData {
  id: string;
  paths: SVGPathData[];
  totalLength: number;
  narration?: string;
}

export interface SVGSceneData {
  sceneId: string;
  viewBox: string;
  elements: SVGElementData[];
  unassignedPaths?: SVGPathData[];
}

// ========== Timeline Types ==========

export interface ElementTimeline {
  id: string;
  drawAtFrame: number;          // Scene-relative frame
  drawDurationFrames: number;
  narration: string;
}

export interface SceneTimeline {
  id: string;
  startFrame: number;           // Global frame (Composition-level)
  durationFrames: number;
  elements?: ElementTimeline[];
}

export interface Timeline {
  fps: number;
  totalFrames: number;
  transitionDurationFrames: number;
  drawMode: "sequential";
  scenes: SceneTimeline[];
}

// ========== Storyboard Types ==========

export interface TextOverlayConfig {
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
  style?: "handwritten" | "fade";
  drawAt?: number; // Seconds into scene
  duration?: number; // Seconds
}

export interface StoryboardElement {
  id: string;
  description: string;
  bbox: { x: number; y: number; w: number; h: number };
  drawAt: number | null;
  narration: string;
}

export interface StyleGuide {
  colorPalette: string[];
  lineStyle: string;
  characterStyle?: string;
  iconStyle?: string;
  compositionRules?: string;
  moodAndTone?: string;
  consistencyNotes?: string;
}

export interface StoryboardScene {
  id: string;
  imagePrompt?: string;
  description?: string;
  voiceText: string;
  duration: number | null;
  imageName?: string;
  elements?: StoryboardElement[];
  textOverlay?: TextOverlayConfig;
}

export interface CameraConfig {
  enabled?: boolean;
  maxZoom?: number;
  transitionMs?: number;
}

export interface StoryboardMeta {
  title: string;
  topic: string;
  fps: number;
  width: number;
  height: number;
  imageStyle?: string;
  style?: "whiteboard" | "blackboard" | "notebook" | "refined_illustration" | "ipad_sketch" | "custom";
  styleGuide?: StyleGuide | null;
  imageAspectRatio: string;
  drawMode: "sequential";
  pipeline: { mode: string; defaultSceneDuration: number | null };
  tts: { provider: string; voice: number; speed: number };
  subtitle: { enabled: boolean; fontSize: number };
  transition: { type: string; durationFrames: number };
}

export interface Storyboard {
  meta: StoryboardMeta;
  scenes: StoryboardScene[];
}
