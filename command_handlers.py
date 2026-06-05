import asyncio
import json
import os
import shutil
import sys
import time
import traceback
from enum import Enum
from typing import Optional

from plugins import P5_card, YGO_find_card, jm2pdf, markdown, typst_renderer
from tool_router import Tool, ToolRouter, ToolScope


class CommandType(Enum):
    HELP = "help"
    RESET = "reset"
    STOP = "stop"
    CLEAN = "clean"
    SLEEP = "sleep"
    WAKE = "wake"
    CHAT_PROVIDER = "chat_provider"
    PROFILE = "profile"
    BAN = "ban"
    UNBAN = "unban"
    BANLIST = "banlist"
    TYPST = "typst"
    MARKDOWN = "markdown"
    YGO = "YGO"
    P5 = "P5"
    JM = "jm"


class MessageType(Enum):
    GROUP = "group"
    PRIVATE = "private"


class CommandHandler:
    """Command facade backed by ToolRouter."""

    def __init__(self, bot_interfaces, user_sessions, session_manager=None, profile_manager=None, ban_manager=None):
        self.bot_interfaces = bot_interfaces
        self.user_sessions = user_sessions
        self.session_manager = session_manager
        self.profile_manager = profile_manager
        self.ban_manager = ban_manager
        self.tool_router = ToolRouter()
        self._sleep_until: dict[int, float] = {}  # group_id → wake timestamp
        self.help_message = """========================
.help              查看此帮助
.reset             重启 Bot            ★
.stop              强制停止 Bot        ★
.clean             清空当前群记忆      ★
.sleep <分钟>      休眠指定分钟数      ★
.wake              提前唤醒 Bot        ★
.chat_provider     查看/切换聊天模型   ★
.ban <QQ> [原因]   禁用用户            ★
.unban <QQ>        解禁用户            ★
.banlist           查看禁用列表        ★
.profile           查看/设置个人档案
.typ / .typst      Typst 渲染
.md / .markdown    Markdown 渲染
.YGO               查询游戏王卡片
.P5                生成 P5 预告信
.jm <数字>         下载 JM 并生成 PDF
========================
★ 超级用户专属指令"""
        self._register_tools()

    def _register_tools(self):
        self.tool_router.register_many(
            [
                Tool(
                    name="help",
                    command_type=CommandType.HELP,
                    prefixes=[".help"],
                    group_handler=self._handle_help_group,
                    private_handler=self._handle_help_private,
                    description="显示插件信息",
                ),
                Tool(
                    name="reset",
                    command_type=CommandType.RESET,
                    prefixes=[".reset"],
                    group_handler=self._handle_reset_group,
                    private_handler=self._handle_reset_private,
                    description="重启 Bot",
                ),
                Tool(
                    name="stop",
                    command_type=CommandType.STOP,
                    prefixes=[".stop"],
                    group_handler=self._handle_stop_group,
                    private_handler=self._handle_stop_private,
                    description="强制停止 Bot",
                ),
                Tool(
                    name="clean",
                    command_type=CommandType.CLEAN,
                    prefixes=[".clean"],
                    group_handler=self._handle_clean_group,
                    private_handler=self._handle_clean_private,
                    description="清空当前群向量记忆",
                ),
                Tool(
                    name="chat_provider",
                    command_type=CommandType.CHAT_PROVIDER,
                    prefixes=[".chat_provider"],
                    group_handler=self._handle_chat_provider_group,
                    private_handler=self._handle_chat_provider_private,
                    description="查看/切换聊天模型 (deepseek/qwen)",
                ),
                Tool(
                    name="sleep",
                    command_type=CommandType.SLEEP,
                    prefixes=[".sleep"],
                    group_handler=self._handle_sleep_group,
                    private_handler=self._handle_sleep_private,
                    description="休眠指定分钟数",
                ),
                Tool(
                    name="wake",
                    command_type=CommandType.WAKE,
                    prefixes=[".wake"],
                    group_handler=self._handle_wake_group,
                    private_handler=self._handle_wake_private,
                    description="提前唤醒 Bot",
                ),
                Tool(
                    name="profile",
                    command_type=CommandType.PROFILE,
                    prefixes=[".profile"],
                    group_handler=self._handle_profile_group,
                    private_handler=self._handle_profile_private,
                    description="查看/设置个人档案",
                ),
                Tool(
                    name="ban",
                    command_type=CommandType.BAN,
                    prefixes=[".ban"],
                    group_handler=self._handle_ban_group,
                    private_handler=self._handle_ban_private,
                    description="禁用用户",
                ),
                Tool(
                    name="unban",
                    command_type=CommandType.UNBAN,
                    prefixes=[".unban"],
                    group_handler=self._handle_unban_group,
                    private_handler=self._handle_unban_private,
                    description="解禁用户",
                ),
                Tool(
                    name="banlist",
                    command_type=CommandType.BANLIST,
                    prefixes=[".banlist"],
                    group_handler=self._handle_banlist_group,
                    private_handler=self._handle_banlist_private,
                    description="查看禁用列表",
                ),
                Tool(
                    name="typst",
                    command_type=CommandType.TYPST,
                    prefixes=[".typst", ".typ"],
                    group_handler=self._handle_typst_group,
                    private_handler=self._handle_typst_private,
                    description="Typst 渲染",
                ),
                Tool(
                    name="markdown",
                    command_type=CommandType.MARKDOWN,
                    prefixes=[".markdown", ".md"],
                    group_handler=self._handle_markdown_group,
                    private_handler=self._handle_markdown_private,
                    description="Markdown 渲染",
                ),
                Tool(
                    name="ygo",
                    command_type=CommandType.YGO,
                    prefixes=[".YGO"],
                    group_handler=self._handle_ygo_group,
                    private_handler=self._handle_ygo_private,
                    description="查询游戏王卡片",
                ),
                Tool(
                    name="p5",
                    command_type=CommandType.P5,
                    prefixes=[".P5", ".p5"],
                    group_handler=self._handle_p5_group,
                    private_handler=self._handle_p5_private,
                    description="生成 P5 预告信",
                ),
                Tool(
                    name="jm",
                    command_type=CommandType.JM,
                    prefixes=[".jm", ".JM"],
                    group_handler=self._handle_jm_group,
                    private_handler=self._handle_jm_private,
                    description="下载 JM 并生成 PDF",
                ),
            ]
        )

    def get_command_type(self, message_content: str) -> Optional[CommandType]:
        return self.tool_router.match_command_type(message_content)

    def extract_command_content(self, message_content: str, command_type: CommandType) -> str:
        return self.tool_router.extract_content(message_content, command_type)

    async def handle_command(
        self,
        ws,
        message_type: MessageType,
        command_type: CommandType,
        message_content: str,
        **kwargs,
    ) -> bool:
        try:
            scope = ToolScope(message_type.value)
            return await self.tool_router.handle(
                scope,
                command_type,
                ws,
                message_content,
                **kwargs,
            )
        except Exception as exc:
            print(f"[Command] Failed to handle {command_type}: {exc}")
            traceback.print_exc()
            return False

    async def _send_group_text(self, ws, group_id: int, text: str):
        await self.bot_interfaces["send_group_message"](
            ws,
            group_id,
            await self.bot_interfaces["decode_CQ_to_message"](text),
        )

    async def _send_private_text(self, ws, user_id: int, text: str):
        await self.bot_interfaces["send_private_message"](
            ws,
            user_id,
            await self.bot_interfaces["decode_CQ_to_message"](text),
        )

    async def _handle_help_group(self, ws, message_content: str, group_id: int, **kwargs):
        await self._send_group_text(ws, group_id, self.help_message)

    async def _handle_help_private(self, ws, message_content: str, user_id: int, **kwargs):
        await self._send_private_text(ws, user_id, self.help_message)

    async def _handle_reset_group(
        self,
        ws,
        message_content: str,
        group_id: int,
        user_id: int,
        **kwargs,
    ):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可重启 Bot")
            return
        await self._send_group_text(ws, group_id, "Bot 重启中，稍后见~")
        await self._trigger_restart()

    async def _handle_reset_private(self, ws, message_content: str, user_id: int, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_private_text(ws, user_id, "权限不足，仅超级用户可重启 Bot")
            return
        await self._send_private_text(ws, user_id, "Bot 重启中，稍后见~")
        await self._trigger_restart()

    async def _trigger_restart(self):
        await asyncio.sleep(0.8)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    async def _handle_stop_group(
        self,
        ws,
        message_content: str,
        group_id: int,
        user_id: int,
        **kwargs,
    ):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可停止 Bot")
            return
        await self._send_group_text(ws, group_id, "Bot 已停止，再见~")
        await self._do_stop()

    async def _handle_stop_private(self, ws, message_content: str, user_id: int, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_private_text(ws, user_id, "权限不足，仅超级用户可停止 Bot")
            return
        await self._send_private_text(ws, user_id, "Bot 已停止，再见~")
        await self._do_stop()

    async def _do_stop(self):
        await asyncio.sleep(0.8)
        os._exit(0)

    async def _handle_clean_group(
        self,
        ws,
        message_content: str,
        group_id: int,
        user_id: int,
        **kwargs,
    ):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可清空记忆")
            return
        memory = getattr(self.session_manager, "memory", None) if self.session_manager else None
        if not memory:
            await self._send_group_text(ws, group_id, "向量记忆未启用")
            return
        if memory.clear(group_id):
            await self._send_group_text(ws, group_id, "已清空本群的向量记忆")
        else:
            await self._send_group_text(ws, group_id, "清空失败，记忆模块尚未就绪")

    async def _handle_clean_private(self, ws, message_content: str, user_id: int, **kwargs):
        await self._send_private_text(ws, user_id, "私聊暂无向量记忆可清理")

    # ------------------------------------------------------------------
    # Profile command handlers
    # ------------------------------------------------------------------
    _PROFILE_FIELDS = ["name", "nickname", "hobbies", "appearance", "extra"]
    _PROFILE_HELP = (
        ".profile                     查看你的档案\n"
        ".profile <字段> <值>          设置字段 (需审核)\n"
        ".profile delete              申请删除档案\n"
        "--- 以下仅超级用户可用 ---\n"
        ".profile <字段> <值> <QQ号>   直接编辑别人档案\n"
        ".profile pending             查看待审申请\n"
        ".profile approve <QQ号>      批准申请\n"
        ".profile reject <QQ号>        拒绝申请"
    )

    async def _handle_profile_group(self, ws, message_content, group_id, user_id, **kwargs):
        await self._handle_profile(ws, user_id, message_content, is_group=True, group_id=group_id)

    async def _handle_profile_private(self, ws, message_content, user_id, **kwargs):
        await self._handle_profile(ws, user_id, message_content, is_group=False)

    async def _handle_profile(self, ws, user_id, message_content, is_group, group_id=None):
        if not self.profile_manager:
            await self._reply(ws, user_id, group_id, is_group, "个人档案功能未启用")
            return

        is_super = self.bot_interfaces["test_if_super_user"](user_id)
        args = message_content.strip().split()

        # ---- .profile (no args) ----
        if len(args) <= 1:
            await self._profile_show(ws, user_id, group_id, is_group)
            return

        match args[1]:
            # ---- Super-user admin commands ----
            case "pending":
                if not is_super:
                    await self._reply(ws, user_id, group_id, is_group, "权限不足，仅超级用户可查看待审申请")
                    return
                await self._profile_pending(ws, user_id, group_id, is_group)

            case "approve":
                if not is_super:
                    await self._reply(ws, user_id, group_id, is_group, "权限不足")
                    return
                target = args[2] if len(args) > 2 else ""
                if not target or not target.isdigit():
                    await self._reply(ws, user_id, group_id, is_group, "用法: .profile approve <QQ号>")
                    return
                await self._profile_approve(ws, user_id, group_id, is_group, int(target))

            case "reject":
                if not is_super:
                    await self._reply(ws, user_id, group_id, is_group, "权限不足")
                    return
                target = args[2] if len(args) > 2 else ""
                if not target or not target.isdigit():
                    await self._reply(ws, user_id, group_id, is_group, "用法: .profile reject <QQ号>")
                    return
                await self._profile_reject(ws, user_id, group_id, is_group, int(target))

            # ---- Delete ----
            case "delete":
                # Super user can delete others: .profile delete 123456789
                target_id = user_id
                if is_super and len(args) > 2 and args[2].isdigit():
                    target_id = int(args[2])
                if is_super:
                    ok = self.profile_manager.delete(target_id)
                    msg = f"已删除 QQ{target_id} 的档案" if ok else f"QQ{target_id} 没有档案"
                    if target_id != user_id:
                        msg += f"\n（由 QQ{user_id} 设定）"
                else:
                    self.profile_manager.submit(user_id, {"_delete": "1"})
                    msg = "删除申请已提交，等待超级用户审核"
                await self._reply(ws, user_id, group_id, is_group, msg)

            # ---- Help ----
            case "help":
                await self._reply(ws, user_id, group_id, is_group, self._PROFILE_HELP)

            # ---- Field set ----
            case field if field in self._PROFILE_FIELDS:
                value = " ".join(args[2:]) if len(args) > 2 else ""
                if not value:
                    await self._reply(ws, user_id, group_id, is_group,
                                      f"用法: .profile {field} <值>\n例如: .profile {field} 打篮球")
                    return
                # Super user can edit others: .profile name 张三 123456789
                target_id = user_id
                if is_super:
                    last_arg = args[-1]
                    if last_arg.isdigit() and len(last_arg) >= 5:
                        target_id = int(last_arg)
                        value = " ".join(args[2:-1])
                if is_super:
                    self.profile_manager.set(target_id, field, value)
                    msg = f"已更新 QQ{target_id} 的 {field}: {value}"
                    if target_id != user_id:
                        msg += f"\n（由 QQ{user_id} 设定）"
                else:
                    self.profile_manager.submit(user_id, {field: value})
                    msg = f"「{field}: {value}」已提交审核，等待超级用户批准"
                await self._reply(ws, user_id, group_id, is_group, msg)

            case _:
                await self._reply(ws, user_id, group_id, is_group,
                                  f"未知操作 \"{args[1]}\"。\n{self._PROFILE_HELP}")

    # -- helpers --

    async def _profile_show(self, ws, user_id, group_id, is_group):
        profile = self.profile_manager.get(user_id)
        if not profile:
            await self._reply(ws, user_id, group_id, is_group,
                              "你还没有个人档案。\n用 .profile <字段> <值> 来申请设置，例如:\n.profile name 张三")
            return
        lines = ["你的档案:"]
        for field in self._PROFILE_FIELDS:
            val = profile.get(field, "")
            if val:
                lines.append(f"  {field}: {val}")
        await self._reply(ws, user_id, group_id, is_group, "\n".join(lines))

    async def _profile_pending(self, ws, user_id, group_id, is_group):
        items = self.profile_manager.list_pending()
        if not items:
            await self._reply(ws, user_id, group_id, is_group, "没有待审核的申请")
            return
        lines = [f"待审核申请 ({len(items)} 条):"]
        for item in items:
            uid = item["user_id"]
            fields = []
            for k, v in item.items():
                if k in ("user_id", "submitted_at", "submitted_by"):
                    continue
                if k == "_delete":
                    fields.append("[删除档案]")
                else:
                    fields.append(f"{k}={v}")
            lines.append(f"  QQ{uid}: {', '.join(fields)}")
        await self._reply(ws, user_id, group_id, is_group, "\n".join(lines))

    async def _profile_approve(self, ws, user_id, group_id, is_group, target_id):
        result = self.profile_manager.approve(target_id)
        if result is None:
            await self._reply(ws, user_id, group_id, is_group, f"QQ{target_id} 没有待审核的申请")
            return
        if not result:
            # Delete was approved
            await self._reply(ws, user_id, group_id, is_group, f"已批准删除 QQ{target_id} 的档案")
        else:
            fields = [f"{f}={v}" for f, v in result.items() if f in self._PROFILE_FIELDS]
            await self._reply(ws, user_id, group_id, is_group,
                              f"已批准 QQ{target_id} 的申请: {', '.join(fields)}")

    async def _profile_reject(self, ws, user_id, group_id, is_group, target_id):
        ok = self.profile_manager.reject(target_id)
        if not ok:
            await self._reply(ws, user_id, group_id, is_group, f"QQ{target_id} 没有待审核的申请")
        else:
            await self._reply(ws, user_id, group_id, is_group, f"已拒绝 QQ{target_id} 的申请")

    async def _reply(self, ws, user_id, group_id, is_group, text):
        if is_group:
            cq_text = f"[CQ:at,qq={user_id}]\n{text}"
            await self._send_group_text(ws, group_id, cq_text)
        else:
            await self._send_private_text(ws, user_id, text)

    # ------------------------------------------------------------------
    # Ban / Unban / Banlist handlers (super-user only)
    # ------------------------------------------------------------------

    async def _handle_ban_group(self, ws, message_content, group_id, user_id, **kwargs):
        await self._handle_ban(ws, user_id, message_content, is_group=True, group_id=group_id)

    async def _handle_ban_private(self, ws, message_content, user_id, **kwargs):
        await self._handle_ban(ws, user_id, message_content, is_group=False)

    async def _handle_ban(self, ws, operator_id, message_content, is_group, group_id=None):
        if not self.ban_manager:
            await self._reply(ws, operator_id, group_id, is_group, "禁用管理功能未启用")
            return
        if not self.bot_interfaces["test_if_super_user"](operator_id):
            await self._reply(ws, operator_id, group_id, is_group, "权限不足，仅超级用户可禁用用户")
            return

        args = message_content.strip().split()
        if len(args) < 2 or not args[1].isdigit():
            await self._reply(ws, operator_id, group_id, is_group, "用法: .ban <QQ号> [原因]")
            return

        target_id = int(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else ""

        if self.ban_manager.is_banned(target_id):
            await self._reply(ws, operator_id, group_id, is_group, f"QQ{target_id} 已在禁用列表中")
            return

        self.ban_manager.ban(target_id, reason=reason, banned_by=str(operator_id))
        msg = f"已禁用 QQ{target_id}"
        if reason:
            msg += f"，原因: {reason}"
        await self._reply(ws, operator_id, group_id, is_group, msg)

    async def _handle_unban_group(self, ws, message_content, group_id, user_id, **kwargs):
        await self._handle_unban(ws, user_id, message_content, is_group=True, group_id=group_id)

    async def _handle_unban_private(self, ws, message_content, user_id, **kwargs):
        await self._handle_unban(ws, user_id, message_content, is_group=False)

    async def _handle_unban(self, ws, operator_id, message_content, is_group, group_id=None):
        if not self.ban_manager:
            await self._reply(ws, operator_id, group_id, is_group, "禁用管理功能未启用")
            return
        if not self.bot_interfaces["test_if_super_user"](operator_id):
            await self._reply(ws, operator_id, group_id, is_group, "权限不足，仅超级用户可解禁用户")
            return

        args = message_content.strip().split()
        if len(args) < 2 or not args[1].isdigit():
            await self._reply(ws, operator_id, group_id, is_group, "用法: .unban <QQ号>")
            return

        target_id = int(args[1])
        ok = self.ban_manager.unban(target_id)
        if ok:
            await self._reply(ws, operator_id, group_id, is_group, f"已解禁 QQ{target_id}")
        else:
            await self._reply(ws, operator_id, group_id, is_group, f"QQ{target_id} 不在禁用列表中")

    def is_sleeping(self, group_id: int) -> bool:
        until = self._sleep_until.get(int(group_id))
        if until and time.time() < until:
            return True
        return False

    # ---- Sleep / Wake ----
    async def _handle_sleep_group(self, ws, message_content, group_id, user_id, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可使用")
            return
        args = message_content.strip().split()
        if len(args) < 2 or not args[1].isdigit():
            await self._send_group_text(ws, group_id, "用法: .sleep <分钟数>")
            return
        minutes = int(args[1])
        wake_at = time.time() + minutes * 60
        self._sleep_until[group_id] = wake_at
        await self._send_group_text(ws, group_id, f"好的，我去睡 {minutes} 分钟~ 到时间自动醒。\n提前唤醒用 .wake")

    async def _handle_sleep_private(self, ws, message_content, user_id, **kwargs):
        await self._send_private_text(ws, user_id, ".sleep 指令仅在群聊可用")

    async def _handle_wake_group(self, ws, message_content, group_id, user_id, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可使用")
            return
        if group_id in self._sleep_until:
            del self._sleep_until[group_id]
            await self._send_group_text(ws, group_id, "醒啦！")
        else:
            await self._send_group_text(ws, group_id, "我没在睡觉呀")

    async def _handle_wake_private(self, ws, message_content, user_id, **kwargs):
        await self._send_private_text(ws, user_id, ".wake 指令仅在群聊可用")

    # ---- Chat Provider ----
    async def _handle_chat_provider_group(self, ws, message_content, group_id, user_id, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_group_text(ws, group_id, "权限不足，仅超级用户可使用")
            return
        await self._handle_chat_provider(ws, message_content, group_id=group_id, is_group=True, user_id=user_id)

    async def _handle_chat_provider_private(self, ws, message_content, user_id, **kwargs):
        if not self.bot_interfaces["test_if_super_user"](user_id):
            await self._send_private_text(ws, user_id, "权限不足，仅超级用户可使用")
            return
        await self._handle_chat_provider(ws, message_content, is_group=False, user_id=user_id)

    async def _handle_chat_provider(self, ws, message_content, is_group, user_id, group_id=None):
        import config as cfg
        args = message_content.strip().split()
        if len(args) < 2:
            await self._reply(ws, user_id, group_id, is_group,
                              f"当前模型: {cfg.CHAT_PROVIDER}\n切换: .chat_provider deepseek 或 .chat_provider qwen")
            return
        choice = args[1].lower()
        if choice not in ("deepseek", "qwen"):
            await self._reply(ws, user_id, group_id, is_group, "可选: deepseek 或 qwen")
            return
        # Write back to config.json
        cfg.CHAT_PROVIDER = choice
        try:
            with open(cfg.config_path, "r", encoding="utf-8-sig") as f:
                conf = json.loads(f.read())
            conf.setdefault("model_settings", {})["chat_provider"] = choice
            with open(cfg.config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f, ensure_ascii=False, indent=2)
            await self._reply(ws, user_id, group_id, is_group, f"已切换到 {choice}，重启后生效")
        except Exception as exc:
            cfg.CHAT_PROVIDER = cfg.config_data.get("model_settings", {}).get("chat_provider", "deepseek")
            await self._reply(ws, user_id, group_id, is_group, f"保存失败: {exc}")

    async def _handle_banlist_group(self, ws, message_content, group_id, user_id, **kwargs):
        await self._handle_banlist(ws, user_id, is_group=True, group_id=group_id)

    async def _handle_banlist_private(self, ws, message_content, user_id, **kwargs):
        await self._handle_banlist(ws, user_id, is_group=False)

    async def _handle_banlist(self, ws, operator_id, is_group, group_id=None):
        if not self.ban_manager:
            await self._reply(ws, operator_id, group_id, is_group, "禁用管理功能未启用")
            return
        if not self.bot_interfaces["test_if_super_user"](operator_id):
            await self._reply(ws, operator_id, group_id, is_group, "权限不足，仅超级用户可查看禁用列表")
            return

        items = self.ban_manager.list_all()
        if not items:
            await self._reply(ws, operator_id, group_id, is_group, "禁用列表为空")
            return

        lines = [f"禁用列表 ({len(items)} 人):"]
        for item in items:
            uid = item["user_id"]
            reason = item.get("reason", "")
            line = f"  QQ{uid}"
            if reason:
                line += f" ({reason})"
            lines.append(line)
        await self._reply(ws, operator_id, group_id, is_group, "\n".join(lines))

    async def _handle_typst_group(self, ws, message_content: str, group_id: int, **kwargs):
        image_cq_code = await typst_renderer.handle_typst_message(message_content)
        await self._send_group_text(ws, group_id, image_cq_code)

    async def _handle_typst_private(self, ws, message_content: str, user_id: int, **kwargs):
        image_cq_code = await typst_renderer.handle_typst_message(message_content)
        await self._send_private_text(ws, user_id, image_cq_code)

    async def _handle_markdown_group(self, ws, message_content: str, group_id: int, **kwargs):
        image_cq_code = await markdown.handle_markdown_message(message_content)
        await self._send_group_text(ws, group_id, image_cq_code)

    async def _handle_markdown_private(self, ws, message_content: str, user_id: int, **kwargs):
        image_cq_code = await markdown.handle_markdown_message(message_content)
        await self._send_private_text(ws, user_id, image_cq_code)

    async def _handle_ygo_group(self, ws, message_content: str, group_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.YGO)
        card_info = await YGO_find_card.get_card_info(command_content)
        await self.bot_interfaces["send_group_message"](
            ws,
            group_id,
            card_info or "抱歉，未找到相关卡片信息。",
        )

    async def _handle_ygo_private(self, ws, message_content: str, user_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.YGO)
        card_info = await YGO_find_card.get_card_info(command_content)
        await self.bot_interfaces["send_private_message"](
            ws,
            user_id,
            card_info or "抱歉，未找到相关卡片信息。",
        )

    async def _handle_p5_group(self, ws, message_content: str, group_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.P5)
        card_image = await P5_card.get_card(command_content)
        await self.bot_interfaces["send_group_message"](
            ws,
            group_id,
            card_image or "预告信生成失败",
        )

    async def _handle_p5_private(self, ws, message_content: str, user_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.P5)
        card_image = await P5_card.get_card(command_content)
        await self.bot_interfaces["send_private_message"](
            ws,
            user_id,
            card_image or "预告信生成失败",
        )

    async def _handle_jm_group(self, ws, message_content: str, group_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.JM)

        if not command_content or not command_content.strip():
            await self._send_group_text(ws, group_id, "用法: .jm <数字编号>")
            return

        await self._send_group_text(ws, group_id, f"好好好，{command_content} 嘛，这就去给你搬过来~")

        jm_pdf = await jm2pdf.get_pdf(command_content)
        if jm_pdf == 0:
            await self._send_group_text(ws, group_id, f"翻了个遍没找到 {command_content}，编号没搞错吧？还是被和谐了？")
            return

        try:
            abs_path = os.path.abspath(jm_pdf)
            await self.bot_interfaces["upload_group_file"](
                ws,
                group_id,
                abs_path,
                f"{command_content}.pdf",
                "/",
            )
            await self._send_group_text(ws, group_id, "Get Da★Ze☆~ 少🦌一点哦，已发至群文件，好好欣赏哦")
        finally:
            self._cleanup_jm_tmp(jm_pdf, command_content)

    async def _handle_jm_private(self, ws, message_content: str, user_id: int, **kwargs):
        command_content = self.extract_command_content(message_content, CommandType.JM)

        if not command_content or not command_content.strip():
            await self._send_private_text(ws, user_id, "用法: .jm <数字编号>")
            return

        await self._send_private_text(ws, user_id, f"好好好，{command_content} 嘛，这就去给你搬过来~")

        jm_pdf = await jm2pdf.get_pdf(command_content)
        if jm_pdf == 0:
            await self._send_private_text(ws, user_id, f"翻了个遍没找到 {command_content}，编号没搞错吧？还是被和谐了？")
            return

        try:
            abs_path = os.path.abspath(jm_pdf)
            await self.bot_interfaces["upload_private_file"](
                ws,
                user_id,
                abs_path,
                f"{command_content}.pdf",
            )
            await self._send_private_text(ws, user_id, "Get Da★Ze☆~ 少🦌一点哦，好好欣赏哦")
        finally:
            self._cleanup_jm_tmp(jm_pdf, command_content)

    def _cleanup_jm_tmp(self, jm_pdf: str, command_content: str):
        if jm_pdf and os.path.exists(jm_pdf):
            os.remove(jm_pdf)

        tmp_dir = os.path.join("Bot", "tmp", command_content)
        if os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)