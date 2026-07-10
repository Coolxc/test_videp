/**
 * index.tsx - Remotion 根组件
 *
 * 载入 timeline.json + scene-config.json + drawing-paths.json，
 * 传递给 WhiteboardVideo 组件进行渲染。
 *
 * 数据通过 deploy_resources.py 从 Python 管线复制到 src/。
 */

import React from "react";
import { Composition, registerRoot } from "remotion";
import { WhiteboardVideo } from "./WhiteboardVideo";

import timeline from "./timeline.json";
import sceneConfig from "./scene-config.json";
import drawingPathsData from "./drawing-paths.json";

const FPS = 30;
const WIDTH = 1920;
const HEIGHT = 1080;

const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="VideoMain"
      component={() => (
        <WhiteboardVideo
          timeline={timeline as any}
          storyboard={sceneConfig}
          drawingPathsData={drawingPathsData as any}
        />
      )}
      durationInFrames={timeline.totalFrames || 300}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  );
};

registerRoot(RemotionRoot);
