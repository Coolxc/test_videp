# whiteboard-video

> AI-powered whiteboard-style tech explainer video generator. From script to rendered video in one workflow.

手绘白板风格技术讲解视频生成器——从演讲稿到成品视频的一站式 AI 工作流。

## ✨ 特色

- 🎨 **手绘白板风格**：站酷快乐体 + 内联 SVG 矩形/箭头/徽章，方格纸背景，温暖的米白色调
- 🎙️ **自动语音合成**：内置腾讯云 TTS（专业梓欣 602005），可选本地 vibevoice-tts
- 📐 **数据驱动渲染**：一个 canonical 渲染器适配所有视频，只需覆盖 JSON 数据
- 🤖 **AI 友好**：为 Claude Code / WorkBuddy / Cursor 等 AI Agent 设计，SKILL.md 即工作指令
- 📱 **竖屏 9:16**：1080×1920，适合抖音/视频号/小红书等短视频平台
- 🖼️ **AI 封面生成**：内置 image_gen 优先，nano banana / Midjourney 降级
- 🎵 **自动配乐**：BGM 循环播放，音量 3%，开头结尾淡入淡出

## 📦 安装

```bash
# 1. 放到 skills 目录
git clone https://github.com/<your-username>/whiteboard-video.git \
  ~/.codebuddy/skills/skills/whiteboard-video

# 2. 一键初始化
cd ~/.codebuddy/skills/skills/whiteboard-video
bash scripts/setup.sh

# 3. 配置腾讯云 TTS 密钥
cp .env.example .env
# 编辑 .env 填入 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY
```

### 系统依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| Python 3 | 腾讯云 TTS 脚本 | macOS: `brew install python3` |
| Node.js ≥ 18 | Remotion 视频渲染 | macOS: `brew install node` |
| ffmpeg | 音频时长检测 (ffprobe) | macOS: `brew install ffmpeg` |
| npm | Node 依赖管理 | 随 Node.js 安装 |

## 🚀 快速开始

### 给 AI Agent 使用（推荐）

在支持 Skills 的 AI Agent（WorkBuddy / Claude Code / Cursor）中触发：

> "帮我把这篇文章做成一个手绘风格的讲解视频"

AI 会自动加载 `SKILL.md`，按流程引导你完成整个视频制作。

### 手动使用

```bash
# 1. 创建新视频工作区
bash scripts/new_video.sh my-topic

# 2. 编辑 output/my-topic-YYYYMMDD-HHmm/scene-config.json
#    填入演讲稿、元素、trigger 等

# 3. 生成 TTS
python3 scripts/tts_tencent.py --text "演讲稿文字" --output output/.../audio/my-topic/scene1.wav

# 4. 回填 duration，生成 timeline.json

# 5. 复制到 Remotion 项目
cp output/.../scene-config.json remotion-project/src/
cp output/.../timeline.json remotion-project/src/

# 6. 预览
cd remotion-project && npx remotion studio

# 7. 渲染
npx remotion render src/index.tsx VideoMain --output output/.../video.mp4 --concurrency=1
```

## 📁 项目结构

```
whiteboard-video/
├── SKILL.md                      # AI Agent 主指令（工作流程 + 设计规范）
├── CHANGELOG.md                  # 版本历史
├── VERSION                       # 当前版本
├── requirements.txt              # Python 依赖
├── .gitignore
│
├── references/                   # 按需加载的详细规范
│   ├── script-writing.md         #   演讲稿写作指南
│   ├── scene-config-schema.md    #   scene-config.json schema
│   ├── cover-prompt.md           #   封面提示词模板
│   ├── layout-engine.md          #   自动布局引擎
│   ├── components.md             #   组件库实现
│   └── canonical-video-reference.md  # canonical 渲染器参考
│
├── scripts/
│   ├── setup.sh                  # 一键环境初始化
│   ├── new_video.sh              # 新视频工作区 scaffold
│   ├── tts_tencent.py            # 腾讯云 TTS（单段）
│   └── tts_batch.py              # 腾讯云 TTS（长文本分片拼接）
│
└── remotion-project/             # Remotion 视频项目
    ├── package.json
    ├── tsconfig.json
    ├── public/
    │   ├── bgm.mp3               # 背景音乐（必备）
    │   ├── audio/{topic}/        # 每个视频的 TTS 音频
    │   └── assets/{topic}/       # 每个视频的 SVG 素材
    └── src/
        ├── index.tsx             # Composition 注册（VideoMain + Prototype）
        ├── LightclawaceVideo.tsx # canonical 数据驱动渲染器
        ├── Prototype.tsx         # 组件 playground
        ├── scene-config.json     # 当前视频数据（单一事实源）
        └── timeline.json         # 当前视频时间轴（派生文件）
```

## 🎬 工作流概览

```
写演讲稿 → 设计 JSON → 用户确认 → TTS → 算时间轴 + 画 SVG（并行）
    → 覆盖 JSON + 拷资源 → Studio 预览 → 渲染输出
```

7 个 Step，2 次用户确认点（稿子 review + 预览 review），AI 负责所有中间环节。

详见 [SKILL.md](./SKILL.md)。

## ⚙️ 设计规范

| 项目 | 规格 |
|------|------|
| 画面 | 1080×1920，30fps，9:16 竖屏 |
| 背景 | 米白方格纸 `#F5F5F0` |
| 字体 | 站酷快乐体（T1 64px / T2 40px / T3 26px）|
| Box 风格 | 内联 SVG 矩形（粉/蓝/黄/深灰四色）|
| 箭头 | 粗胖实心方块箭头 |
| 旁白音量 | 腾讯云 TTS: `5.0`，vibevoice: `1.0` |
| BGM | 3%（0.03），1 秒淡入淡出，循环 |
| 动画 | Fade（淡入+上移）/ Pop（spring 弹入）|
| 封面 | 9:16 竖版，image_gen 优先 |

## 📝 License

MIT
