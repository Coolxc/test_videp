---
name: whiteboard-video-workflow
description: V2 流量爆款版：从 SRT 自动生成完整白板动画视频。新增内容评分、分级过滤及 Hook 变体测试（Warning/Fear/Contrarian），支持矩阵多版本输出。当用户提供 SRT 并要求生成爆款/白板视频时触发。
---

# Whiteboard Video Workflow V2 (Viral Version)

从 SRT 字幕文件到“爆款级”白板动画视频的自动化生产系统。V2 版本引入了人性测试逻辑和分级生产策略。

## 输入参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `srtPath` | 是 | SRT 字幕文件的绝对路径 |
| `outputDir` | 否 | 输出根目录，默认为 SRT 文件所在目录 |
| `stage` | 否 | 当前阶段：`cold_start` (默认, 阈值4) / `growth` (阈值5) / `mature` (阈值7) |

## 工作流步骤

### 步骤 0: 环境预检
运行 `scripts/check_env.py`。获取 `PYTHON_PATH`，确认 `GEMINI_API_KEY` 或 `RUNNINGHUB_API_KEY` 已配置。
- **注意**：V2 需要 `opencv-python` 和 `av` 库，脚本会自动安装。系统优先使用 `GEMINI_API_KEY`（提供更直接的 Imagen 3 语义图片生成）。

### 步骤 1: 确定输出目录并初始化
使用 `scripts/workflow_helper.py init-dirs` 创建目录结构。

### 步骤 2: 解析、评分与 Hook 提取（Subagent）
启动 **subagent**，使用 `references/storyboard-parser.md`。
- **目标**：生成带 `score`、`level` 和三种 `hooks` (Warning, Fear, Contrarian) 的 `storyboard.json`。
- **重要逻辑**：主 agent 获取返回结果后，检查 `score`。
    - 如果 `score` < 当前阶段阈值（冷启动默认为 4），**直接终止工作流**并告知用户建议优化脚本。

### 步骤 3: 确定生产策略（Matrix Logic）
根据 `level` 决定生成的变体数量（Variants）和视觉样式：

| Level (Score) | 变体数 | Hook 类型 | 视觉背景 |
| :--- | :--- | :--- | :--- |
| **Normal** (4-6) | 1 | Warning | 纯黑 |
| **Potential** (7-8) | 2 | Warning, Fear | 纯黑 |
| **Viral** (9-10) | 3 | Warning, Fear, Contrarian | 纯黑 + 模糊图混合 |

### 步骤 4: 生成分镜图片（Subagent）
启动 **subagent**，使用 `references/image-generator.md`。为所有分镜生成白板图。

### 步骤 5: 渲染 Hook 片段
主 agent 使用 `PYTHON_PATH` 调用 `scripts/render_hook.py` 为每个变体渲染 2 秒视频：
- **普通/潜力**：`--mode black`
- **爆款**：变体 1/2 用 `black`，变体 3 用 `--mode image --bg-image <第一帧路径>`。

### 步骤 6: 渲染白板动画片段（Subagent）
调用 `whiteboard-animation` 批量模式渲染所有分镜。

### 步骤 7: 组装矩阵视频
对每个变体，调用 `scripts/workflow_helper.py merge-videos`：
- `Variant A`: 合并 `Hook_Warning` + `动画片段`
- `Variant B` (如有): 合并 `Hook_Fear` + `动画片段`
- `Variant C` (如有): 合并 `Hook_Contrarian` + `动画片段`

### 步骤 8: 输出结果
输出最终的视频矩阵列表，并告知用户分发测试建议。

## 执行清单

1. [ ] **Step 0**: 环境检查 -> 获取 `PYTHON_PATH`
2. [ ] **Step 2**: Subagent 解析 SRT -> 获取 `storyboard.json`（含 score, level, hooks）
3. [ ] **Step 3**: 检查评分 -> 如果 < 4 则中止并反馈
4. [ ] **Step 4**: Subagent 生成图片
5. [ ] **Step 5**: 循环渲染 Hook 变体 (scripts/render_hook.py)
6. [ ] **Step 6**: Subagent 渲染动画片段 (whiteboard-animation)
7. [ ] **Step 7**: 循环合并视频 (scripts/workflow_helper.py merge-videos)
8. [ ] **Step 8**: 返回矩阵文件列表
