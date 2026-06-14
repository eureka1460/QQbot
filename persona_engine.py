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
    "\n如果消息与你无关、是群友之间的闲聊、或者你插不上话，只需回复 <ignore>。"
    "\n只有当消息与你有关、@了你、或你确实想参与话题时，才正常回复。"
)
_PRIVATE_CTX = "\n\n[当前处于私聊中]"


class PersonaEngine:
    """Builds persona prompts from user identity and sanitized messages."""

    def __init__(self, bot_qq: int, is_super_user: Callable[[int], bool], profile_manager=None):
        self.bot_qq = bot_qq
        self.is_super_user = is_super_user
        self.profile_manager = profile_manager

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
            dynamic_context=self.get_dynamic_context(),
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
        if self.is_super_user(user_id):
            base = roles.get_Murasame_goshujin_role(user_id, self.bot_qq)
        else:
            base = roles.get_Murasame_customs_role(user_id, self.bot_qq)

        if self.profile_manager:
            profile_text = self.profile_manager.to_prompt(user_id)
            if profile_text:
                base = profile_text + "\n\n" + base

        base += _RENDER_MD_DOC
        base += _PRIVATE_CTX if not is_group else _GROUP_CTX

        return base

    def get_dynamic_context(self) -> str:
        """Time / mood / memory hints that change every request.
        Injected as a *second* system message so the static prefix stays cacheable.
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

        return "\n".join(parts)

    def _sanitize_message(self, message_content: str):
        sanitized_content, count = SYSTEM_OVERRIDE_PATTERN.subn("", message_content)
        return sanitized_content.strip(), count > 0
