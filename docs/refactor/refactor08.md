
> 基于 17 个已确认设计决策的完整重构方案。
> 目标：以行业最佳效果为标准，不考虑工作量。

---

## 一、问题诊断

当前系统距离专业级手绘视频有四个核心 Gap：

### 1.1 笔尖与可见线条脱节

**现象**：SVG 线条在逐步显示，但笔尖在线条下方/旁边移动，视觉割裂。

**根因**：路径提取算法使用 skeletonize（形态学骨架化），产出的是图案的几何中心线，而非人类可见的边缘轮廓。蒙版笔刷宽 100px 沿中心线揭示，用户看到的新像素出现在中心线两侧 50px 处，但笔尖固定在中心线上。对于填充区域（如实心圆），骨架退化为内部的单个点，完全不是"画圆"的轨迹。

**关键文件**：
- `scripts/extract_drawing_paths.py` — skeletonize 算法
- `remotion-project/src/MaskRevealAnimation.tsx:169` — `getPointAtLength()` 笔尖定位

**行业对照**：专业工具（VideoScribe、Doodly）使用 SVG 原生路径，路径本身就是笔画，笔尖完美跟随。当前项目从光栅图逆向推断绘画过程，信息损失不可避免。

### 1.2 场景内绘制顺序不可控

**现象**：如跷跷板场景，应先画跷跷板再画人再画财产，但当前无法自动达到。

**根因**：系统功能上支持元素顺序（`elements[]` 数组顺序 = 绘制顺序），但需要用户手动定义每个元素的像素级 bbox，操作门槛过高。`auto_generate_single_element()` 在未定义元素时生成单个全画布元素，等于没有分区。

**关键文件**：
- `scripts/parse_storyboard.py:17-27` — auto_generate_single_element
- `scripts/compute_timeline.py:132-141` — 按数组顺序分配 drawAtFrame

### 1.3 storyboard.json 手写门槛过高

**现象**：用户只能提供简单的分镜脚本，但系统要求完整的 storyboard.json（含 bbox、drawStrategy 等技术字段）。

**根因**：storyboard.json 同时承担了"创作输入"和"技术配置"两个角色。用户需要写像素坐标、选择绘画策略——这些应该由系统自动推断。且 bbox 信息只有在图片生成后才能获取，但当前流程要求先有完整 storyboard 再生图。

**关键文件**：
- `scripts/parse_storyboard.py` — 只支持 JSON 输入
- `scripts/make_video.py` — 流程顺序

### 1.4 画完后元素无法动起来

**现象**：元素绘制完成后静止不动。专业视频中太阳会发光旋转、心会跳动、人物会冒汗。

**根因**：Remotion 技术上支持任意动画，但当前只实现了 `strokeDashoffset` 揭示动画和 `HandWipeTransition` 转场。没有元素级的后画动画系统。且当前图片是整张 PNG，无法对单个元素做独立变换（需要 clip-path 隔离）。

**关键文件**：
- `remotion-project/src/MaskRevealAnimation.tsx` — 只有揭示动画
- `remotion-project/src/WhiteboardVideo.tsx` — 无后画动画组件

---

## 二、架构转变

**核心原则**：让绘画过程信息正向流动，而非逆向推断。

```
当前流程（逆向推断）：
  用户手写 storyboard.json → LLM 生成图片 prompt → 用户生成 PNG
  → skeletonize 猜路径 → 猜顺序 → 渲染

目标流程（正向设计）：
  用户写 Markdown 脚本 → LLM 生成 storyboard 骨架
  → LLM 生成 prompt（含布局约束）→ 用户生成 PNG
  → Vision LLM 检测元素 bbox → 双层路径提取（轮廓+骨架）
  → 动画规划 → Remotion 渲染
```

---

## 三、设计决策记录

以下 17 个决策通过逐个 Grilling 确认，每个决策都经过多选项对比和推理。

### Decision 1: 图片生成路线

**选项**：A. LLM 生成 SVG / B. AI 生图 PNG + 轮廓提取 / C. 双轨制

**结论：B（PNG 路线）**

