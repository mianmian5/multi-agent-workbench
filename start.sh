#!/bin/bash
# 🤖 Multi-Agent Workbench - 一键启动脚本
# 使用方式: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检测 Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python，请先安装 Python 3.9+"
    echo "   https://www.python.org/downloads/"
    exit 1
fi

# 检查 Python 版本
PY_VER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
if [ "$(echo "$PY_VER >= 3.9" | bc 2>/dev/null)" != "1" ]; then
    echo "⚠️  需要 Python 3.9+，当前版本: $PY_VER"
fi

# 检查依赖
echo "🔍 检查依赖..."
$PYTHON -c "import httpx, fastapi, uvicorn, openai, bs4" 2>/dev/null || {
    echo "📦 正在安装依赖..."
    $PYTHON -m pip install -r requirements.txt -q
}

# 检查 .env 文件
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ""
        echo "📝 已创建 .env 文件，请在启动后通过 Web 界面配置 API Key"
        echo ""
    fi
fi

echo ""
echo "🐱 Multi-Agent Workbench"
echo "========================"
echo ""
echo "🚀 启动 Web 服务..."
echo "   地址: http://127.0.0.1:8000"
echo "   按 Ctrl+C 停止"
echo ""
echo "   首次使用:"
echo "   1. 打开浏览器访问 http://127.0.0.1:8000"
echo "   2. 点击右上角 ⚙️ 配置 API Key 和模型"
echo "   3. 选择一个任务模板，开始协作！"
echo ""

# 启动
exec $PYTHON -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload
