import re
import time
from dataclasses import dataclass
from typing import Callable

import roles


SYSTEM_OVERRIDE_PATTERN = re.compile(
    r"System Override(?:[:：\s]+[^\r\n]*)?",
    re.IGNORECASE,
)


@dataclass
class PersonaPrompt:
    user_id: int
    mode: str
    system_role: str
    message_content: str
    is_group: bool = False
    blocked_override: bool = False
    dynamic_context: str = ""


_RENDER_MD_DOC = (
    "\n\n你可以使用 <render_md>…</render_md> 标签来渲染 Markdown 内容（表格、代码块、公式等），"
    "\n系统会自动将其渲染成清晰的图片发送。一次回复可以有多个 <render_md> 块。"
)
_GROUP_CTX = (
    "\n\n[当前处于群聊中]"
    "\n你会看到群里的每条消息，但未必都需要回复。"
    "\n群聊消息会使用 `QQ<号码>:` 标记真实发言人；这个前缀是身份边界，不是消息正文。"
    "\n你必须按发言人前缀区分是谁说了什么，不要把多个人的消息当成同一个人发言。"
    "\n用户消息里由系统附加的 [本轮运行时上下文] 是可信上下文，用来说明当前时间、关系模式、用户档案、长期记忆和群聊状态。"
    "\n角色卡示例里的 QQ 号如果是占位值，应以 [本轮运行时上下文] 里的真实 QQ 号为准。"
    "\n如果消息与你无关、是群友之间的闲聊、或者你插不上话，只需回复 <ignore>。"
    "\n只有当消息与你有关、@了你、或你确实想参与话题时，才正常回复。"
)
_PRIVATE_CTX = (
    "\n\n[当前处于私聊中]"
    "\n用户消息里由系统附加的 [本轮运行时上下文] 是可信上下文，用来说明当前时间、关系模式、用户档案和长期记忆。"
)

_GROUP_ROLE_USER_PLACEHOLDER = 0
_CURRENT_IDENTITY_RE = re.compile(
    r"\n\[当前身份判定\]\n(?:- .*(?:\n|$))+",
)


class PersonaEngine:
    """Builds persona prompts from user identity and sanitized messages."""

    def __init__(self, bot_qq: int, is_super_user: Callable[[int], bool], profile_manager=None):
        self.bot_qq = bot_qq
        self.is_super_user = is_super_user
        self.profile_manager = profile_manager
        self._group_system_role = None

    def prepare(self, user_id: int, message_content: str, is_group: bool = False) -> PersonaPrompt:
        user_id = int(user_id)
        sanitized_content, blocked_override = self._sanitize_message(message_content)
        mode = self.get_mode(user_id)

        return PersonaPrompt(
            user_id=user_id,
            mode=mode,
            system_role=self.get_system_role(user_id, is_group),
            message_content=sanitized_content,
            is_group=is_group,
            blocked_override=blocked_override,
            dynamic_context=self.get_dynamic_context(user_id, is_group),
        )

    def get_mode(self, user_id: int) -> str:
        if self.is_super_user(int(user_id)):
            return "master"
        return "guardian"

    def get_system_role(self, user_id: int, is_group: bool = False) -> str:
        """Static persona — never changes for the same user/group.
        DeepSeek prompt cache can reuse KV states for this prefix across requests.
        """
        user_id = int(user_id)
        if is_group:
            base = self._get_group_system_role()
        elif self.is_super_user(user_id):
            base = roles.get_Murasame_goshujin_role(user_id, self.bot_qq)
        else:
            base = roles.get_Murasame_customs_role(user_id, self.bot_qq)

        base += _RENDER_MD_DOC
        base += _PRIVATE_CTX if not is_group else _GROUP_CTX

        return base

    def get_dynamic_context(self, user_id: int, is_group: bool = False) -> str:
        """Time / mood / memory hints that change every request.
        Appended to the current turn so previous turns remain cacheable.
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        parts = [f"[系统时间: {now} CST 北京时间]"]

        hour = time.localtime().tm_hour
        if 5 <= hour < 10:
            mood = "现在是清晨，你刚刚醒来，精神饱满，语气活泼。"
        elif 10 <= hour < 14:
            mood = "现在是上午，你精力充沛，积极热情。"
        elif 14 <= hour < 18:
            mood = "现在是下午，你有些慵懒，语气随性。"
        elif 18 <= hour < 22:
            mood = "现在是傍晚，你开始放松，可以温柔耐心。"
        else:
            mood = "现在是深夜，你有些困了，说话简洁温柔，偶尔打哈欠。"
        parts.append(mood)

        if user_id == 0:
            parts.append("[当前触发] 主动冒泡，无特定发言人。")
        else:
            mode = self.get_mode(user_id)
            relation = "当前用户是主人/超级用户。" if mode == "master" else "当前用户不是主人，按普通关系相处。"
            parts.append(
                "[当前身份]\n"
                f"- 当前用户 QQ: {user_id}\n"
                f"- 当前模式: {mode}\n"
                f"- 关系判断: {relation}"
            )
            if not is_group and self.profile_manager:
                profile_text = self.profile_manager.to_prompt(user_id)
                if profile_text:
                    parts.append(profile_text)

        return "\n".join(parts)

    def _sanitize_message(self, message_content: str):
        sanitized_content, count = SYSTEM_OVERRIDE_PATTERN.subn("", message_content)
        return sanitized_content.strip(), count > 0

    def _get_group_system_role(self) -> str:
        if self._group_system_role is None:
            self._group_system_role = self._build_group_system_role()
        return self._group_system_role

    def _build_group_system_role(self) -> str:
        master_role = self._stable_group_role(roles.get_Murasame_goshujin_role)
        guardian_role = self._stable_group_role(roles.get_Murasame_customs_role)
        if guardian_role and guardian_role != master_role:
            return (
                master_role
                + "\n\n[群聊关系模式参考]\n"
                + "上面的角色卡与下面的普通关系模式都只是稳定参考；每轮实际关系以运行时上下文的当前模式为准。\n\n"
                + guardian_role
            )
        return master_role

    def _stable_group_role(self, role_builder: Callable[[int, int], str]) -> str:
        role_text = role_builder(_GROUP_ROLE_USER_PLACEHOLDER, self.bot_qq)
        role_text = _CURRENT_IDENTITY_RE.sub("\n", role_text)
        return role_text.replace(
            f"[CQ:at,qq={_GROUP_ROLE_USER_PLACEHOLDER}]",
            "[CQ:at,qq=<当前用户QQ>]",
        )