理由：
- 用户在外部平台（Midjourney/DALL-E/Seedream）生成 PNG，视觉质量远超 LLM 生成的 SVG
- 用户的 LLM（DeepSeek）有识图能力但无生图能力
- 已有成熟的 PNG 生图工作流

### Decision 2: 路径提取算法

**选项**：A. Canny 轮廓 / B. 双层路径（轮廓+填充）/ C. 骨架做蒙版 + 轮廓做笔跟踪

**结论：C（职责分离）**

理由：
- 骨架化用于蒙版揭示已验证有效——100px 蒙版笔刷沿骨架走能覆盖大部分内容
- 问题只在于笔尖跟的是骨架而非轮廓
- 分离两个职责：蒙版继续用骨架（已验证），笔尖换成轮廓（对齐可见边缘）
- 改动量最小，效果提升最直接

### Decision 3: 时钟同步策略

**选项**：A. 轮廓为主时钟 / B. 骨架为主时钟 / C. 双时钟独立

**结论：A（轮廓为主时钟）**

理由：
- 用户看到的是笔尖位置和图像出现
- 轮廓为时间基准 → 笔尖匀速沿轮廓走，运动自然流畅
- 蒙版揭示绑定轮廓进度 → 笔走到 30% 时蒙版也揭示 30%
- B 方案笔尖速度不均匀；C 方案笔和图会脱节

### Decision 4: 轮廓-骨架空间映射

**选项**：A. 空间邻近 / B. 统一进度百分比 / C. 区域分块

**结论：A（空间邻近）**

理由：
- 唯一能保证"笔到哪图出到哪"的方案
- 笔尖位置 (px, py) 周围半径 R 内的骨架路径按距离渐进揭示
- B 方案轮廓和骨架的排序可能完全不对应
- C 方案格子边界产生突兀跳变

核心公式：
```
骨架路径 i 的揭示进度 = max(0, 1 - distance(path_i_center, pen_position) / R)
```

历史上 reveal 达到 1.0 的路径保持揭示，不因笔尖远离而重新遮挡。

### Decision 5: 轮廓路径排序

**选项**：A. 复用 drawStrategy / B. 纯空间贪心 / C. 按骨架路径分组

**结论：C（按骨架分组）**

理由：
- 轮廓顺序与骨架顺序高度一致 → 两套路径天然同步
- 空间邻近映射只处理微观同步，不需要宏观跳跃修正
- 具体做法：每条轮廓绑定到最近的骨架路径，组间复用 drawStrategy 排序

### Decision 6: bbox 检测时机

**选项**：A. 图片生成后 / B. 路径提取后 / C. 双次检测

**结论：C（双次检测）**

理由：
- 第一次（prompt 阶段）：注入元素布局约束，引导图片生成时就把元素分开
- 第二次（图片生成后）：Vision LLM 精确检测实际 bbox
- 如果只在生成后检测，可能因元素重叠严重而无法分离

### Decision 7: bbox 检测失败降级

**选项**：A. 降级单元素 / B. 暂停让用户标注 / C. 多次重试 + 校验

**结论：C 兜底 A**

理由：
- 3 次 Vision 调用取共识，自动校验（不越界、面积合理、IoU ≤ 0.3）
- 通不过 → 降级单元素全画布，日志告知用户
- B 打断自动化流程，用户体验差

校验规则：
```python
def validate_bboxes(bboxes, img_w=1920, img_h=1080):
    for b in bboxes:
        # 不越界
        if b.x < 0 or b.y < 0 or b.x + b.w > img_w or b.y + b.h > img_h:
            return False
        # 面积 >= 画布 1%
        if b.w * b.h < img_w * img_h * 0.01:
            return False
    # 重叠度
    for i, j in combinations(range(len(bboxes)), 2):
        if iou(bboxes[i], bboxes[j]) > 0.3:
            return False
    return True
```

### Decision 8: 用户输入格式

**选项**：A. YAML / B. Markdown / C. 简化 JSON

**结论：B（Markdown）**

理由：
- 目标用户是内容创作者，Markdown 是最自然的书写格式
- 写完即是可读的分镜稿文档
- 解析精确度用 LLM 解决：Markdown → DeepSeek → storyboard JSON

