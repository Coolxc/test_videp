---
name: shorts-audio-engine
description: 一个专门为短视频设计的“情绪化声音引擎”。支持从脚本/字幕自动匹配音效 (SFX)、环境背景音 (Ambient) 以及多段主语音 (Voice) 的精准混音。通过引入人声呼吸感和随机延迟来消除“AI感”。
---

# Shorts 情绪声音引擎 (Emotional Voice Engine)

该引擎通过三层音频混合逻辑，为 AI 视频赋予“人类噪声层”和实时的情绪反馈。

## 核心特性
- **三层混音系统**：主语音 (100%) + 环境音 (15%) + 事件音 (40%)。
- **语义音效匹配**：自动检测关键词（如“敲门”、“核心”、“危险”）并触发对应音效。
- **去 AI 味处理**：加入音量呼吸感波动 (±1.0dB) 和随机时间偏移 (±50ms)，模拟不完美的真实录制效果。
- **环境循环**：支持背景白噪音或紧张氛围音的自动无限轮播。

## 目录结构
- `scripts/pipeline.py`: 核心调度中心。
- `scripts/mixer.py`: 音频合成逻辑。
- `scripts/sfx_library.py`: 关键词与音效映射库。
- `assets/audio/`: 存储所有的 `.wav` / `.mp3` 素材。

## 使用方法

### 1. 准备素材
确保 `assets/audio/` 目录下有以下基础文件：
- `room_ambience.wav` (默认环境)
- `knock.wav` (动作音效)
- `pencil_scratch.wav` (白板写字声)

### 2. 运行混合
使用虚拟环境运行：

```bash
/path/to/venv/bin/python scripts/pipeline.py \
  --data /path/to/storyboard.json \
  --assets ./assets/audio \
  --voice-dir ./output/voices \
  --output final_audio.mp3
```

## 参数说明
- `--data`: 输入的 Storyboard 或 SRT JSON。
- `--assets`: 音效库目录。
- `--voice-dir`: 已生成的配音文件目录（命名需遵循 `voice_0.mp3`, `voice_1.mp3`...）。
- `--output`: 最终输出路径。

## 故障排除
- **音频重叠不准**：检查 Storyboard 中的 `startTime` 是否为毫秒单位。
- **没有声音输出**：确认系统中已安装 `ffmpeg`。
