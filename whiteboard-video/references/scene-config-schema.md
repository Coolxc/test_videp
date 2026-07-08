# scene-config.json 完整 Schema

`scene-config.json` 是整个视频的**单一事实源**：演讲稿、字幕切分、动画触发、场景编排全部定义在这一个文件里。

`timeline.json` 是 `scene-config.json` 的**派生文件**（由 Step 4 自动生成），包含帧级精确的时间数据。**任何修改只改 scene-config.json，然后重新生成 timeline.json。**

两个 JSON 文件同时存放在：
- `{OUTPUT_DIR}/` — 归档副本
- `{REMOTION_DIR}/src/` — Remotion 代码直接 import 的位置

## 完整示例

```json
{
  "meta": {
    "title": "视频标题",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "pad": 0.3,
    "cover": "cover.png",
    "coverDuration": 0.5,
    "ttsProvider": "tencent",
    "topic": "lightclawace"
  },
  "scenes": [
    {
      "id": "scene1",
      "title": "场景标题",
      "audio": "audio/lightclawace/scene1.wav",
      "duration": null,

      "subtitles": [
        { "text": "第一句讲解文字" },
        { "text": "第二句讲解文字" },
        { "text": "第三句讲解文字" }
      ],

      "elements": [
        { "type": "title", "content": "跨平台通用方案", "row": 0, "trigger": 0, "animation": "fade" },
        { "type": "box",   "content": "OpenClaw",       "color": "pink",   "row": 1, "trigger": 1, "animation": "pop" },
        { "type": "box",   "content": "Claude Code",    "color": "blue",   "row": 1, "trigger": 1, "animation": "pop" },
        { "type": "box",   "content": "Codex CLI",      "color": "yellow", "row": 2, "trigger": 1, "animation": "pop" },
        { "type": "box",   "content": "Copilot",        "color": "dark",   "row": 2, "trigger": 1, "animation": "pop" },
        { "type": "svg",   "src": "assets/lightclawace/example.svg", "row": 3, "trigger": 2, "animation": "pop", "scale": 1.2 }
      ]
    }
  ]
}
```

> **element 没有 `position` 字段。** AI 只需标记 `row` 编号，布局由代码自动计算。

## meta 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `meta.title` | 是 | 视频标题 |
| `meta.fps` | 是 | 固定 30 |
| `meta.width` | 是 | 固定 1080 |
| `meta.height` | 是 | 固定 1920 |
| `meta.pad` | 是 | 场景间隔秒数，固定 0.3 |
| `meta.ttsProvider` | 是 | `"tencent"` 或 `"vibevoice"`，决定 TTS 命令和旁白音量 |
| `meta.topic` | 是 | 视频英文 slug，资产目录隔离用（如 `"lightclawace"`） |
| `meta.cover` | 否 | 封面图文件名（相对 {OUTPUT_DIR}），省略或 null 则无封面 |
| `meta.coverDuration` | 否 | 默认 0.5 秒，仅 cover 存在时生效 |

## scene 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `scenes[].id` | 是 | 场景唯一标识，如 `"scene1"` |
| `scenes[].title` | 是 | 场景标题（若在 elements 中需要，再以 title 元素出现） |
| `scenes[].audio` | 是 | TTS 音频文件路径（相对 {OUTPUT_DIR}），**必须带 topic 子目录**，如 `audio/{topic}/scene1.wav` |
| `scenes[].duration` | 否 | **禁止手填**，Step 3 TTS 生成后自动回填 |
| `scenes[].subtitles[]` | 是 | 至少 1 句。字幕时间按句数均匀分配 |
| `scenes[].elements[]` | 是 | 可以为空数组 `[]`（纯语音+字幕的过渡场景） |

## element 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `elements[].type` | 是 | 见下方「元素类型」表 |
| `elements[].row` | 是 | 行编号（从 0 开始），同 row 的元素自动并排居中 |
| `elements[].trigger` | 是 | 必须 `>= 0` 且 `< subtitles.length`，否则 Step 4 报错 |
| `elements[].animation` | 是 | `"fade"` 或 `"pop"` |
| `elements[].scale` | 否 | 仅 svg 类型可选，对 250px 基础尺寸做缩放，默认 1.0 |
| `elements[].widthScale` | 否 | 对同 row 平均分得的宽度再做缩放，默认 1.0 |
| `elements[].seed` | 否 | box/arrow 的 SVG 种子，保证渲染稳定，默认 42 |

多个元素可以绑定同一个 trigger（同时出现），但建议同一 trigger 不超过 3 个元素。

## 元素类型

| type | 必填字段 | 说明 |
|------|---------|------|
| `title` | `content` | 场景标题，T1 字号 64px |
| `box` | `content`, `color` | 内联 SVG 矩形+文字，color 可选 `"pink"` / `"blue"` / `"yellow"` / `"dark"` |
| `svg` | `src` | 手绘插图，`src` 相对 `{OUTPUT_DIR}`，通常在 `assets/{topic}/` 下 |
| `arrow` | 无 | 粗胖实心方块箭头，自动填满行内剩余空间 |
| `badge` | `content`, `color` | 编号圆形标注 |

> **AI 不需要指定任何 x, y, w, h, size 值。** 所有尺寸和位置由代码根据 `row` 自动计算。

## timeline.json 派生格式

由 Step 4 从 scene-config.json 计算而来，内含帧级精确数据：

```json
{
  "totalFrames": 5226,
  "totalDuration": 174.2,
  "cover": {
    "startFrame": 0,
    "durationFrames": 15
  },
  "scenes": [
    {
      "id": "scene1",
      "startFrame": 15,
      "durationFrames": 690,
      "duration": 23.0
    }
  ]
}
```

> timeline.json 只需保存**全局时间**（startFrame、durationFrames、duration）。字幕/元素的场景内相对时间由视频代码从 scene-config.json 按"句数均分"实时计算（见 canonical-video-reference.md）。
