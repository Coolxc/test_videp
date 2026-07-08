import React from "react";
import { Composition, registerRoot } from "remotion";
import { LightclawaceVideo } from "./LightclawaceVideo";
import { Prototype } from "./Prototype";

// timeline.json 作为单一事实源：totalFrames 自动读取，不用手填
import timeline from "./timeline.json";

const FPS = 30;
const WIDTH = 1080;
const HEIGHT = 1920;

// ========================================================================
// Canonical 视频注册
//
// 本项目采用"单视频活跃"模型：
//   - 同一时刻 src/scene-config.json 和 src/timeline.json 只属于一个视频
//   - 新视频 scaffold 时（scripts/new_video.sh）会覆盖这两个 JSON 文件
//   - index.tsx 的 Composition 组件引用 LightclawaceVideo 作为 canonical
//     渲染器，它会动态读取 scene-config/timeline，适配任何视频数据
//
// 如果需要注册多个"同时可预览"的视频变体，复制下面的 <Composition> 并改 id
// ========================================================================

const RemotionRoot: React.FC = () => (
  <>
    {/* 主视频：id 固定为 VideoMain，timeline.totalFrames 驱动时长 */}
    <Composition
      id="VideoMain"
      component={LightclawaceVideo}
      durationInFrames={timeline.totalFrames}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />

    {/* 开发原型：手绘风格组件 playground */}
    <Composition
      id="Prototype"
      component={Prototype}
      durationInFrames={150}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  </>
);

registerRoot(RemotionRoot);
