# Storyboard 编写指南

## 一、最小可运行示例

```json
{
  "meta": {
    "title": "我的视频标题",
    "topic": "my-video"
  },
  "scenes": [
    {
      "id": "scene1",
      "imagePrompt": "一个火柴人站在十字路口，左边是上班的路，右边是创业的路",
      "voiceText": "每个人都会面临选择的时刻。",
      "elements": [
        {
          "id": "person",
          "description": "火柴人站在十字路口",
          "bbox": {"x": 760, "y": 300, "w": 400, "h": 500},
          "narration": "每个人都会面临选择的时刻。"
        }
      ]
    }
  ]
}
```

这是能跑通管线的最小 storyboard。系统会自动补充所有缺失的默认值（fps、分辨率、TTS 配置等）。

---

## 二、完整字段说明

### 2-1. meta（视频元信息）

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `title` | **是** | — | 视频标题，用于展示 |
| `topic` | **是** | title 的小写 kebab-case | 输出目录名（如 `output/my-topic-20260711/`） |
| `fps` | 否 | 30 | 帧率 |
| `width` | 否 | 1920 | 画布宽度 |
| `height` | 否 | 1080 | 画布高度 |
| `style` | 否 | `"ipad_sketch"` | 画风，影响 prompt 生成 |
| `pipeline.mode` | 否 | `"video_first"` | `video_first`=无声视频+BGM，`full`=含 TTS 语音 |
| `tts.provider` | 否 | `"tencent"` | TTS 服务商（full 模式需要） |
| `tts.voice` | 否 | 602005 | 语音 ID |
| `tts.speed` | 否 | 1.1 | 语速 |
| `subtitle.enabled` | 否 | true | 是否显示字幕 |
| `subtitle.fontSize` | 否 | 36 | 字幕字号 |
| `noHand` | 否 | false | 设为 true 隐藏画手 |
| `styleGuide` | 否 | null | LLM 生成的风格指南（自动填充，不需要手写） |

**大多数 meta 字段不需要写**，系统会用合理的默认值。通常只需要 `title` 和 `topic`。

### 2-2. scenes（场景列表）

每个场景代表一张白板画面，按数组顺序播放。

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | **是** | — | 场景唯一 ID，如 `"scene1"`。也用作图片文件名（`scene1.png`） |
| `imagePrompt` | **是**（二选一） | — | 图片内容描述，用于生成图片的 prompt 素材 |
| `voiceText` | **是**（二选一） | `""` | 旁白/解说文案，用于字幕和时长计算 |
| `duration` | 否 | null（自动计算） | 场景时长（秒）。null 时根据旁白字数自动计算 |
| `elements` | 否 | 自动生成一个全画布元素 | 画面中的可绘制元素列表（**强烈建议手动定义**） |
| `textOverlay` | 否 | — | 画面上叠加的手写文字动画 |
| `imageName` | 否 | `"{id}.png"` | 自动生成，通常不需要手写 |

### 2-3. elements（元素列表）— 最重要的部分

**元素决定了手绘视频的核心效果**：手按什么顺序画什么内容。

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | **是** | — | 元素唯一 ID，如 `"person"`, `"clock"` |
| `description` | **是** | — | 元素描述，LLM 用它生成图片 prompt 和判断绘画策略 |
| `bbox` | **是** | — | 元素在画布上的位置和大小 `{x, y, w, h}` |
| `narration` | 否 | `""` | 画这个元素时显示的字幕（voiceText 的分段） |
| `drawAt` | 否 | null | 保留字段，当前未使用，系统自动计算绘制时间 |
| `drawStrategy` | 否 | LLM 自动判断，最终默认 `"spatial_walk"` | 绘画顺序策略（见下方）。优先级：用户手写 > LLM 自动生成 > 默认 `spatial_walk` |

#### elements 数组顺序 = 绘画顺序

**元素按数组顺序依次绘制**。第一个元素画完，停顿片刻，再画第二个。

```json
"elements": [
  {"id": "person", ...},   // ← 第 1 个画
  {"id": "clock", ...},    // ← 第 2 个画
  {"id": "money", ...}     // ← 第 3 个画
]
```

**设计元素顺序时，想象你在白板前讲课，你会先画什么？** 通常跟着旁白走——旁白先提到的元素先画。

#### bbox 坐标系