输入格式示例：
```markdown
# 人生的平衡

## 场景一
画面：一个跷跷板，左边坐着上班族，右边堆满金币
旁白：人生就像一个跷跷板，工作和财富之间总要找到平衡点
绘制顺序：跷跷板 → 上班族 → 金币
动画：跷跷板-摆动, 金币-闪光

## 场景二
画面：天平两端，左边是心（健康），右边是金条
旁白：但如果失去了健康，所有的财富都没有意义
动画：心-心跳
```

### Decision 9: Markdown 解析可靠性

**选项**：A. 纯 LLM + schema 重试 / B. LLM + 程序修补 / C. A+B

**结论：C（LLM + 程序修补 + schema 校验）**

理由：
- 程序修补解决 80% 小问题（缺失字段、类型不对），不浪费 LLM 调用
- schema 校验兜底结构性错误
- 只有修补后仍不合格才重试 LLM（最多 3 轮）
- prompt 中包含完整 JSON 示例，LLM 模仿示例的稳定性远高于从描述推断

### Decision 10: 绘制顺序决策权

**选项**：A. 用户优先 / B. Vision LLM 优先 / C. 冲突时提示

**结论：A（用户绝对优先）**

理由：
- 这是创作工具，创作意图高于技术合理性
- 用户指定顺序有叙事节奏考量
- 遮挡瑕疵在 100px 蒙版笔刷下不明显
- Vision LLM 仅在用户未指定时作为默认值

### Decision 11: 笔的视觉形态

**选项**：A. 手图片增强旋转 / B. SVG marker 笔默认 / C. 手图片+镜像

**结论：B（SVG marker 笔默认）**

理由：
- 纯矢量，完美跟随任意角度旋转，不存在朝向问题
- 当前手图片只做 30% 旋转（`smoothedAngle * 0.3`），向左/向上画时朝向不对
- marker 笔与白板手绘风格完全匹配
- 手图片保留为 `penStyle: "hand"` 可选项

### Decision 12: 后画动画触发时机

**选项**：A. 画完立即开始到场景结束 / B. 全部画完统一触发 / C. 独立触发 + 转场前 freeze

**结论：C（独立触发 + freeze）**

理由：
- A 画面越来越吵；B 不够自然（画完太阳就该发光）
- C：每个元素画完后延迟 0.5s 独立触发，转场前 0.5s freeze 为静帧
- 视觉节奏最专业——YouTube 高端白板动画的标准做法

### Decision 13: 动画类型范围

**选项**：A. 9 种 Transform / B. Transform + 2 种 Sprite / C. 精选 5 种 Transform

**结论：A（9 种 Transform 全做）**

理由：
- 9 种共享同一个 `computeTransform` 函数，只是数学公式不同，每种 10 行代码
- 做 5 种和做 9 种工作量几乎无差
- Sprite 需要额外素材，留后续迭代

9 种动画类型：pulse（心跳）、breathe（呼吸）、rotate（旋转）、seesaw（跷跷板）、bounce（弹跳）、shake（抖动）、float（浮动）、emphasis（强调）、wave（波浪）

### Decision 14: 动画参数来源

**选项**：A. 硬编码 / B. LLM 推断参数 / C. 默认值 + 用户覆盖

**结论：C（3 档预设 + 用户自然语言选档）**

理由：
- A 过于死板（太阳慢转 vs 风车快转需要不同参数）
- B 不可靠（LLM 不擅长调具体动画数值）
- C：每种动画 3 档预设（慢/默认/快），用户写自然语言选档
- LLM 负责映射自然语言到 `{type, speed}` 结构，不推断具体数值

```markdown
动画：旋转(慢)      → {type: "rotate", speed: "slow"}
动画：心跳          → {type: "pulse", speed: "normal"}
动画：抖动(快)      → {type: "shake", speed: "fast"}
```

### Decision 15: 场景转场

**选项**：A. PenWipe 一种 / B. 3 种常用 / C. 5 种全部

**结论：A（PenWipe 一种）**

