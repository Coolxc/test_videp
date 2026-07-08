#!/usr/bin/env bash
# 新视频 scaffold 脚本
# 用法:
#   bash scripts/new_video.sh <topic>
#
# 本脚本会：
#   1. 在当前工作目录创建 output/{topic}-{timestamp}/ 目录
#   2. 生成空的 audio/{topic}/ 和 assets/{topic}/ 子目录
#   3. 写入一个 scene-config.json 模板（AI 随后会填充内容）
#   4. 提示后续流程

set -e

if [ -z "$1" ]; then
  echo "用法: bash scripts/new_video.sh <topic-slug>"
  echo "  topic-slug: 小写字母+连字符，如 claude-tools、lightclawace"
  exit 1
fi

TOPIC="$1"
# 校验 topic 格式
if ! [[ "$TOPIC" =~ ^[a-z][a-z0-9-]*$ ]]; then
  echo "❌ topic 必须是小写字母+数字+连字符，以字母开头"
  echo "   示例: claude-tools, lightclawace, world-model"
  exit 1
fi

TIMESTAMP=$(date +%Y%m%d-%H%M)
CWD=$(pwd)
OUTPUT_DIR="${CWD}/output/${TOPIC}-${TIMESTAMP}"

echo "创建视频工作区: ${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}/audio/${TOPIC}"
mkdir -p "${OUTPUT_DIR}/assets/${TOPIC}"

# 生成 scene-config.json 空模板
cat > "${OUTPUT_DIR}/scene-config.json" <<EOF
{
  "meta": {
    "title": "[视频标题]",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "pad": 0.3,
    "cover": null,
    "coverDuration": 0.5,
    "ttsProvider": "tencent",
    "topic": "${TOPIC}"
  },
  "scenes": [
    {
      "id": "scene1",
      "title": "[场景标题]",
      "audio": "audio/${TOPIC}/scene1.wav",
      "duration": null,
      "subtitles": [
        { "text": "[第一句讲解]" }
      ],
      "elements": [
        { "type": "title", "content": "[占位]", "row": 0, "trigger": 0, "animation": "fade" }
      ]
    }
  ]
}
EOF

echo ""
echo "✅ 工作区已就绪"
echo ""
echo "目录结构:"
echo "  ${OUTPUT_DIR}/"
echo "  ├── scene-config.json  （已生成空模板）"
echo "  ├── audio/${TOPIC}/"
echo "  └── assets/${TOPIC}/"
echo ""
echo "下一步:"
echo "  1. 填充 scene-config.json 的 scenes（Step 2）"
echo "  2. 用户确认后运行 TTS（Step 3）:"
echo "     python3 \$SKILL_DIR/scripts/tts_tencent.py \\"
echo "       --text \"...\" --output ${OUTPUT_DIR}/audio/${TOPIC}/scene1.wav"
echo "  3. 回填 duration，生成 timeline.json（Step 4）"
echo "  4. 生成 SVG 素材到 ${OUTPUT_DIR}/assets/${TOPIC}/（Step 5）"
echo "  5. 复制到 remotion-project 并渲染（Step 6-7）"
echo ""
echo "TOPIC=${TOPIC}"
echo "OUTPUT_DIR=${OUTPUT_DIR}"
