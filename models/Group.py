from typing import Optional
import time
from api import *


class Group:
    _TRIM_SLACK_MIN = 4
    _TRIM_SLACK_MAX = 20

    def __init__(self, group_id, bot_qq, memory=None, window_size: int = 30, save_callback=None):
        self.group_id = group_id
        self.users = {}
        self.chat_history = []
        self.bot_qq = bot_qq
        self.memory = memory
        self._window_size = window_size
        self._save_callback = save_callback

    def add_message(self, role, message_content, user_id=None, trim=True):
        if role == "user" and user_id:
            message_content = f"QQ{user_id}: {message_content}"
        self.chat_history.append({
            "role": role,
            "content": message_content,
            "timestamp": int(time.time() * 1000),
        })
        if trim:
            self._trim_chat_history()

        if self._save_callback:
            self._save_callback(self.chat_history)

    def get_chat_history(self):
        return self.chat_history

    async def handle_message(self, user_id: Optional[int], message_content, system_role, store_user=True, dynamic_context=""):
        if self.memory and store_user:
            self.memory.store(self.group_id, user_id, message_content, "user")

        # Build dynamic context: time/mood + long-term memory
        dynamic_with_memory = dynamic_context
        if self.memory:
            relevant = self.memory.search(self.group_id, message_content)
            if relevant:
                dynamic_with_memory += (
                    "\n\n[来自长期记忆的相关历史对话，供参考]\n"
                    + relevant
                    + "\n[历史记忆结束]"
                )

        # Build messages: [static system] [cached history] [current input] [runtime context]
        tmp_chat_history = [{"role": "system", "content": system_role}]
        for msg in self.chat_history:
            if msg["role"] != "system":
                tmp_chat_history.append(msg)
        tmp_chat_history.append({"role": "user", "content": self._format_user_message(message_content, user_id)})
        runtime_message = self._runtime_context_message(dynamic_with_memory)
        if runtime_message:
            tmp_chat_history.append(runtime_message)

        clean_history = [{"role": m["role"], "content": m["content"]} for m in tmp_chat_history]
        gpt_response = await call_llm_api(clean_history)

        self.add_message("user", message_content, user_id, trim=False)
        if self.memory:
            self.memory.store(self.group_id, None, gpt_response, "assistant")
        self.add_message("assistant", gpt_response)

        return gpt_response

    def _trim_chat_history(self) -> None:
        if len(self.chat_history) <= self._window_size + self._trim_slack():
            return
        self.chat_history = self.chat_history[-self._window_size:]

    def _trim_slack(self) -> int:
        return max(self._TRIM_SLACK_MIN, min(self._TRIM_SLACK_MAX, self._window_size // 5))

    @staticmethod
    def _format_user_message(message_content: str, user_id: Optional[int] = None) -> str:
        if user_id:
            return f"QQ{user_id}: {message_content}"
        return message_content

    @staticmethod
    def _runtime_context_message(runtime_context: str) -> Optional[dict]:
        runtime_context = (runtime_context or "").strip()
        if not runtime_context:
            return None
        return {"role": "system", "content": "[本轮运行时上下文]\n" + runtime_context + "\n[运行时上下文结束]"}