理由：
- 转场是效果感知最低的环节
- YouTube 95% 白板动画都用同一种转场
- 把 HandWipe 适配为与 SVG marker 笔一致即可
- 多种转场是很低优先级的锦上添花

### Decision 16: 管线运行模式

**选项**：A. 两段式 / B. 三段式 / C. 两段式 + `--review`

**结论：C（两段式 + 可选检查点）**

理由：
- 段一：Markdown → prompt（暂停等图片）
- 段二：图片就位后自动跑完
- `--review` 参数可在 Vision bbox 后暂停，输出标注预览图让用户检查
- 熟练用户跳过，新用户可检查建立信任

### Decision 17: 重构策略

**结论：完整重构，非渐进**

---

## 四、实现规格

### 4.1 新增文件

#### `scripts/parse_markdown_script.py` — Markdown 脚本解析器

**职责**：用户 Markdown 脚本 → storyboard 骨架 JSON（无 bbox）

**实现逻辑**：
1. 读取 Markdown 文件全文
2. 调用 `call_deepseek` 将 Markdown 转为 storyboard JSON
   - System prompt 包含完整 storyboard JSON schema + 示例
   - 指示：不生成 bbox 字段，只生成 scenes/elements/narration/drawOrder/postAnimations
3. 程序修补：`setdefault` 补全 meta 区所有缺省字段（复用 `parse_storyboard.py` 现有逻辑）
4. jsonschema 校验
5. 校验不过 → 错误信息拼入 prompt 重新调 LLM（最多 3 轮）
6. 输出 `storyboard-skeleton.json`

**复用**：
- `scripts/llm_client.py` — `call_deepseek_json()`
- `scripts/parse_storyboard.py` — `auto_generate_single_element()` + `enrich_draw_strategies()`

---

#### `scripts/detect_elements.py` — Vision LLM 元素检测

**职责**：图片生成后，用 DeepSeek Vision 检测元素 bbox + 推断绘制顺序

**核心函数**：
```python
def detect_element_bboxes(image_path: str, elements: list[dict],
                          max_retries: int = 3) -> list[dict]:
    """
    用 Vision LLM 检测图片中各元素的 bbox。

    Args:
        image_path: PNG 图片路径
        elements: storyboard 中的元素列表（含 id, description）

    Returns:
        elements 列表，每个元素补全了 bbox 字段
    """
```

**实现逻辑**：
1. 读取图片 → base64
2. 调用 `call_deepseek_vision_json()`，prompt 包含图片 + 元素列表
3. 自动校验 `validate_bboxes()`：不越界、面积 ≥ 1%、IoU ≤ 0.3
4. 不过 → 重试（最多 3 次，错误信息拼入 prompt）
5. 全失败 → 降级单元素全画布
6. 输出补全后的完整 storyboard

**绘制顺序逻辑**：
- 用户指定 `drawOrder` → 保留不动（Decision 10）
- 未指定 → Vision prompt 追加：基于遮挡关系和语义推断绘制顺序

**bbox 检查预览**（`--review` 模式）：
- 用 PIL 在原图上画彩色矩形（按绘制顺序从冷色→暖色）+ 标注序号和元素名
- 输出预览图路径，暂停等用户确认

---

#### `scripts/extract_contour_paths.py` — 轮廓路径提取

**职责**：从 PNG 提取 Canny 轮廓路径，用于笔尖跟踪

**核心函数**：
```python
def extract_contour_paths(image_path: str, elements: list[dict],
                          skeleton_paths: list[dict]) -> list[dict]:
    """
    从 PNG 提取轮廓路径（Canny + contour tracing），按骨架路径分组排序。

    Args:
        image_path: PNG 图片路径
        elements: 元素列表（含 bbox）
        skeleton_paths: 已提取的骨架路径（用于分组排序）

    Returns:
        [{"d": "M... L...", "elementId": "person", "layer": "outline"}, ...]
    """
```

