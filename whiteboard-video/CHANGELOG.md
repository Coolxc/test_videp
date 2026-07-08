# Changelog

## 2.1.0 (2026-04-20) — 改名 + 封面 + TTS 调速

- **Skill 重命名**：`video-template` → `whiteboard-video`（GitHub 发布用名）
- **封面生成**：优先使用 Agent 内置 `image_gen` 工具生成 9:16 竖版封面（1024×1536），nano banana / Midjourney 降级为备选方案
- **TTS 默认速度**：1.2 → 1.1（更自然的语速，约 6.5 字/秒）
- 每场景参考字数从 155-180 调整为 140-170
- 新增 `README.md`（GitHub 首页展示）+ `LICENSE`（MIT）

## 2.0.0 (2026-04-20) — 迁移性重构

**Breaking changes：**
- `.env` 路径从 `{CWD}/.env` 正式改为 `{SKILL_DIR}/.env`（脚本历来如此，文档对齐）
- `scenes[].audio` 路径必须带 topic 子目录：`audio/{topic}/scene1.wav`
- `assets` SVG 路径必须带 topic 子目录：`assets/{topic}/xxx.svg`
- Remotion 项目 `src/` 中移除 15 个历史视频 tsx（Tools/Skill/Sd/… 全部），只保留 `LightclawaceVideo.tsx` 作为 canonical 数据驱动渲染器
- `index.tsx` 重写：只注册 `VideoMain`（canonical 渲染器）和 `Prototype`（开发 playground），`durationInFrames` 从 `timeline.totalFrames` 自动读取
- **新视频不再需要新建 tsx 文件**（替换原 Step 6c/6d）——只要覆盖 `src/scene-config.json` 和 `src/timeline.json`
- `scripts/tts_tencent_long.py` 删除（死代码，功能被 `tts_batch.py` 覆盖）

**新增：**
- `scripts/setup.sh`：一键环境初始化（系统依赖检查、Python/Node 依赖安装、目录准备、.env.example 生成）
- `scripts/new_video.sh`：新视频工作区 scaffold（创建 output 目录 + scene-config 模板 + topic 子目录）
- `requirements.txt`：Python 依赖声明
- SKILL.md 新增 **Installation（含迁移指南）** 章节
- SKILL.md Troubleshooting 新增"迁移/环境相关"分节
- `.gitignore` 重写：白名单保留 `bgm.mp3` + `lightclawace` 示例资产

**修正：**
- SKILL.md 文档谎言：`.env` 路径与脚本对齐
- `LightclawaceVideo.tsx` 封面路径改为动态读 `meta.topic`（不再硬编码 lightclawace）

**清理：**
- `remotion-project/public/` 从 460MB 降到 19MB（删除历史视频的音频/SVG 资产）
- 移除所有 .DS_Store
- 移除 `remotion-project/out/`（历史渲染产物）

---

## 1.1.0 (2026-04-20) — 依赖内化

- 内化 gen-warm-pic 的封面提示词模板到 `references/cover-prompt.md`
- SKILL.md description 不再声称依赖"remotion 技能"（项目自带）
- vibevoice-tts 明确标注为"可选外部依赖"并提供 fallback 提示

---

## 1.0.0 (2026-04-20) — 主文档精简与经验沉淀

- SKILL.md 从 1108 行精简到 ~360 行，细节沉到 `references/` 按需加载
- 新增 5 个 references：
  - `script-writing.md` — 演讲稿写作指南
  - `scene-config-schema.md` — 数据源 schema
  - `layout-engine.md` — 自动布局引擎
  - `components.md` — 组件库实现
  - `canonical-video-reference.md` — canonical 渲染器参考
- 对齐 15 个实战视频经验：腾讯云 TTS 音量 5.0、BGM 3%、字幕按句数均分、内联 SVG 替代 roughjs、Sequence 内重绘 Grid 修复 PAD 黑帧
- 资产目录引入 topic 隔离约定
- 新增"踩坑经验"自动积累区域
