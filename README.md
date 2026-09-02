# QQBot

基于 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) + Python 的 QQ 机器人，以 DeepSeek 为主对话模型，内置猫娘角色扮演人格，支持图片/视频识别、Markdown/公式渲染、表情包系统、向量长期记忆、用户档案、联网搜索等多模态能力。

## 功能一览

| 能力 | 说明 |
|------|------|
| 角色扮演 | 内置猫娘人格（主人/守护模式），傲娇恋人风格，支持表情包辅助情绪表达 |
| 长期记忆 | 群聊+私聊消息向量化存入 ChromaDB，按群/用户分 collection，LLM 自动检索相关历史 |
| 场景感知 | bot 自动区分群聊/私聊场合，system prompt 附带场景标识和当前时间 |
| 群聊发言人识别 | 群聊上下文统一使用 `QQ<号码>:` 标记真实发言人，避免多人消息被模型混淆 |
| Prompt 缓存优化 | 固定人设置于稳定 system 前缀，时间/档案/记忆等动态上下文按轮次追加，提高 DeepSeek 缓存命中率 |
| 自适应回复 | 根据群活跃度自动调整回复延迟和字数限制，人少快回、人多慢回 |
| 随机参与 | @bot/问句 100% 回复，闲聊 20% 概率随机搭话，像真人而不是 24h 客服 |
| 时段语调 | 根据早中晚深夜自动调整语气（清晨活泼、下午慵懒、深夜温柔） |
| 主动冒泡 | 群沉默超 6 小时后，20% 概率 bot 自己冒一句（凌晨静默） |
| 休眠指令 | `.sleep` 让 bot 暂停 N 分钟，`.wake` 提前唤醒 |
| 用户档案 | 每个 QQ 号独立档案（姓名/绰号/爱好/外貌/备注），私聊群聊共享，审核制写入，超管可直编 |
| 记忆迁移 | `migrate_memory.py` 将存量群聊记忆按用户拆分，支持增量更新 |
| 图片识别 | 消息含图片时自动调用 Qwen3-VL-Plus 识别 |
| 视频分析 | 调用 Gemini 2.0 Flash 分析视频内容 |
| 语音转文字 | 调用 Groq Whisper 转录语音消息 |
| Markdown 渲染 | AI 回复中的代码块、表格、数学公式自动渲染为图片 |
| 数学公式 | LaTeX 渲染，支持 `$…$` 行内和 `$$…$$` 块级公式 |
| P5 预告信 | 生成女神异闻录 5 风格预告信 |
| JMComic | 漫画下载并转 PDF |
| 风控 | 随机延迟、长消息分批发送，模拟人类行为 |

## 部署

### 前置要求

- **Python 3.11+**（建议用 venv）
- **Node.js 18+**（Markdown/公式渲染依赖 Puppeteer）
- **NapCatQQ**（OneBot v11 反向 WebSocket 模式）
- `duckduckgo_search`（联网搜索依赖，`pip install duckduckgo_search`）

### 1. 一键安装

```bash
# Linux
git clone https://github.com/eureka1460/QQbot-cat.git && cd QQbot-cat && bash install.sh

# Windows
git clone https://github.com/eureka1460/QQbot-cat.git && cd QQbot-cat && install.bat
```

安装脚本自动完成：Python 虚拟环境创建、pip 依赖安装、Node 依赖安装。

> 首次运行时 sentence-transformers 会自动下载向量模型（约 90 MB），之后离线可用。

### 2. 配置文件

复制 `config.example.json` 为 `config.json` 并填写：

```json
{
  "api_keys": {
    "deepseek":   "sk-...",
    "openrouter": "sk-or-v1-...",
    "qwen":       "sk-...",
    "gemini":     "AIza...",
    "groq":       "gsk_...",
    "openai":     "",
    "prodia":     ""
  },
  "model_settings": {
    "deepseek_base_url":    "https://api.deepseek.com",
    "deepseek_model":       "deepseek-v4-flash",
    "deepseek_temperature": 0.75
  },
  "bot_settings": {
    "super_users": [你的QQ号],
    "test_groups":  [启用Bot的群号],
    "host":      "127.0.0.1",
    "port":      "8080",
    "proxy_url": "http://127.0.0.1:7890"
  },
  "memory_settings": {
    "enabled":        true,
    "db_path":        "./memory_db",
    "window_size":    30,
    "search_results": 12
  }
}
```