**实现逻辑**：
1. 读取图片 → 灰度 → `cv2.Canny(gray, 50, 150)`
2. `cv2.findContours(edges, RETR_LIST, CHAIN_APPROX_SIMPLE)`
3. 过滤碎片轮廓（长度 < 10px）
4. RDP 简化（复用 `_simplify_path()`，epsilon=5.0）
5. 转 SVG path（复用 `_points_to_svg_polyline()`）
6. 按 element bbox 归属（复用 `_assign_paths_to_elements()`）
7. 按骨架路径分组排序：
   - 每条轮廓 → 找空间最近的骨架路径 → 绑定到同一组
   - 组内：按距骨架路径起点的距离排序
   - 组间：复用 drawStrategy 排好的骨架顺序

**输出**：`layer: "outline"` 标记的路径列表

---

#### `remotion-project/src/MarkerPen.tsx` — SVG 矢量马克笔

**Props**：
```typescript
interface MarkerPenProps {
  x: number;       // 笔尖 X
  y: number;       // 笔尖 Y
  angle: number;   // 运动方向角度（deg）
  opacity: number; // 0=抬笔, 1=落笔
}
```

**实现**：
- 纯 SVG：椭圆笔尖 + 矩形笔杆 + 圆角笔帽
- 笔尖在 (0,0)，笔杆向右下延伸 ~120px
- 整体按 `angle` 旋转，`transformOrigin: "0 0"`
- 颜色：笔尖 #333，笔杆 #888，笔帽 #555
- 尺寸：笔尖 8×4px，笔杆 120×6px，整体占画面约 7%

---

#### `remotion-project/src/PostDrawAnimation.tsx` — 后画动画

**Props**：
```typescript
interface PostDrawAnimationProps {
  imageSrc: string;
  bbox: { x: number; y: number; w: number; h: number };
  animation: { type: AnimationType; speed: "slow" | "normal" | "fast" };
  triggerFrame: number;   // 动画开始帧
  freezeFrame: number;    // 动画冻结帧
}

type AnimationType =
  | "pulse" | "breathe" | "rotate" | "seesaw" | "bounce"
  | "shake" | "float" | "emphasis" | "wave";
```

**实现**：
- `<div>` + `overflow: hidden` 裁出 bbox 区域
- 内部放完整 PNG，偏移 `left: -bbox.x, top: -bbox.y`
- 外层 div 应用 CSS transform
- `computeTransform(type, speed, age)` 返回 transform 字符串

**9 种动画参数表**：

| 类型 | 公式 | slow | normal | fast |
|------|------|------|--------|------|
| pulse | `scale(1 + abs(sin(t*π*freq)) * amp)` | freq=1, amp=0.03 | freq=1.5, amp=0.05 | freq=2.5, amp=0.08 |
| breathe | `scaleY(1 + sin(t*π*freq) * amp)` | freq=0.5, amp=0.02 | freq=0.8, amp=0.03 | freq=1.2, amp=0.05 |
| rotate | `rotate(t * speed deg)` | 30°/s | 60°/s | 120°/s |
| seesaw | `rotate(sin(t*π*freq) * amp deg)` | freq=0.4, amp=3° | freq=0.8, amp=5° | freq=1.5, amp=8° |
| bounce | `translateY(abs(sin(t*π*freq)) * -amp px)` | freq=1, amp=8 | freq=2, amp=15 | freq=3, amp=25 |
| shake | `translateX(sin(t*π*freq) * amp px)` | freq=4, amp=2 | freq=8, amp=4 | freq=15, amp=8 |
| float | `translateY(sin(t*π*freq) * amp px)` | freq=0.5, amp=5 | freq=1, amp=10 | freq=1.5, amp=18 |
| emphasis | `scale(1 + spring(t) * amp)` 衰减弹跳 | amp=0.1 | amp=0.2 | amp=0.35 |
| wave | `skewX(sin(t*π*freq) * amp deg)` | freq=0.8, amp=2° | freq=1.5, amp=4° | freq=2.5, amp=7° |

**触发逻辑**：
- `age = frame - triggerFrame`
- `age < 0` → 不渲染
- `frame > freezeFrame` → 使用 freezeFrame 时刻的 transform 值（静止）
- emphasis 类型只播一次（不循环）

---

### 4.2 修改现有文件

#### `scripts/llm_client.py` — 新增 Vision 调用

