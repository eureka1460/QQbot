@echo off
chcp 65001 >nul
echo ============================================
echo   QQbot-cat 一键安装 (Windows)
echo ============================================

:: Python 虚拟环境
python -m venv .venv
call .venv\Scripts\activate.bat

:: Python 依赖
pip install -r requirements.txt

:: Node 依赖 (Markdown 渲染)
npm install markdown-it markdown-it-texmath katex puppeteer

echo.
echo === 安装完成 ===
echo.
echo 接下来:
echo   1. 复制 config.example.json 为 config.json 并填写 API key
echo   2. 放置角色卡到 roles\
echo   3. (可选) 放置表情包到 stickers\
echo   4. (可选) 上传 memory_db 记忆数据
echo   5. run.bat 启动
pause
