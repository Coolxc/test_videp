#!/usr/bin/env bash
# whiteboard-video skill 一键环境初始化
# 用法（在 skill 根目录运行）：
#   bash scripts/setup.sh
#
# 本脚本会：
#   1. 检查 Python3, Node.js, ffmpeg 是否已安装
#   2. 安装 Python 依赖（腾讯云 TTS SDK + python-dotenv）
#   3. 安装 Remotion 项目 node_modules（npm install）
#   4. 创建必要的目录结构
#   5. 提示用户配置 .env（腾讯云密钥）

set -e

# 定位 skill 根目录（本脚本所在目录的父目录）
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTION_DIR="${SKILL_DIR}/remotion-project"

echo "======================================"
echo "whiteboard-video skill 初始化"
echo "Skill dir: ${SKILL_DIR}"
echo "======================================"
echo ""

# ---- Step 1: 依赖检查 ----
echo "[1/5] 检查系统依赖..."

missing_deps=()
command -v python3 >/dev/null 2>&1 || missing_deps+=("python3")
command -v node >/dev/null 2>&1 || missing_deps+=("node")
command -v npm >/dev/null 2>&1 || missing_deps+=("npm")
command -v ffprobe >/dev/null 2>&1 || missing_deps+=("ffmpeg (提供 ffprobe)")

if [ ${#missing_deps[@]} -ne 0 ]; then
  echo "❌ 缺少以下系统依赖，请先安装:"
  for dep in "${missing_deps[@]}"; do
    echo "  - ${dep}"
  done
  echo ""
  echo "安装建议:"
  echo "  macOS:   brew install python3 node ffmpeg"
  echo "  Ubuntu:  sudo apt-get install python3 python3-pip nodejs npm ffmpeg"
  echo "  CentOS:  sudo yum install python3 python3-pip nodejs ffmpeg"
  exit 1
fi

echo "  ✅ python3: $(python3 --version)"
echo "  ✅ node:    $(node --version)"
echo "  ✅ npm:     $(npm --version)"
echo "  ✅ ffprobe: $(ffprobe -version 2>&1 | head -1)"
echo ""

# ---- Step 2: Python 依赖 ----
echo "[2/5] 安装 Python 依赖..."
if [ -f "${SKILL_DIR}/requirements.txt" ]; then
  python3 -m pip install --user -r "${SKILL_DIR}/requirements.txt" 2>&1 | tail -5
  echo "  ✅ Python 依赖已安装"
else
  echo "  ⚠️  未找到 requirements.txt，跳过"
fi
echo ""

# ---- Step 3: Node 依赖 ----
echo "[3/5] 安装 Remotion 项目依赖（可能需要 2-5 分钟）..."
if [ -f "${REMOTION_DIR}/package.json" ]; then
  if [ -d "${REMOTION_DIR}/node_modules" ]; then
    echo "  node_modules 已存在，跳过（如需重装请先 rm -rf node_modules）"
  else
    (cd "${REMOTION_DIR}" && npm install 2>&1 | tail -10)
    echo "  ✅ node_modules 已安装"
  fi
else
  echo "  ❌ 未找到 ${REMOTION_DIR}/package.json"
  exit 1
fi
echo ""

# ---- Step 4: 目录结构 ----
echo "[4/5] 确保目录结构..."
mkdir -p "${REMOTION_DIR}/public/audio" "${REMOTION_DIR}/public/assets"
if [ ! -f "${REMOTION_DIR}/public/bgm.mp3" ]; then
  echo "  ⚠️  缺失 ${REMOTION_DIR}/public/bgm.mp3"
  echo "     这是背景音乐文件，视频必需。请从备份复制或另行获取"
else
  echo "  ✅ bgm.mp3 存在"
fi
echo ""

# ---- Step 5: .env 配置 ----
echo "[5/5] 检查 .env 配置..."
if [ -f "${SKILL_DIR}/.env" ]; then
  if grep -q "TENCENT_SECRET_ID" "${SKILL_DIR}/.env" 2>/dev/null; then
    echo "  ✅ .env 已配置"
  else
    echo "  ⚠️  .env 存在但未包含 TENCENT_SECRET_ID"
  fi
else
  cat > "${SKILL_DIR}/.env.example" <<EOF
# 腾讯云 TTS 密钥（可在腾讯云控制台 > 访问管理 > API密钥管理 获取）
# 复制本文件为 .env 并填入真实密钥：
#   cp .env.example .env
TENCENT_SECRET_ID=your-secret-id-here
TENCENT_SECRET_KEY=your-secret-key-here

# 可选：覆盖默认音色（默认 602005 专业梓欣）和速度（默认 1.1）
# TENCENT_TTS_VOICE_TYPE=602005
# TENCENT_TTS_SPEED=1.1
EOF
  echo "  ⚠️  未找到 .env，已生成模板 .env.example"
  echo "     请复制并填入密钥: cp ${SKILL_DIR}/.env.example ${SKILL_DIR}/.env"
fi
echo ""

echo "======================================"
echo "✅ 初始化完成"
echo "======================================"
echo ""
echo "下一步:"
echo "  - 如未配置 .env，先填入腾讯云密钥"
echo "  - 启动开发预览: cd ${REMOTION_DIR} && npx remotion studio"
echo "  - 可选：安装 vibevoice-tts skill 启用本地 TTS"
echo ""