新增两个函数：

```python
def call_deepseek_vision(
    system_prompt: str,
    user_text: str,
    image_path: str,
    temperature: float = 0.3,
    max_tokens: int = 4000,
) -> str:
    """调用 DeepSeek Vision API（图片+文本输入）。"""
    # 读取图片 → base64
    # user message content 改为数组格式：
    # [{"type": "text", "text": ...}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
    # 其余复用 call_deepseek 的重试逻辑

def call_deepseek_vision_json(system_prompt, user_text, image_path, **kwargs) -> dict:
    """Vision 调用 + JSON 提取。"""
    # 复用 call_deepseek_json 的 JSON 提取逻辑
```

---

#### `scripts/extract_drawing_paths.py` — 扩展输出格式

改动：
- `extract_drawing_paths()` 返回值每条路径增加 `"layer": "skeleton"` 字段
- 新增 `extract_all_scenes_dual()` 函数：
  - 调用现有骨架提取
  - 调用 `extract_contour_paths.py` 的轮廓提取
  - 合并输出到 `drawing-paths.json`

保留不变的函数（供轮廓模块复用）：
- `_extract_branches()`, `_walk_chain()`, `_simplify_path()`, `_points_to_svg_polyline()`
- `_assign_paths_to_elements()`, `_sort_element_paths()`, `_greedy_spatial_walk()`

---

#### `scripts/make_video.py` — 流程重编排

新流程：
```
Step 1:  validate            环境检查（保留）
Step 2:  parse_script         Markdown → storyboard 骨架（新增）
                              输入为 .json 时走现有 parse_storyboard.py（兼容）
Step 3:  generate_prompts     image prompt + 元素布局约束（修改）
         ── 暂停：等用户生成 PNG ──
Step 4:  validate_images      图片校验 + 尺寸规范化（保留）
Step 5:  detect_elements      Vision bbox + 绘制顺序推断（新增）
         ── [--review] 可选暂停：输出标注预览图 ──
Step 6:  tts                  语音合成（保留，仅 full 模式）
Step 7:  compute_timeline     时间轴 + 后画动画时间（修改）
Step 8:  generate_sfx         音效（保留）
Step 9:  extract_paths        双层路径：骨架 + 轮廓（修改）
Step 10: generate_subtitles   字幕（保留）
Step 11: mix_audio            音频混合（保留，仅 full 模式）
Step 12: deploy + render      部署 + Remotion 渲染（修改）
Step 13: generate_publish     发布文案（保留）
```

输入检测：
```python
if input_file.endswith('.md'):
    storyboard = parse_markdown_script(input_file, output_path)
elif input_file.endswith('.json'):
    storyboard = parse_storyboard(input_file, output_path)
```

新增 `--review` 参数：Step 5 后输出标注预览图，暂停等用户确认。

---

#### `scripts/compute_timeline.py` — 新增后画动画时间

每个 element 新增字段：
```python
{
    "id": "sun",
    "drawAtFrame": 30,
    "drawDurationFrames": 60,
    "narration": "...",
    "postAnimation": {"type": "rotate", "speed": "normal"},  # 新增
    "animationStartFrame": 95,   # drawEndFrame + 15帧(0.5s delay)
    "animationFreezeFrame": 180, # sceneDuration - transitionFrames - 15帧
}
```

---

#### `scripts/generate_prompts.py` — 注入元素布局约束

在 per-scene prompt 中，如果 scene 有 elements 定义，追加：
```
画面布局要求：
- 以下元素必须在画面中清晰分离，元素之间保持明显间距（至少 50px）
- {element1.description}: 建议位于画面 {position}
- {element2.description}: 建议位于画面 {position}
- 元素不可重叠，每个元素应该占据独立的画面区域
```

位置建议由 LLM 在 prompt 中给出（如"左侧"/"中央"/"右侧"）。

---

#### `remotion-project/src/MaskRevealAnimation.tsx` — 核心重写

**新 Props**：
```typescript
interface MaskRevealV2Props {
  imageSrc: string;
  drawingPaths: DrawingPathV2[];    // 含 layer 字段
  drawAtFrames: number[];
  drawDurations: number[];
  elementIds: string[];
  brushRadius?: number;             // 默认 50
  penStyle?: "marker" | "hand" | "debug";  // 默认 "marker"
  showHand?: boolean;               // 兼容旧配置
}
```

**笔尖跟踪改动**：
- `findCurrentPath()` 只遍历 `layer === "outline"` 路径
- 时间分配按 outline 总长度
- 旋转系数 0.3 → 1.0（marker 笔完全跟随方向）

**蒙版揭示改动（空间邻近驱动）**：
```typescript
function computeSkeletonReveal(
  skeletonPath: DrawingPathV2,
  penPosition: {x: number, y: number} | null,
  brushRadius: number,
): number {
  if (!penPosition) return 0;
  const pathCenter = getPathCenter(skeletonPath.d);
  const dist = Math.hypot(pathCenter.x - penPosition.x, pathCenter.y - penPosition.y);
  if (dist <= brushRadius) return 1;
  if (dist >= brushRadius * 2) return 0;
  return 1 - (dist - brushRadius) / brushRadius;
}
```

- 已揭示路径（reveal 曾达 1.0）保持揭示，用 `revealedSet` 追踪
- skeleton 路径渲染用 `strokeDasharray`/`strokeDashoffset` 控制揭示进度

**笔形态切换**：
```typescript
{penStyle === "marker" && <MarkerPen x={...} y={...} angle={...} opacity={...} />}
{penStyle === "hand" && <DrawingHand ... />}
{penStyle === "debug" && <DebugCrosshair x={...} y={...} />}
```

**抬笔/落笔过渡**：
- 路径端点距离 > 50px → 抬笔(opacity 1→0) → 空移(不可见) → 落笔(opacity 0→1)
- 过渡时长 4 帧（~0.13s）

---

#### `remotion-project/src/WhiteboardVideo.tsx` — 集成后画动画 + PenWipe

1. 在 MaskRevealAnimation 后渲染 PostDrawAnimation：
```typescript
{tScene.elements?.filter(e => e.postAnimation).map(elem => (
  <PostDrawAnimation
    key={`anim-${elem.id}`}
    imageSrc={staticFile(`images/${tScene.id}.png`)}
    bbox={elementBboxMap[elem.id]}
    animation={elem.postAnimation}
    triggerFrame={elem.animationStartFrame}
    freezeFrame={elem.animationFreezeFrame}
  />
))}
```

2. `HandWipeTransition` → `PenWipeTransition`：
   - 白色矩形扫过保留
   - 前沿渲染 `<MarkerPen>`（角度 0°，从左到右）

---

#### `remotion-project/src/types.ts` — 类型扩展

新增：
```typescript
interface DrawingPathV2 {
  d: string;
  elementId: string;
  layer: "outline" | "skeleton";
}

interface PostAnimation {
  type: "pulse"|"breathe"|"rotate"|"seesaw"|"bounce"|"shake"|"float"|"emphasis"|"wave";
  speed: "slow"|"normal"|"fast";
}

interface ElementTimelineV2 extends ElementTimeline {
  postAnimation?: PostAnimation;
  animationStartFrame?: number;
  animationFreezeFrame?: number;
}
```

修改：`DrawingSceneData.paths` 类型 → `DrawingPathV2[]`

---

#### `remotion-project/src/HandWipeTransition.tsx` → `PenWipeTransition.tsx`

- 重命名
- 前沿渲染 `<MarkerPen>` 组件
- 笔角度 0°，Y 居中

---

### 4.3 不修改的文件

- `scripts/validate.py`
- `scripts/validate_images.py`
- `scripts/generate_default_sfx.py`
- `scripts/generate_subtitles.py`
- `scripts/tts_pipeline.py`
- `scripts/audio_mixer.py`
- `scripts/generate_publish.py`
- `scripts/config.py`（可能新增少量常量）
- `remotion-project/src/index.tsx`

---

### 4.4 新增依赖

**Python**（添加到 `requirements.txt`）：
- `opencv-python` — Canny 边缘检测 + 轮廓追踪
- `jsonschema` — storyboard schema 校验