**字段说明：**

| 字段 | 用途 | 是否必填 |
|------|------|----------|
| `deepseek` | 主对话模型 | 必填 |
| `qwen` | 图片识别（千问 DashScope） | 推荐填写 |
| `gemini` | 视频分析（google-genai） | 可选 |
| `groq` | 语音转文字（Whisper） | 可选 |
| `super_users` | 主人 QQ 号列表，拥有管理指令权限 | 必填 |
| `test_groups` | 允许 Bot 响应的群号列表 | 必填 |
| `proxy_url` | HTTP 代理（国内需配置，海外留空） | 按需填写 |
| `memory_settings.window_size` | 内存中保留的最近消息数 | 默认 30 |
| `memory_settings.search_results` | 每次从向量 DB 检索的历史条数 | 默认 12 |

### 3. 配置 NapCatQQ

1. 首次登录：扫码登录
2. 进入 NapCat「网络配置」，添加 **反向 WebSocket**：
   - URL：`ws://127.0.0.1:8080/onebot/v11/ws`

### 4. 服务器部署（Linux）

```bash
# 安装 npm（如未装）
sudo apt install nodejs npm -y

# 后台启动（一条命令）
source .venv/bin/activate && nohup python bot.py > bot.log 2>&1 &

# 查看日志
tail -f bot.log

# 停止
pkill -f bot.py
```

### 5. 本地启动（Windows）

```bat
run.bat
```

日志出现 `[NapCat] NapCat connected from path` 表示连接成功，`[Memory] Vector memory ready` 表示长期记忆就绪。对话请求完成后若 DeepSeek 返回 usage，会额外输出 `[DeepSeek Cache] hit=..., miss=..., rate=...` 用于观察 prompt 缓存命中率。

### 5. 表情包（可选）

在 `stickers/` 目录下放置图片并更新 `stickers/manifest.json`：

```json
{
  "shy":  "害羞、被夸奖、被摸头、慌乱时",
  "smug": "完成任务后的得意、自满时"
}
```

同一情绪可放多张（`shy0.jpg`、`shy1.gif`），发送时随机选择。

## 指令列表

群聊需要 @ Bot，私聊直接发送。★ 为超级用户专属。

| 指令 | 说明 | 权限 |
|------|------|------|
| `.help` | 显示帮助 | 所有人 |
| `.reset` | 重启 Bot 进程 | ★ |
| `.stop` | 停止 Bot | ★ |
| `.clean` | 清空当前群的向量记忆 | ★ |
| `.sleep <分钟>` | 休眠指定分钟数 | ★ |
| `.wake` | 提前唤醒 Bot | ★ |
| `.ban <QQ> [原因]` | 禁用用户 | ★ |
| `.unban <QQ>` | 解禁用户 | ★ |
| `.banlist` | 查看禁用列表 | ★ |
| `.profile` | 查看自己的档案 | 所有人 |
| `.profile <字段> <值>` | 提交档案修改申请 | 所有人 |
| `.profile <字段> <值> <QQ>` | 直接编辑别人档案 | ★ |
| `.profile delete [QQ]` | 删除档案 | 所有人/★ |
| `.profile pending` | 查看待审申请 | ★ |
| `.profile approve <QQ>` | 批准档案修改 | ★ |
| `.profile reject <QQ>` | 拒绝档案修改 | ★ |
| `.typ / .typst` | Typst 渲染 | 所有人 |
| `.md / .markdown <文本>` | 渲染 Markdown 为图片 | 所有人 |
| `.YGO <卡名>` | 查询游戏王卡片 | 所有人 |
| `.P5 <内容>` | P5 风格预告信 | 所有人 |
| `.jm <编号>` | 下载 JMComic 并转 PDF | 所有人 |

## 记忆系统

### 两层架构

| 层级 | 存储 | 内容 |
|------|------|------|
| 短期记忆 | 内存滑动窗口 + `memory_db/sessions/` 磁盘持久化 | 最近 N 条对话，带时间戳，重启后自动恢复 |
| 长期记忆 | ChromaDB（磁盘持久化） | 向量化消息，按 `group_{id}` / `user_{id}` 分 collection |

