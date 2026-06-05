#!/bin/bash
set -e

echo "============================================"
echo "  QQbot-cat 一键安装 (Linux)"
echo "============================================"

# Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# Python 依赖
pip install -r requirements.txt

# Node 依赖 (Markdown 渲染)
npm install markdown-it markdown-it-texmath katex puppeteer

echo ""
echo "=== 安装完成 ==="
echo ""
echo "接下来:"
echo "  1. cp config.example.json config.json 并填写 API key"
echo "  2. 放置角色卡到 roles/"
echo "  3. (可选) 放置表情包到 stickers/"
echo "  4. (可选) 上传 memory_db/ 记忆数据"
echo "  5. python bot.py 启动"
