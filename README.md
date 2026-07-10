# 手绘知识讲解视频生成管线 (Whiteboard Video Pipeline)

专业级白板手绘动画视频生成管线。用户提供故事板脚本 → 管线输出图片生成 Prompt → 用户用任意工具生成插画 → 自动检测元素区域 → 插画按叙事顺序"先描后涂"逐元素画出，虚拟镜头智能跟随聚焦 → 可选 TTS 配音 + 三层混音 → Remotion 合成字幕/音效/文字动画 → 输出成片。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- ffmpeg + ffprobe (in PATH)

### 安装

```bash
# Python 依赖
pip install -r requirements.txt

# Remotion 依赖
cd remotion-project && npm install && cd ..
```

### 使用流程

#### 两步流程（推荐）

```bash
# 第一步：生成图片 Prompt
python scripts/make_video.py --storyboard output/topic/storyboard.json --mode video_first

# 使用 Midjourney / DALL-E / SD 等工具生成图片，放入 output/topic/images/
# 可选：先跑区域检测辅助标注 bbox
python scripts/detect_regions.py output/topic/images/scene1.png

# 第二步：生成视频（含镜头运动 + 绘画音效）
python scripts/make_video.py --storyboard output/topic/storyboard.json --skip-prompts
```

#### 完整模式（需要 TTS API Key）

```bash
python scripts/make_video.py --storyboard output/topic/storyboard.json --mode full
```

## 项目结构

```
D:\Documents\video-pro\
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
├── plan.md                   # 完整设计方案
│
├── scripts/                  # Python 管线脚本
│   ├── make_video.py         # 总编排（含断点续跑）
│   ├── parse_storyboard.py   # 脚本 → storyboard.json
│   ├── generate_prompts.py   # 生成 Prompt（含空间分离引导）
│   ├── validate_images.py    # 图片校验
│   ├── detect_regions.py     # 自动区域检测
│   ├── generate_scene_animation.py  # 核心手绘动画引擎
│   ├── generate_animations.py       # 批量动画生成
│   ├── generate_default_sfx.py      # 合成音效生成
│   ├── compute_timeline.py   # 时间轴编排
│   ├── generate_subtitles.py # SRT 字幕生成
│   ├── tts_pipeline.py       # TTS 语音合成
│   ├── audio_mixer.py        # 三层混音
│   ├── deploy_resources.py   # 资源部署到 Remotion
│   ├── generate_publish.py   # 发布文案生成
│   └── validate.py           # 环境检查
│
├── remotion-project/         # Remotion 合成项目
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── index.tsx         # 入口注册
│   │   ├── types.ts          # TypeScript 类型
│   │   └── WhiteboardVideo.tsx  # 主合成器
│   └── public/
│       ├── bgm.mp3
│       ├── fonts/
│       └── assets/
│           ├── sfx/
│           └── writing-hand-small.png
│
├── whiteboard-video/         # 现有 Remotion 参考项目
├── whiteboard-video-workflow/ # 动画引擎 + 音频引擎
│
├── cache/tts/                # TTS 缓存
└── output/                   # 输出目录
```

## 核心特性

### 视觉真实感设计

- **虚拟镜头系统**：CameraVideoWriter 包装器，对每帧裁剪视口区域后缩放输出
- **先描后涂双程绘制**：Pass 1 全部线稿 → Pass 2 全部上色，视觉状态自洽
- **智能镜头过渡**：dip（背景淡出）用于 sketch 阶段、breathe（呼吸式缩放）用于 colorize 阶段
- **自适应笔刷半径**：按缩放反向补偿，屏幕视觉尺寸恒定
- **路径连续性修复**：仅当跳跃超阈值时触发最近邻重排
- **Ken Burns 微运镜**：Hold 阶段 97%→100% 极轻微缩放
- **手部一次加载+多尺寸缓存**：避免重复 I/O

### 管线设计

- **数据驱动**：`storyboard.json` 单一事实源，驱动全部下游产物
- **人机协作**：图片生成、区域标注是可审阅的检查点
- **断点续跑**：每步完成写 `.checkpoint.json`
- **零边际成本**：手绘动画、镜头运动、音效均本地生成

## 技术栈

| 层 | 技术 |
|---|------|
| 手绘动画引擎 | Python + OpenCV + NumPy |
| 视频合成 | Remotion (React) |
| 音效生成 | NumPy + pydub |
| TTS | 腾讯云 / edge-tts |
| 混音 | pydub |
| 字幕 | SRT 格式 |