```
(0,0) ──────────────────────── (1920,0)
  │                                │
  │     bbox: {                    │
  │       "x": 700,  ← 左边距      │
  │       "y": 50,   ← 上边距      │
  │       "w": 400,  ← 宽度        │
  │       "h": 400   ← 高度        │
  │     }                          │
  │                                │
(0,1080) ──────────────────── (1920,1080)
```

- 坐标原点在左上角
- x 向右增大，y 向下增大
- 画布大小默认 1920×1080

**bbox 不需要完美精确**。它用于两个目的：
1. 告诉生图模型元素应该出现在画面的哪个区域
2. 路径提取时将骨架路径分配到对应元素（有 15% 的容错 padding）

**估算 bbox 的方法**：把画布想象成 3×3 九宫格（每格约 640×360），元素放在对应的格子里。

#### drawStrategy 绘画策略

| 策略 | 何时使用 | 绘画效果 |
|------|---------|---------|
| `spatial_walk` | 通用默认 | 从左上开始，手按空间邻近顺序平滑移动 |
| `top_down` | 人物、悬挂物 | 从上往下画（先头后身体） |
| `bottom_up` | 金字塔、建筑、层级图 | 从下往上画（先底部后顶部） |
| `left_right` | 时间线、流程图 | 从左到右画 |
| `outline_first` | 圆形图标、方框、封闭图形 | 先画外轮廓，再画内部细节 |
| `center_out` | 大脑、太阳、放射图 | 从中心向外画 |

**不写也可以**——系统会用 LLM 根据 `description` 自动判断最合适的策略。

### 2-4. textOverlay（可选：手写文字叠加）

在画面上叠加一个逐字出现的手写文字动画。

```json
"textOverlay": {
  "text": "判断",
  "x": 960,              // 文字中心 x
  "y": 500,              // 文字中心 y
  "fontSize": 120,
  "color": "#2D3748",
  "style": "handwritten", // "handwritten" 逐字出现 | "fade" 淡入淡出
  "drawAt": 0.7,          // 场景开始后 0.7 秒出现
  "duration": 1.5          // 持续 1.5 秒
}
```

---

> ⚠️ **重要：`textOverlay` 必须是对象格式**（如上所示），不能直接写成字符串。  
> ❌ 错误：`"textOverlay": "判断"`  
> ✅ 正确：`"textOverlay": { "text": "判断", "style": "handwritten", ... }`  
> 如果写成字符串，管线会丢失位置、字体、动画样式等配置，退化为使用默认值。

---

## 三、注意事项

### 3-1. 元素间必须留白

**元素的 bbox 不要重叠或紧贴**。元素间至少留 15% 画布宽度（~290px）的空白。

```
✗ 错误：元素紧贴
  ┌─────────┬─────────┐
  │ person  │  clock  │
  └─────────┴─────────┘

✓ 正确：元素间留白
  ┌─────────┐    ┌─────────┐
  │ person  │    │  clock  │
  └─────────┘    └─────────┘
```

原因：路径提取依赖 bbox 做元素分组，重叠的 bbox 会导致路径分配错误。

### 3-2. imagePrompt 描述构图而非风格

imagePrompt 应该**描述画面内容和空间布局**，不需要描述画风（系统自动加上画风 prompt）。

```
✗ 不好：
  "imagePrompt": "黑白线条手绘风格，一个人坐在电脑前，极简主义，无背景"

✓ 好：
  "imagePrompt": "画面左侧一个人坐在电脑前低头工作，头上冒汗珠；右上方一个巨大的闹钟时针飞速旋转；右下角散落几张纸币。各元素之间有明确的空白间隔。"
```

### 3-3. narration 是 voiceText 的分段

每个元素的 `narration` 应该是 `voiceText` 的一个片段。系统用 narration 的字数来分配绘制时间——字多的元素画得久，字少的画得快。

```json
{
  "voiceText": "还在单纯靠出卖劳动时间，来换取那点微薄的工资吗？",
  "elements": [
    {
      "id": "person",
      "narration": "还在单纯靠出卖劳动时间，"   // ← voiceText 的前半段
    },
    {
      "id": "clock",
      "narration": "来换取那点微薄的工资吗？"     // ← voiceText 的后半段
    },
    {
      "id": "money",
      "narration": ""                             // ← 无旁白，快速画过
    }
  ]
}
```

**没有 narration 的元素**会分配最小绘制时间（约 1 秒）。

### 3-4. 场景转场与绘制时序

上一场景和白板擦除动画需要 25 帧（~0.83s），**新场景的前 25 帧是空闲等待**，待白板完全擦净后才开始绘制。这是管线自动处理的，不需要手动配置。

