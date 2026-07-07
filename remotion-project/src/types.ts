/**
 * types.ts - TypeScript type definitions for the whiteboard video pipeline.
 *
 * All types use scene-relative frame references (not global frame numbers)
 * for per-Scene internal timing.
 */

export interface ElementTimeline {
  id: string;
  sketchAtFrame: number; // Scene-relative frame
  sketchDurationFrames: number;
  colorizeAtFrame: number; // Scene-relative frame
  colorizeDurationFrames: number;
  narration: string;
}

export interface SceneTimeline {
  id: string;
  startFrame: number; // Global frame (Composition-level)
  durationFrames: number;
  elements?: ElementTimeline[];
}

export interface Timeline {
  fps: number;
  totalFrames: number;
  frameReference: "scene-relative";
  drawMode: "sketch_first" | "sequential";
  scenes: SceneTimeline[];
}

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

export interface StoryboardScene {
  id: string;
  imagePrompt: string;
  voiceText: string;
  duration: number | null;
  elements?: StoryboardElement[];
  textOverlay?: TextOverlayConfig;
}

export interface CameraConfig {
  enabled?: boolean;
  maxZoom?: number;
  transitionMs?: number;
}

export interface Storyboard {
  meta: {
    title: string;
    topic: string;
    fps: number;
    width: number;
    height: number;
    imageStyle: string;
    imageAspectRatio: string;
    drawMode: "sketch_first" | "sequential";
    pipeline: { mode: string; defaultSceneDuration: number | null };
    camera?: CameraConfig;
    tts: { provider: string; voice: number; speed: number };
    subtitle: { enabled: boolean; fontSize: number };
    transition: { type: string; durationFrames: number };
    animationEngine: string;
  };
  scenes: StoryboardScene[];
}
