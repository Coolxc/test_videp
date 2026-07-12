/**
 * types.ts - TypeScript type definitions for the whiteboard video pipeline.
 *
 * All types use scene-relative frame references (not global frame numbers)
 * for per-Scene internal timing.
 *
 * Major changes from v07 → v08 (PNG Mask Reveal):
 *  - SVGPathData / SVGElementData / SVGSceneData → DrawingPath / DrawingSceneData
 *  - ElementTimeline unchanged: drawAtFrame/drawDurationFrames
 *  - Timeline gains transitionDurationFrames, drawMode fixed to "sequential"
 */

// ========== Mask Reveal (Drawing Path) Types ==========

export interface DrawingPath {
  d: string;           // SVG path d 属性（中心线 polyline）
  elementId: string;   // 归属元素 ID
}

export interface DrawingSceneData {
  paths: DrawingPath[];
}

// ========== SVG Path Animation Types (Deprecated in v08) ==========

/** @deprecated Replaced by DrawingPath + MaskRevealAnimation */
export interface SVGPathData {
  d: string;
  stroke: string;
  strokeWidth: number;
  fill: string;
  length: number;
  type: "stroke" | "fill";
}

/** @deprecated Replaced by DrawingSceneData */
export interface SVGElementData {
  id: string;
  paths: SVGPathData[];
  totalLength: number;
  narration?: string;
}

/** @deprecated Replaced by DrawingSceneData */
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
  penStyle?: "marker" | "hand" | "debug";
  transition: { type: string; durationFrames: number };
}

export interface Storyboard {
  meta: StoryboardMeta;
  scenes: StoryboardScene[];
}

// ========== V2 Types (Refactor 08) ==========

export interface DrawingPathV2 {
  d: string;
  elementId: string;
  layer: "outline" | "skeleton";
}

export interface DrawingSceneDataV2 {
  paths: DrawingPathV2[];
}

export type AnimationType =
  | "pulse" | "breathe" | "rotate" | "seesaw" | "bounce"
  | "shake" | "float" | "emphasis" | "wave";

export type AnimationSpeed = "slow" | "normal" | "fast";

export interface PostAnimation {
  type: AnimationType;
  speed: AnimationSpeed;
}

export interface ElementTimelineV2 extends ElementTimeline {
  postAnimation?: PostAnimation;
  animationStartFrame?: number;
  animationFreezeFrame?: number;
}

export interface SceneTimelineV2 extends SceneTimeline {
  elements?: ElementTimelineV2[];
}