```
场景1 ──── 绘制 ──── hold ── 擦除(25帧) ──┐
                                            ├── 空闲25帧 ── 场景2开始绘制
场景2 ── 空闲25帧 ── 绘制 ──── hold ── ...
```

元素的 `narration` 时间线会正确对齐这一等待，旁白不会在绘制前开始。

### 3-5. 不写 elements 时的行为

如果一个场景没有 `elements` 字段，系统会自动创建一个覆盖全画布的单元素：
```json
{"id": "full", "bbox": {"x": 0, "y": 0, "w": 1920, "h": 1080}}
```

效果：整张图作为一个整体被画出来，没有分区域的逐步绘制效果。**不推荐**——手动定义 elements 能获得更好的手绘效果。

### 3-5. scene id 命名规范

- 使用 `scene1`, `scene2`, `scene3`... 的格式
- id 同时用作图片文件名（`scene1.png`）
- 不要有空格或特殊字符

### 3-6. topic 命名规范

- 使用纯英文、数字、连字符
- 用作输出目录名（如 `output/ai-asset-20260711/`）
- 例：`"topic": "ai-asset"`, `"topic": "time-management"`

---

## 四、完整示例

```json
{
  "meta": {
    "title": "AI时代资产蓝图",
    "topic": "ai-asset",
    "pipeline": {"mode": "video_first"}
  },
  "scenes": [
    {
      "id": "scene1",
      "imagePrompt": "画面左侧一个人坐在电脑前低头工作，头上冒汗珠；右上方一个巨大的闹钟时针飞速旋转；右下角散落几张纸币。各元素之间有明确的空白间隔。",
      "voiceText": "还在单纯靠出卖劳动时间，来换取那点微薄的工资吗？",
      "elements": [
        {
          "id": "person",
          "description": "一个人坐在电脑前低头工作，头上冒汗珠",
          "bbox": {"x": 80, "y": 250, "w": 500, "h": 550},
          "narration": "还在单纯靠出卖劳动时间，",
          "drawStrategy": "top_down"
        },
        {
          "id": "clock",
          "description": "巨大的闹钟时针飞速旋转",
          "bbox": {"x": 700, "y": 50, "w": 400, "h": 400},
          "narration": "来换取那点微薄的工资吗？",
          "drawStrategy": "outline_first"
        },
        {
          "id": "money",
          "description": "散落的纸币",
          "bbox": {"x": 750, "y": 550, "w": 350, "h": 300},
          "narration": ""
        }
      ]
    },
    {
      "id": "scene2",
      "imagePrompt": "画面中间一个简洁的大脑轮廓，脑内中心留白，线条干净。",
      "voiceText": "停止做执行者，开始做拥有高阶判断力的决策者。",
      "elements": [
        {
          "id": "brain",
          "description": "大脑轮廓",
          "bbox": {"x": 560, "y": 190, "w": 800, "h": 700},
          "narration": "停止做执行者，开始做拥有高阶判断力的决策者。",
          "drawStrategy": "outline_first"
        }
      ],
      "textOverlay": {
        "text": "判断",
        "x": 960, "y": 500,
        "fontSize": 120, "color": "#2D3748",
        "style": "handwritten",
        "drawAt": 0.7, "duration": 1.5
      }
    },
    {
      "id": "scene3",
      "imagePrompt": "一座金字塔结构图，三层，底层最宽顶层最窄，每层中间各有一个简单图标。",
      "voiceText": "从执行到管理再到决策，这是每一个职场人的进阶之路。",
      "elements": [
        {
          "id": "pyramid",
          "description": "三层金字塔结构图",
          "bbox": {"x": 460, "y": 80, "w": 1000, "h": 920},
          "narration": "从执行到管理再到决策，这是每一个职场人的进阶之路。",
          "drawStrategy": "bottom_up"
        }
      ]
    }
  ]
}
```

---

## 五、管线运行流程

```bash
# 第一步：生成图片 prompt（在此暂停，等用户生成图片）
python scripts/make_video.py -s storyboard.json --mode video_first

# 用户根据 output/{topic}/prompts.md 中的 prompt 去生图
# 将生成的图片放到 output/{topic}/images/ 目录（文件名必须匹配 scene1.png, scene2.png...）

# 第二步：生成视频
python scripts/make_video.py -s storyboard.json --mode video_first --skip-prompts
```
