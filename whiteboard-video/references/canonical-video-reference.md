# Canonical Video Reference

**新架构（v2.0）：`LightclawaceVideo.tsx` 是数据驱动的 canonical 渲染器。**

**默认情况下新视频不需要复制 tsx，只需覆盖 JSON：**

1. 覆盖 `src/scene-config.json` 和 `src/timeline.json`
2. 放资源到 `public/audio/{topic}/` 和 `public/assets/{topic}/`
3. 跑 `npx remotion studio`（id=`VideoMain`）预览，再 `npx remotion render` 渲染

组件自动从 `meta.topic` 派生封面路径、从 `timeline.totalFrames` 派生时长。**除非你在引入新的元素类型或修改布局算法，否则不需要动 tsx。**

## 已经踩过的坑（canonical 实现已全部规避）

- roughjs 闪烁 → 改为内联 SVG（`RoughBox` 组件）
- 腾讯云 TTS 音量偏小 → `volume={5.0}`
- 场景切换黑屏 → 每个 Sequence 内重绘 Grid
- 字幕按字数分配不稳 → 改为按句数均分
- BGM 盖过旁白 → `0.03`（3%）
- Sequence 内 `useCurrentFrame()` 已是相对帧（不需加全局偏移）
- 封面硬编码 → 动态读 `meta.topic`

## 何时需要编辑 LightclawaceVideo.tsx

仅以下情况：

1. **引入新元素类型**（如 `table`、`chart`、自定义动画元素）——编辑 `renderElement()` + `TYPE_HEIGHT`
2. **修改布局算法**（`layoutScene`）——全部视频受影响
3. **修改组件实现**（Grid/Box/Subtitle/Arrow 等）——全部视频受影响
4. **引入新动画类型**（除 fade/pop 以外的）——新增组件并扩展 `AnimComp` 选择逻辑

**一次修改，所有视频受益**——这是 canonical 数据驱动设计的核心优势。

## 组件主体（已在 src/LightclawaceVideo.tsx 实现）

下面展示主 Composition 骨架，供理解架构。实际代码看 `{REMOTION_DIR}/src/LightclawaceVideo.tsx`。

```tsx
import sceneConfig from "./scene-config.json";
import timeline from "./timeline.json";

const NARRATION_VOL = sceneConfig.meta.ttsProvider === "tencent" ? 5.0 : 1.0;

export const LightclawaceVideo: React.FC = () => {
  const totalF = timeline.totalFrames;
  const topic = (sceneConfig as any).meta?.topic || "lightclawace";

  const bgmVolume = (frame: number) => {
    const fadeIn  = interpolate(frame, [0, 30], [0, 0.03], { extrapolateRight: "clamp" });
    const fadeOut = interpolate(frame, [totalF - 30, totalF], [0.03, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return Math.min(fadeIn, fadeOut);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Grid />
      <Audio src={staticFile("bgm.mp3")} loop volume={bgmVolume} />
      <Watermark />

      {/* 封面：路径从 meta.topic 动态拼接 */}
      {timeline.cover && sceneConfig.meta.cover && (
        <Sequence from={0} durationInFrames={timeline.cover.durationFrames}>
          <Cover src={staticFile(`assets/cover_${topic}.png`)} />
        </Sequence>
      )}

      {/* 逐场景渲染 */}
      {timeline.scenes.map((tScene, i) => {
        const sConfig = sceneConfig.scenes[i];
        const laid = layoutScene(sConfig.elements);
        const sceneDur = sConfig.duration;
        const subs = sConfig.subtitles;
        const subCount = subs.length;

        // 字幕时间：按句数均分
        const subSegs = subs.map((s: any, si: number) => ({
          text: s.text,
          startTime: (si / subCount) * sceneDur,
          endTime: ((si + 1) / subCount) * sceneDur,
        }));

        return (
          <Sequence key={tScene.id} from={tScene.startFrame} durationInFrames={tScene.durationFrames}>
            <AbsoluteFill style={{ backgroundColor: C.bg }}>
              <Grid />
              <Audio src={staticFile(sConfig.audio)} volume={NARRATION_VOL} />

              {laid.map((config, j) => {
                const trigger = sConfig.elements[j].trigger;
                const delay = (trigger / subCount) * sceneDur;
                const AnimComp = config.animation === "pop" ? Pop : Fade;
                return (
                  <AnimComp key={j} delay={delay}>
                    {renderElement(config)}
                  </AnimComp>
                );
              })}

              <Subtitle segments={subSegs} duration={sceneDur} />
              <ProgressBar current={i + 1} total={timeline.scenes.length} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
```

## Composition 注册（已在 src/index.tsx）

```tsx
import { LightclawaceVideo } from "./LightclawaceVideo";
import timeline from "./timeline.json";

<Composition
  id="VideoMain"                              // 固定 id，不需要按视频改
  component={LightclawaceVideo}
  durationInFrames={timeline.totalFrames}     // 自动从 JSON 读取
  fps={30} width={1080} height={1920}
/>
```

**新视频只覆盖 JSON 即可**，`VideoMain` 这个 id 永远不变。渲染命令固定：

```bash
npx remotion render src/index.tsx VideoMain --output <path>.mp4
```
