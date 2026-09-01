import asyncio
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from command_handlers import MessageType
from plugins.markdown import markdown_to_image
from plugins.stickers import sticker_to_segment
from plugins.vision import fetch_image
from plugins.gemini import image_to_text
from api import search_web

# Matches both special tag types in one pass
_SPECIAL_RE   = re.compile(r'(<render_md>.*?</render_md>|<sticker:\w+>)', re.DOTALL)
_RENDER_MD_RE = re.compile(r'<render_md>(.*?)</render_md>', re.DOTALL)
_STICKER_RE   = re.compile(r'<sticker:(\w+)>')
_CQ_RE        = re.compile(r'\[CQ:[^\]]*\]')


MultimodalProcessor = Callable[[list, str], Awaitable[str]]


class AgentAction(Enum):
    IGNORE = "ignore"
    TOOL = "tool"
    CHAT = "chat"


@dataclass
class AgentDecision:
    action: AgentAction
    reason: str
    command_type: Optional[Any] = None


@dataclass
class AgentRunResult:
    handled: bool
    action: AgentAction
    reason: str


class AgentOrchestrator:
    """Coordinates command tools, persona prompts, sessions, and replies.

    This is deliberately small for now. It gives the bot a single agent entry
    point without forcing every plugin to become an LLM tool immediately.
    """

    def __init__(
        self,
        bot_interfaces: Dict[str, Any],
        command_handler,
        persona_engine,
        session_manager,
        multimodal_processor: MultimodalProcessor,
        ban_manager=None,
    ):
        self.bot_interfaces = bot_interfaces
        self.command_handler = command_handler
        self.persona_engine = persona_engine
        self.session_manager = session_manager
        self.multimodal_processor = multimodal_processor
        self.ban_manager = ban_manager
        # Adaptive debounce state per group
        self._buf: Dict[int, list] = {}       # group_id → [(ws, user_id, msg, segments), ...]
        self._timer: Dict[int, asyncio.Task] = {}
        self._msg_times: Dict[int, deque] = {} # group_id → deque of recent timestamps
        self._last_flush: Dict[int, float] = {}
        self._DEBOUNCE_MIN = 2.0
        self._DEBOUNCE_MAX = 15.0
        self._group_ws: Dict[int, Any] = {}  # latest ws per group
        # Proactive check: every 20 min, if silent > 1h, 20% chance say something
        self._proactive_task = asyncio.ensure_future(self._proactive_check_loop())

    async def handle_group_message(self, ws, payload: Dict[str, Any]) -> AgentRunResult:
        group_id = int(payload["group_id"])
        user_id = int(payload["user_id"])
        segments = payload.get("message", [])
        message_content = await self.bot_interfaces["encode_message_to_CQ"](segments)

        if self._is_banned(user_id):
            return AgentRunResult(True, AgentAction.IGNORE, "user is banned")

        # Track ws per group for proactive messaging
        self._group_ws[group_id] = ws

        # Check if group is sleeping
        if self.command_handler.is_sleeping(group_id) and not self.command_handler.get_command_type(message_content):
            return AgentRunResult(True, AgentAction.IGNORE, "group is sleeping")

        # Process images → text descriptions (before memory store)
        image_urls = []
        for seg in segments:
            if seg.get("type") == "image":
                url = seg.get("data", {}).get("url") or seg.get("data", {}).get("file")
                if url:
                    image_urls.append(url)
        if image_urls:
            descs = []
            for url in image_urls:
                try:
                    img_data = await fetch_image(url)
                    if img_data:
                        descs.append(await image_to_text(img_data))
                except Exception as exc:
                    print(f"[Agent] Image recognition failed: {exc}")
            if descs:
                message_content += "\n[图片内容: " + " / ".join(descs) + "]"

        # Store to long-term memory (with image descriptions)
        memory = self.session_manager.memory
        if memory:
            memory.store(group_id, user_id, message_content, "user")
            memory.store(user_id, user_id, message_content, "user", prefix="user")

        # Track message timing for adaptive debounce
        now = time.time()
        self._msg_times.setdefault(group_id, deque(maxlen=10)).append(now)

        # Commands: flush buffer first, then handle
        command_type = self.command_handler.get_command_type(message_content)
        if command_type:
            await self._flush_group_buffer(group_id)
            handled = await self.command_handler.handle_command(
                ws, MessageType.GROUP, command_type, message_content,
                group_id=group_id, user_id=user_id,
                message_id=payload.get("message_id"),
            )
            return AgentRunResult(handled, AgentAction.TOOL, "command")

        # @mention → reply immediately (no debounce)
        is_mention = self._is_at_me(segments)

        # Add to buffer
        self._buf.setdefault(group_id, []).append((ws, user_id, message_content, segments))

        if is_mention:
            # Cancel pending timer, flush now
            old = self._timer.pop(group_id, None)
            if old:
                old.cancel()
            await self._flush_group_buffer(group_id)
            return AgentRunResult(True, AgentAction.CHAT, "immediate reply to mention")

        # Calculate adaptive debounce delay
        delay = self._calc_debounce(group_id)
        print(f"[Agent] group {group_id} buffered (debounce={delay:.1f}s, pending={len(self._buf[group_id])})")

        # Cancel old timer, start new
        old = self._timer.pop(group_id, None)
        if old:
            old.cancel()
        self._timer[group_id] = asyncio.ensure_future(self._debounce_tick(group_id, delay))

        return AgentRunResult(True, AgentAction.CHAT, "buffered")

    async def _debounce_tick(self, group_id: int, delay: float):
        """Wait *delay* seconds, then flush the group buffer."""
        try:
            await asyncio.sleep(delay)
            await self._flush_group_buffer(group_id)
        except asyncio.CancelledError:
            pass

    def _calc_debounce(self, group_id: int) -> float:
        """Adaptive debounce: slower when chat is busy, faster when quiet."""
        times = self._msg_times.get(group_id)
        if not times or len(times) < 2:
            return self._DEBOUNCE_MIN
        intervals = [times[i] - times[i - 1] for i in range(1, len(times))]
        avg_interval = sum(intervals) / len(intervals)
        delay = avg_interval * 1.5
        return max(self._DEBOUNCE_MIN, min(self._DEBOUNCE_MAX, delay))

    async def _proactive_check_loop(self):
        """Every 20 min, if a group has been silent > 1h, 20% chance say something."""
        while True:
            await asyncio.sleep(1200)  # 20 minutes
            now = time.time()
            # Don't bother people during sleep hours (0-7am)
            hour = time.localtime().tm_hour
            if 0 <= hour < 7:
                continue

            for gid in list(self._group_ws.keys()):
                last = self._last_flush.get(gid, 0)
                if now - last < 21600:  # < 6 hours
                    continue
                if self.command_handler.is_sleeping(gid):
                    continue
                if random.random() > 0.20:
                    continue
                ws = self._group_ws.get(gid)
                if not ws:
                    continue
                try:
                    group = self.session_manager.get_group_session(gid)
                    persona_prompt = self.persona_engine.prepare(
                        0, "群里好久没人说话了，你突然想到什么想冒个泡？简短说一句，像真人偶遇一样自然。", is_group=True,
                    )
                    response = await group.handle_message(
                        0, persona_prompt.message_content, persona_prompt.system_role,
                        store_user=False, dynamic_context=persona_prompt.dynamic_context,
                    )
                    _IGNORE_RE = re.compile(r'<ignore>\s*', re.IGNORECASE)
                    if _IGNORE_RE.fullmatch(response.strip()):
                        if group.chat_history and group.chat_history[-1]["role"] == "assistant":
                            group.chat_history = group.chat_history[:-1]
                        continue
                    segments = await self._build_message_segments(response)
                    await self._send_with_human_delay(ws, gid, segments, is_group=True)
                    print(f"[Agent] group {gid} proactive message sent")
                except Exception as exc:
                    print(f"[Agent] proactive check failed for group {gid}: {exc}")

    async def _flush_group_buffer(self, group_id: int):
        """Send all buffered messages to LLM as a batch."""
        entries = self._buf.pop(group_id, [])
        self._timer.pop(group_id, None)
        if not entries:
            return

        now = time.time()
        self._last_flush[group_id] = now

        ws = entries[0][0]

        # ---- activity level & random participation ----
        msg_times = self._msg_times.get(group_id, deque())
        recent = [t for t in msg_times if now - t < 60]
        msgs_per_min = len(recent)
        if msgs_per_min > 8:
            activity = "high"
        elif msgs_per_min > 3:
            activity = "medium"
        else:
            activity = "low"

        # Check if bot is targeted
        has_mention = any(self._is_at_me(segs) for _, _, _, segs in entries)
        has_question = any("?" in msg or "？" in msg for _, _, msg, _ in entries)
        triggered = has_mention or has_question

        # Random skip for non-triggered messages
        # Still add to chat_history so bot has context when asked later
        if not triggered and random.random() > 0.20:
            group = self.session_manager.get_group_session(group_id)
            for _, uid, msg, _ in entries:
                group.add_message("user", msg, user_id=uid)
            print(f"[Agent] group {group_id} random skip ({activity=}, {msgs_per_min=}msgs/min)")
            return

        # Dynamic word limit
        word_limit = {"high": 30, "medium": 80}.get(activity, None)

        # Collect all unique user IDs from the batch for profile loading
        speaker_ids = list(set(uid for _, uid, _, _ in entries))
        all_profiles = []
        if self.persona_engine.profile_manager:
            for uid in speaker_ids:
                p = self.persona_engine.profile_manager.to_prompt(uid)
                if p:
                    all_profiles.append(f"QQ{uid}: {p}")
        profile_context = "\n".join(all_profiles)

        # Build batch context
        limit_hint = f" [活跃度:{'激烈' if activity=='high' else '闲聊'}, 回复限制:{word_limit}字以内]" if word_limit else ""
        lines = [
            f"[最近群聊消息{limit_hint}]",
            "[注意: 每行开头的 QQ<号码>: 是真实发言人，冒号后的内容才是该发言人的消息。]",
        ]
        for _, uid, msg, _ in entries:
            lines.append(f"QQ{uid}: {msg}")
        if word_limit:
            lines.append(f"\n（当前群聊很活跃，请将回复控制在 {word_limit} 字以内，一句说完不要霸屏）")
        batch_text = "\n".join(lines)

        print(f"[Agent] group {group_id} flushing {len(entries)}msgs ({activity=}, {triggered=}, limit={word_limit})")

        # Web search via Qwen (only when @mention + search keywords)
        _search_kw = ["搜索", "查一下", "帮我查", "天气", "新闻", "股价", "汇率", "今天几号", "最近发生"]
        search_context = ""
        if triggered and any(kw in batch_text for kw in _search_kw):
            try:
                print(f"[Agent] group {group_id} triggering web search...")
                search_result = await search_web(batch_text)
                if search_result:
                    search_context = f"[联网搜索结果]\n{search_result}\n[搜索结束]"
                    print(f"[Agent] group {group_id} search results injected ({len(search_result)} chars)")
            except Exception as exc:
                print(f"[Agent] group {group_id} search failed: {exc}")

        # Send to LLM
        persona_prompt = self.persona_engine.prepare(entries[-1][1], batch_text, is_group=True)
        runtime_context = persona_prompt.dynamic_context
        runtime_parts = []
        if profile_context:
            runtime_parts.append("[本批群友档案]\n" + profile_context)
        if word_limit:
            runtime_parts.append(f"[群聊回复限制]\n当前群聊较活跃，请将回复控制在 {word_limit} 字以内，一句说完不要霸屏。")
        if search_context:
            runtime_parts.append(search_context)
        if runtime_parts:
            runtime_context += "\n\n" + "\n\n".join(runtime_parts)
        group = self.session_manager.get_group_session(group_id)
        response = await group.handle_message(
            None,
            persona_prompt.message_content,
            persona_prompt.system_role,
            store_user=False,
            dynamic_context=runtime_context,
        )

        _IGNORE_RE = re.compile(r'<ignore>\s*', re.IGNORECASE)
        if _IGNORE_RE.fullmatch(response.strip()):
            print(f"[Agent] group {group_id} ignore — bot chose not to reply")
            if group.chat_history and group.chat_history[-1]["role"] == "assistant":
                group.chat_history = group.chat_history[:-1]
            return

        segments = await self._build_message_segments(response)
        await self._send_with_human_delay(ws, group_id, segments, is_group=True)

    async def handle_private_message(self, ws, payload: Dict[str, Any]) -> AgentRunResult:
        user_id = int(payload["user_id"])
        segments = payload.get("message", [])
        message_content = await self.bot_interfaces["encode_message_to_CQ"](segments)

        if self._is_banned(user_id):
            print(f"[Agent] Ignored banned user {user_id} in private chat")
            return AgentRunResult(True, AgentAction.IGNORE, "user is banned")

        decision = self.decide_private(message_content)
        print(f"[Agent] private decision={decision.action.value} reason={decision.reason}")

        if decision.action == AgentAction.TOOL:
            handled = await self.command_handler.handle_command(
                ws,
                MessageType.PRIVATE,
                decision.command_type,
                message_content,
                user_id=user_id,
            )
            return AgentRunResult(handled, decision.action, decision.reason)

        message_content = await self._with_reply_context(ws, segments, message_content)
        message_content = await self.multimodal_processor(segments, message_content)

        persona_prompt = self.persona_engine.prepare(user_id, message_content, is_group=False)
        if persona_prompt.blocked_override:
            print(f"[Persona] Blocked System Override from private user {user_id}")
        print(f"[Persona] Using {persona_prompt.mode} mode for private user {user_id}")

        user_session = self.session_manager.get_private_session(user_id)
        response = await user_session.handle_message(
            persona_prompt.message_content,
            persona_prompt.system_role,
            dynamic_context=persona_prompt.dynamic_context,
        )
        segments = await self._build_message_segments(response)
        await self._send_with_human_delay(ws, user_id, segments, is_group=False)
        return AgentRunResult(True, decision.action, decision.reason)

    async def _build_message_segments(self, response: str) -> List[dict]:
        """Split AI response into a mixed text+image OneBot segment list.

        Handles two special tag types inside the AI response:
          <render_md>…</render_md>  – render the enclosed markdown as a PNG image
          <sticker:name>            – insert the named pre-set sticker image

        Surrounding text may still contain CQ codes and is parsed normally.
        All failures degrade gracefully to plain text so nothing is lost silently.
        """
        if not _SPECIAL_RE.search(response):
            return await self.bot_interfaces["decode_CQ_to_message"](response)

        # split() with one capturing group → [text, tag, text, tag, …]
        parts = _SPECIAL_RE.split(response)
        result: List[dict] = []
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 0:
                # plain text segment (may contain CQ codes)
                result.extend(await self.bot_interfaces["decode_CQ_to_message"](part))
            elif part.startswith('<render_md>'):
                md_match = _RENDER_MD_RE.match(part)
                md_content = md_match.group(1).strip() if md_match else part
                md_content = _CQ_RE.sub('', md_content)
                try:
                    img_b64 = await markdown_to_image(md_content)
                    result.append({"type": "image", "data": {"file": f"base64://{img_b64}"}})
                except Exception as exc:
                    print(f"[Agent] markdown render failed, raw md content: {md_content[:200]}")
                    print(f"[Agent] markdown render exception: {exc}")
                    import traceback
                    traceback.print_exc()
                    result.extend(await self.bot_interfaces["decode_CQ_to_message"]("[Markdown 渲染失败，请稍后重试]"))
            elif part.startswith('<sticker:'):
                name = _STICKER_RE.match(part).group(1)
                seg = sticker_to_segment(name)
                if seg:
                    result.append(seg)
                else:
                    print(f"[Agent] sticker not found: {name}")
        return result

    def _is_banned(self, user_id: int) -> bool:
        if not self.ban_manager:
            return False
        if self.bot_interfaces["test_if_super_user"](user_id):
            return False
        return self.ban_manager.is_banned(user_id)

    def decide_group(self, message_content: str, segments: list) -> AgentDecision:
        command_type = self.command_handler.get_command_type(message_content)
        if command_type:
            return AgentDecision(AgentAction.TOOL, "matched explicit command", command_type)
        # Let LLM decide whether to reply — all messages go to chat
        return AgentDecision(AgentAction.CHAT, "auto-chat")

    def decide_private(self, message_content: str) -> AgentDecision:
        command_type = self.command_handler.get_command_type(message_content)
        if command_type:
            return AgentDecision(AgentAction.TOOL, "matched explicit command", command_type)
        return AgentDecision(AgentAction.CHAT, "private message")

    async def _with_reply_context(self, ws, segments: list, message_content: str) -> str:
        reply_id = self._reply_id(segments)
        if not reply_id:
            return message_content

        try:
            reply_message = await self.bot_interfaces["get_message_by_id"](ws, reply_id)
            if not reply_message or "message" not in reply_message:
                print(f"[Agent] Could not fetch replied message with id {reply_id}")
                return message_content

            reply_content = await self.bot_interfaces["encode_message_to_CQ"](
                reply_message["message"]
            )
            return (
                f"The user is replying to this message: '{reply_content}'. "
                f"Their new message is: {message_content}"
            )
        except Exception as exc:
            print(f"[Agent] Error fetching replied message {reply_id}: {exc}")
            return message_content

    def _is_at_me(self, segments: list) -> bool:
        bot_qq = str(self.bot_interfaces["bot_qq"])
        for part in segments:
            if part.get("type") == "at" and str(part.get("data", {}).get("qq")) == bot_qq:
                return True
        return False

    def _reply_id(self, segments: list) -> Optional[str]:
        for part in segments:
            if part.get("type") == "reply":
                reply_id = part.get("data", {}).get("id")
                if reply_id is not None:
                    return str(reply_id)
        return None

    # ------------------------------------------------------------------
    # Human-like sending helpers (anti-fraud / rate-limiting)
    # ------------------------------------------------------------------
    _CHUNK_MAX_LEN = 200  # characters; split if a chunk exceeds this

    async def _send_with_human_delay(
        self, ws, target_id: int, segments: list, is_group: bool
    ) -> None:
        """Send segments with a randomized pre-send delay.

        If the plain-text content exceeds _CHUNK_MAX_LEN characters the
        message is split on sentence boundaries (newlines, periods, etc.)
        and sent in chunks, each with its own inter-chunk delay.
        """
        # 1. Pre-send human-thinking delay (0.8 – 4.0 s)
        await asyncio.sleep(random.uniform(0.8, 4.0))

        # 2. Determine plain-text length for the chunking decision
        full_text = self._segments_to_plain_text(segments)
        has_non_text = any(seg.get("type") != "text" for seg in segments)

        if len(full_text) <= self._CHUNK_MAX_LEN or has_non_text:
            # short message, or contains images/stickers → send as-is
            if is_group:
                await self.bot_interfaces["send_group_message"](ws, target_id, segments)
            else:
                await self.bot_interfaces["send_private_message"](ws, target_id, segments)
            return

        # 3. Split into chunks and send one by one
        chunks = self._split_long_text(full_text)
        for chunk in chunks:
            chunk_segments = await self.bot_interfaces["decode_CQ_to_message"](chunk)
            if is_group:
                await self.bot_interfaces["send_group_message"](ws, target_id, chunk_segments)
            else:
                await self.bot_interfaces["send_private_message"](ws, target_id, chunk_segments)
            if chunk is not chunks[-1]:
                # inter-chunk delay (1.0 – 3.0 s)
                await asyncio.sleep(random.uniform(1.0, 3.0))

    @staticmethod
    def _segments_to_plain_text(segments: list) -> str:
        """Extract plain-text content from OneBot segments."""
        text = ""
        for seg in segments:
            if seg.get("type") == "text":
                text += seg.get("data", {}).get("text", "")
        return text

    @staticmethod
    def _split_long_text(text: str) -> List[str]:
        """Split *text* on sentence boundaries so each chunk ≤ _CHUNK_MAX_LEN.

        Boundaries tried in order:
          newline (\\n)  →  punctuation: (. ) / (。) / (！) / (？)
        If a single sentence still exceeds the limit it is cut at the
        limit boundary (hard split).
        """
        # Try splitting on newlines first
        lines = text.split("\n")
        # If at least one line already exceeds the limit, fallback to
        # punctuation-based splitting so we don't cut mid-sentence.
        if any(len(line) > AgentOrchestrator._CHUNK_MAX_LEN for line in lines):
            import re
            # Split on period+space, Chinese period, exclamation, question mark
            parts = re.split(r'(?<=\. )|(?<=。)|(?<=！)|(?<=？)', text)
            # Filter out empty strings
            parts = [p for p in parts if p]
            return AgentOrchestrator._merge_chunks(
                parts, AgentOrchestrator._CHUNK_MAX_LEN
            )
        return AgentOrchestrator._merge_chunks(
            lines, AgentOrchestrator._CHUNK_MAX_LEN
        )

    @staticmethod
    def _merge_chunks(parts: List[str], max_len: int) -> List[str]:
        """Merge *parts* greedily so that each result item ≤ max_len."""
        result = []
        buf = ""
        for part in parts:
            if not part.strip():
                # empty lines – append them to the current buffer so they
                # don't get lost
                if buf:
                    buf += "\n"
                continue
            if not buf:
                buf = part
                continue
            if len(buf) + 1 + len(part) <= max_len:
                buf += "\n" + part
            else:
                result.append(buf)
                buf = part
        if buf:
            result.append(buf)
        return result
