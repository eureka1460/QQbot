from typing import Optional
import time
from api import *


class Group:
    def __init__(self, group_id, bot_qq, memory=None, window_size: int = 30, save_callback=None):
        self.group_id = group_id
        self.users = {}
        self.chat_history = []
        self.bot_qq = bot_qq
        self.memory = memory
        self._window_size = window_size
        self._save_callback = save_callback

    def add_message(self, role, message_content, user_id=None):
        if role == "user" and user_id:
            message_content = f"QQ{user_id}: {message_content}"
        self.chat_history.append({
            "role": role,
            "content": message_content,
            "timestamp": int(time.time() * 1000),
        })
        if len(self.chat_history) > self._window_size:
            self.chat_history = self.chat_history[-self._window_size:]

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

        current_content = self._with_runtime_context(message_content, dynamic_with_memory)
        self.add_message("user", current_content, user_id)

        # Build messages: [static system] [append-only chat history]
        tmp_chat_history = [{"role": "system", "content": system_role}]
        for msg in self.chat_history:
            if msg["role"] != "system":
                tmp_chat_history.append(msg)

        clean_history = [{"role": m["role"], "content": m["content"]} for m in tmp_chat_history]
        gpt_response = await call_llm_api(clean_history)

        if self.memory:
            self.memory.store(self.group_id, None, gpt_response, "assistant")
        self.add_message("assistant", gpt_response)

        return gpt_response

    @staticmethod
    def _with_runtime_context(message_content: str, runtime_context: str) -> str:
        runtime_context = (runtime_context or "").strip()
        if not runtime_context:
            return message_content
        return (
            "[本轮运行时上下文]\n"
            + runtime_context
            + "\n[运行时上下文结束]\n\n"
            + "[当前群聊输入]\n"
            + message_content
        )