**Node**：无新增。`@remotion/paths` 已存在。

---

## 五、Storyboard JSON Schema V2

兼容现有格式，新增字段均为可选：

```json
{
  "meta": {
    "title": "人生的平衡",
    "topic": "balance",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "style": "ipad_sketch",
    "penStyle": "marker",
    "pipeline": { "mode": "video_first" },
    "subtitle": { "enabled": true, "fontSize": 36 },
    "transition": { "type": "pen_wipe", "durationFrames": 25 }
  },
  "scenes": [
    {
      "id": "scene1",
      "imagePrompt": "...",
      "voiceText": "...",
      "elements": [
        {
          "id": "seesaw",
          "description": "跷跷板",
          "bbox": { "x": 200, "y": 400, "w": 1500, "h": 400 },
          "narration": "...",
          "drawStrategy": "left_right",
          "postAnimation": {
            "type": "seesaw",
            "speed": "normal"
          }
        }
      ]
    }
  ]
}
```

---

## 六、数据流总览

```
用户 Markdown 脚本 (.md)
  │
  ▼
parse_markdown_script.py ──DeepSeek──▶ storyboard-skeleton.json (无 bbox)
  │
  ▼
generate_prompts.py ──DeepSeek──▶ prompts.md (含元素布局约束)
  │
  ══ 暂停：用户在外部平台生成 PNG 图片，放入 images/ ══
  │
  ▼
validate_images.py ──▶ 尺寸规范化后的 PNG
  │
  ▼
detect_elements.py ──DeepSeek Vision──▶ storyboard-complete.json (含 bbox + 顺序)
  │                                       │
  ├── [--review] 输出标注预览图，等待确认 ──┘
  │
  ▼
compute_timeline.py ──▶ timeline.json (含 postAnimation 时间)
  │
  ▼
extract_drawing_paths.py ──▶ drawing-paths.json
  +                             ├── skeleton 路径 (layer: "skeleton") — 蒙版揭示
extract_contour_paths.py ──▶    └── outline 路径 (layer: "outline")  — 笔尖跟踪
  │
  ▼
deploy_resources.py ──▶ remotion-project/src/ 下的 JSON 数据文件
  │
  ▼
Remotion 渲染
  ├── MaskRevealAnimation: outline 驱动笔尖 + 空间邻近驱动 skeleton 蒙版
  ├── MarkerPen: SVG 矢量笔跟随 outline 路径
  ├── PostDrawAnimation: 元素画完后 9 种 Transform 动画
  └── PenWipeTransition: 马克笔转场
  │
  ▼
final.mp4
```

---

## 七、验证方案

### 7.1 单元验证

| 模块 | 验证方法 |
|------|---------|
| Markdown 解析 | 3 份不同复杂度的 .md 脚本 → 验证输出 JSON schema 合规性 |
| Vision bbox | 现有 output 中的 PNG → 调用 detect_elements → 人眼检查标注预览图 |
| 轮廓提取 | 对比同一图片的 skeleton vs outline 路径 → 验证轮廓覆盖可见边缘 |
| 空间邻近蒙版 | Remotion Studio 逐帧：笔尖位置和蒙版揭示区域是否空间一致 |
| MarkerPen | Remotion Studio：笔朝向是否跟随路径方向 |
| PostDrawAnimation | 每种动画类型录 3 秒片段验证效果 |
| PenWipeTransition | Remotion Studio 检查转场 |

### 7.2 端到端验证

1. 编写测试 Markdown 脚本（3 场景，含绘制顺序 + 后画动画）
2. 运行 `python scripts/make_video.py --input test.md`
3. 检查输出视频：
   - 笔尖是否跟着可见线条走（核心指标）
   - 绘制顺序是否符合 Markdown 指定
   - 后画动画是否在元素画完后触发、转场前 freeze
   - PenWipe 转场是否正常
4. 运行 `--review` 模式验证 bbox 标注预览图

### 7.3 回归验证

- 旧格式 storyboard.json → `make_video.py` 仍能处理（兼容性）
- 对比重构前后同一场景的渲染结果 → 视觉质量不降级