### Prompt 缓存策略

对话 prompt 按缓存友好的顺序组织：稳定角色卡作为第一段 system，短期历史只保存干净的用户消息与 bot 回复；当前时间、当前用户身份、用户档案、长期记忆检索结果、联网搜索结果和群聊活跃度等易变化信息，会作为本轮临时的 `[本轮运行时上下文]` 注入到 prompt 末尾。这样模型仍然能看到完整上下文，同时避免动态信息反复写入历史导致 token 膨胀。

群聊中每条消息统一使用 `QQ<号码>:` 标记真实发言人。该前缀会进入短期历史和批量群聊输入，帮助模型区分多人发言。

### 群聊 ↔ 私聊打通

群聊消息同时存入 `group_{group_id}` 和 `user_{user_id}` 两个 collection。同一用户在群里的发言，切到私聊后 bot 也能检索到。

### 存量迁移

```bash
python migrate_memory.py [memory_db_path]
```

将已有群聊记忆按发言人拆分到各用户的 collection，首次部署必跑一次。

## 用户档案

存储位置：`memory_db/profiles.json`

```
.profile                    查看档案
.profile name 张三           申请设置姓名
.profile nickname 三哥       申请设置绰号
.profile hobbies 打篮球      申请设置爱好
.profile appearance 戴眼镜   申请设置外貌
.profile extra 备注          申请设置备注
.profile delete              申请删除档案

# 超级用户审核
.profile pending             查看待审
.profile approve <QQ>        批准
.profile reject <QQ>         拒绝
```

## 项目结构

```
QQBot/
├── bot.py                      # WebSocket 服务器 & 消息收发
├── handlers.py                 # 消息路由 & 多模态预处理
├── agent_orchestrator.py       # Agent 编排（决策/对话/搜索/工具调用）
├── persona_engine.py           # 人格系统（稳定角色卡、运行时上下文、场景感知）
├── session_manager.py          # 会话管理（私聊/群聊上下文、TTL 控制）
├── api.py                      # DeepSeek API 封装（含重试与缓存命中日志）
├── config.py                   # 配置加载
├── command_handlers.py         # 命令解析与分发
├── tool_router.py              # 工具路由
├── migrate_memory.py           # 记忆迁移脚本（群→用户）
├── config.example.json         # 配置模板
├── requirements.txt            # Python 依赖
├── framework/                  # 事件路由框架
├── memory/
│   ├── vector_memory.py        # ChromaDB 向量记忆（后台加载模型）
│   ├── user_profile.py         # 用户档案（JSON 存储 + 审核流程）
│   ├── banlist.py              # 禁用用户管理
│   └── session_store.py        # 短期记忆磁盘持久化（重启恢复）
├── models/
│   ├── User.py                 # 私聊会话模型（运行时上下文 + 长期记忆）
│   └── Group.py                # 群聊会话模型（发言人前缀 + 长期记忆）
├── roles/
│   └── murasame_card.py        # 猫娘角色卡（人格提示词）
├── plugins/
│   ├── vision.py               # 图片识别
│   ├── gemini.py               # 视频分析
│   ├── markdown.py             # Markdown 渲染调度
│   ├── renderMarkdown.js       # Markdown 渲染（Node.js + Puppeteer + KaTeX）
│   ├── stickers.py             # 表情包系统
│   ├── jm2pdf.py               # JMComic 下载转 PDF
│   ├── option.yml              # jmcomic 配置文件
│   ├── typst_renderer.py       # Typst 渲染
│   ├── YGO_find_card.py        # 游戏王卡片查询
│   └── P5_card.py              # P5 预告信生成
└── stickers/
    ├── manifest.json            # 表情包情绪描述
    └── *.png                    # 表情包图片（不随仓库分发）
```

## 注意事项

- `config.json` 含 API Key，已加入 `.gitignore`
- 向量记忆数据库存于 `memory_db/`，已加入 `.gitignore`
- `roles/Murasame_*.py` 含自定义角色卡，已加入 `.gitignore`
- 国内部署建议配置代理访问 DeepSeek / Google API
- 新加坡/海外服务器不需要代理，DuckDuckGo 直连可用
- Puppeteer 首次运行会下载 Chromium

## License

MIT
