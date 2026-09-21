"""Main application orchestrator wiring together PySide6, Playwright, DB, and AI."""
import asyncio
import sys
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
import qasync

from config.settings import get_settings
from database.db import init_db, test_db_connection
from gui.main_window import MainWindow
from browser.manager import BrowserManager
from browser.tinder import TinderBrowser
from browser.match_scanner import MatchScanner
from browser.message_detector import MessageDetector
from browser.sender import MessageSender
from conversations.manager import ConversationManager
from conversations.queue import ConversationState
from ai.client import LLMClient
from ai.generator import ResponseGenerator
from ai.memory import ConversationMemory
from ai.classifier import IntentClassifier, IntentCategory
from services.match_service import MatchService
from services.message_service import MessageService
from services.reply_service import ReplyService
from services.account_service import AccountService
from utils.logger import logger
from utils.sleep_preventer import sleep_preventer


class TinderAppController:
    """Master controller orchestrating GUI, background scanner tasks, and AI pipelines."""

    def __init__(self, window: MainWindow):
        self.window = window
        self.settings = get_settings()
        self.browser_mgr = BrowserManager()
        self.tinder_browser = TinderBrowser(self.browser_mgr)
        self.llm_client = LLMClient()
        self.ai_generator = ResponseGenerator(self.llm_client)
        self.memory = ConversationMemory(self.llm_client)
        
        # Conversation manager with async AI handler callback
        self.conv_manager = ConversationManager(ai_handler=self.on_bundled_messages_ready)
        
        self.sender: MessageSender | None = None
        self.scanner: MatchScanner | None = None
        # Tinder automation uses one shared tab. Every navigation/detection/send
        # operation must be serialized or one conversation can steal another's
        # textbox between verification and Enter.
        self._browser_operation_lock = asyncio.Lock()
        self._scanner_task: asyncio.Task | None = None
        self._opener_task: asyncio.Task | None = None
        self._msg_monitor_task: asyncio.Task | None = None
        self._history_backfilled: set[str] = set()
        # Style/question metadata of the reply awaiting send, per conversation.
        # Persisted to memory only after the message is really sent.
        self._pending_reply_meta: dict[str, dict] = {}
        # Consecutive turns where no acceptable reply could be produced, per conversation.
        self._giveup_counts: dict[str, int] = {}
        self._unread_conversations: set[str] = set()
        self._queued_message_hashes: set[str] = set()
        self._auto_scan_index = 0
        self._opener_sent_or_checked: set[str] = set()
        # Once a waiting conversation is detected, keep Tinder on that person
        # through debounce, AI generation, and every outgoing message. Only the
        # completing worker may release this reservation.
        self._active_conversation_turn: str | None = None
        self._active_conversation_name: str = ""
        self._is_running = True

    async def initialize(self):
        """Initialize database, check AI connectivity, and prepare browser."""
        # 1. Database check
        try:
            await init_db()
            db_ok = await test_db_connection()
            logger.info(f"Database connection: {'OK' if db_ok else 'FAILED'}")
        except Exception as e:
            logger.error(f"Database init error: {e}")

        # 2. AI check
        ai_ok, ai_msg = await self.llm_client.test_connection()
        self.window.set_ai_status(ai_ok, "Ready" if ai_ok else "Check Key")

        # 3. Load initial matches from database
        stored_matches = await MatchService.list_matches()
        if stored_matches:
            self.window.matches_panel.set_matches(stored_matches)

        # Connect GUI actions to controller
        self.window.reply_panel.send_requested.connect(
            lambda cid, text: asyncio.create_task(self.handle_user_send_reply(cid, text))
        )
        self.window.reply_panel.regenerate_requested.connect(
            lambda cid: asyncio.create_task(self.handle_user_regenerate_reply(cid))
        )
        self.window.matches_panel.match_mode_updated.connect(
            lambda tid, mode: asyncio.create_task(self.handle_mode_update(tid, mode))
        )
        self.window.matches_panel.match_selected.connect(
            lambda tid: asyncio.create_task(self.handle_match_selected(tid))
        )
        self.window.btn_auto_swipe.clicked.connect(
            lambda: asyncio.create_task(self.handle_auto_swipe())
        )
        self.window.btn_auto_opener.clicked.connect(
            lambda: asyncio.create_task(self.handle_auto_opener())
        )

        # Connect account and session management signals
        self.window.account_login_requested.connect(
            lambda: asyncio.create_task(self.handle_login())
        )
        self.window.account_logout_requested.connect(
            lambda: asyncio.create_task(self.handle_logout())
        )
        self.window.account_switch_requested.connect(
            lambda aid: asyncio.create_task(self.handle_switch_account(aid))
        )
        self.window.account_add_requested.connect(
            lambda: asyncio.create_task(self.handle_add_account())
        )

        logger.info("Application controller initialized.")

    async def start_browser(self):
        """Launch persistent browser and monitor login."""
        try:
            active_acc = AccountService.get_active_account()
            self.browser_mgr.settings.browser.profile_dir = active_acc.get("profile_dir", "./data/tinder_browser")
            page = await self.browser_mgr.start()
            self.sender = MessageSender(page, operation_lock=self._browser_operation_lock)
            self.scanner = MatchScanner(
                page,
                operation_lock=self._browser_operation_lock,
                can_switch_tabs=lambda: self._active_conversation_turn is None,
            )

            # Check login
            is_logged_in = await self.browser_mgr.check_login_status()
            if is_logged_in:
                self.window.set_tinder_status(True, "Connected")
                await self.on_logged_in()
            else:
                self.window.set_tinder_status(False, "Waiting Login")
                # Wait in background
                asyncio.create_task(self._poll_for_login())
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            self.window.set_tinder_status(False, "Error")

    async def _poll_for_login(self):
        logged_in = await self.browser_mgr.wait_for_manual_login(timeout_seconds=300)
        if logged_in:
            self.window.set_tinder_status(True, "Connected")
            await self.on_logged_in()
        else:
            self.window.set_tinder_status(False, "Login Timeout")

    async def on_logged_in(self):
        """Called once Tinder session is established."""
        logger.info("Tinder session ready. Running selector health check...")
        if self.browser_mgr.page:
            inspector = self.tinder_browser.get_inspector()
            healthy, _ = await inspector.perform_health_check()
            self.window.set_dom_status(healthy)

            if not healthy:
                logger.warning("Selector health check notice: some selectors were not found immediately. Continuing with settings.")

            # Recover any messages stuck in NEW/GENERATING/SENDING/READY_TO_SEND due to a previous crash
            await self.recover_pending_messages()

            # Start match scanner loop
            if self.scanner:
                self._scanner_task = asyncio.create_task(
                    self.scanner.run_loop(
                        interval_seconds=self.settings.scanner.match_scan_interval,
                        on_matches_found=self.on_matches_scanned
                    )
                )

            # Start message monitor loop for incoming chat messages
            self._msg_monitor_task = asyncio.create_task(self._message_monitor_background_loop())

            # AUTO chats are inspected by the scanner/monitor pipeline. Empty
            # chats receive their opener there, avoiding a second navigation
            # loop racing against incoming-message detection.

    def _reserve_conversation_turn(self, conversation_id: str, match_name: str) -> bool:
        """Reserve the shared Tinder tab for one complete conversation turn."""
        if self._active_conversation_turn not in (None, conversation_id):
            return False
        if self._active_conversation_turn is None:
            logger.info(
                f"🔒 Giữ hội thoại {match_name} ({conversation_id[:8]}...) "
                "cho đến khi trả lời xong."
            )
        self._active_conversation_turn = conversation_id
        self._active_conversation_name = match_name
        return True

    def _release_conversation_turn(self, conversation_id: str) -> None:
        """Release a reservation only from the worker that owns it."""
        if self._active_conversation_turn == conversation_id:
            logger.info(
                f"🔓 Đã xử lý xong {self._active_conversation_name or conversation_id}; "
                "có thể chuyển sang người tiếp theo."
            )
            self._active_conversation_turn = None
            self._active_conversation_name = ""

    async def on_matches_scanned(self, matches: list[dict]):
        """Handler when match scanner finds matches."""
        synced = await MatchService.sync_matches(matches)
        for m in synced:
            self.window.matches_panel.add_or_update_match(
                tinder_id=m["tinder_id"],
                name=m["name"],
                status=m["status"],
                mode=m["mode"]
            )

        # A detected waiting conversation owns the tab until its entire reply is
        # complete. Do not round-robin to another person during debounce or AI.
        reserved_id = self._active_conversation_turn
        if reserved_id and self.browser_mgr.page and not self.browser_mgr.page.is_closed():
            async with self._browser_operation_lock:
                if self.tinder_browser.get_current_conversation_id() != reserved_id:
                    logger.info(
                        f"↩️ Quay lại hội thoại đang xử lý "
                        f"{self._active_conversation_name or reserved_id}."
                    )
                    await self.browser_mgr.page.goto(
                        f"https://tinder.com/app/messages/{reserved_id}",
                        wait_until="networkidle",
                        timeout=15000,
                    )
            return

        # Inspect every explicitly AUTO conversation in round-robin order, even
        # when Tinder fails to render a red/unread badge. Message order inside
        # the chat determines whether they are waiting for our reply.
        if (
            self.settings.global_auto_reply
            and not self.settings.is_paused
            and not self.settings.emergency_stop
            and not getattr(self, "_swiping", False)
            and self.browser_mgr.page
            and not self.browser_mgr.page.is_closed()
        ):
            auto_matches = []
            for match in matches:
                tinder_id = match.get("tinder_id")
                if tinder_id and await MatchService.get_mode(tinder_id) == "AUTO":
                    auto_matches.append(match)
                    if match.get("has_unread"):
                        self._unread_conversations.add(tinder_id)

            if auto_matches:
                unread = [
                    match for match in auto_matches
                    if match.get("tinder_id") in self._unread_conversations
                ]
                if unread:
                    target = unread[0]
                else:
                    target = auto_matches[self._auto_scan_index % len(auto_matches)]
                    self._auto_scan_index += 1

                tinder_id = target["tinder_id"]
                async with self._browser_operation_lock:
                    # Reservation may have been created while this scanner was
                    # waiting for the browser lock. Re-check before navigation.
                    if self._active_conversation_turn:
                        return
                    current_id = self.tinder_browser.get_current_conversation_id()
                    if current_id != tinder_id:
                        logger.info(
                            f"🔎 Kiểm tra hội thoại AUTO của {target.get('name')} "
                            f"({tinder_id[:8]}...), không phụ thuộc dấu chưa đọc."
                        )
                        try:
                            await self.browser_mgr.page.goto(
                                f"https://tinder.com/app/messages/{tinder_id}",
                                wait_until="networkidle",
                                timeout=15000,
                            )
                        except Exception as e:
                            logger.warning(f"Error opening AUTO chat {tinder_id}: {e}")

        # Never infer "unmatched" from a sidebar scan. Tinder only renders a
        # partial/virtualized tab at a time, so absence from this scan is not
        # proof that a match was removed. Automatic cleanup previously deleted
        # valid conversations and raced with active DB sessions.

    async def on_bundled_messages_ready(self, state: ConversationState, bundled_messages: list[dict[str, str]]):
        """Process one reserved person's complete turn, then allow navigation."""
        self._reserve_conversation_turn(state.conversation_id, state.match_name)
        try:
            await self._process_bundled_messages_ready(state, bundled_messages)
        finally:
            self._release_conversation_turn(state.conversation_id)

    async def _process_bundled_messages_ready(self, state: ConversationState, bundled_messages: list[dict[str, str]]):
        """Triggered after debounce expires when messages are ready for AI processing."""
        logger.info(f"Processing AI reply for {state.match_name} ({len(bundled_messages)} messages)")
        
        message_texts = [m["content"] for m in bundled_messages]
        message_hashes = [m["hash"] for m in bundled_messages]

        # Per-user memory: full history of THIS conversation + saved summary/facts -> final context
        memory_ctx = None
        try:
            memory_ctx = await self.memory.build_context(state.conversation_id, message_texts)
        except Exception as e:
            logger.warning(f"Memory context failed, falling back to in-memory history: {e}")

        out_messages, is_safe_for_auto, intent, meta = await self.ai_generator.generate_response(
            state, message_texts, memory=memory_ctx
        )
        # They closed a topic ("hong á", "thôi bỏ qua"...): remember it so later turns stay off it.
        if meta.get("closed_topic"):
            try:
                await self.memory.record_closed_topic(state.conversation_id, meta["closed_topic"])
            except Exception as e:
                logger.debug(f"Could not persist closed topic for {state.conversation_id}: {e}")

        if not out_messages:
            if meta.get("gave_up"):
                # Not a deliberate WAIT: nothing acceptable could be produced. Do not drop
                # their message; let the monitor pick it up again (bounded number of retries).
                count = self._giveup_counts.get(state.conversation_id, 0) + 1
                self._giveup_counts[state.conversation_id] = count
                if count <= 2:
                    logger.info(f"Chưa có câu trả lời đạt chuẩn cho {state.match_name}, sẽ thử lại (lần {count}/2).")
                    await MessageService.update_messages_status(message_hashes, "FAILED")
                    self._queued_message_hashes.difference_update(message_hashes)
                    return
                logger.warning(f"Đã thử lại nhiều lần cho {state.match_name} mà không có câu đạt chuẩn; bỏ qua lượt này.")
            # If AI says WAIT (or we gave up for good)
            await MessageService.update_messages_status(message_hashes, "IGNORED")
            return
        self._giveup_counts.pop(state.conversation_id, None)

        gui_reply_text = "\n".join(out_messages)
        self._pending_reply_meta[state.conversation_id] = meta

        # Save AI reply to DB
        import json
        hashes_json = json.dumps(message_hashes)
        reply_id = await ReplyService.record_reply(
            conversation_id=state.conversation_id,
            input_text=" \n ".join(message_texts),
            output_text=gui_reply_text,
            status="READY_TO_SEND",
            message_hashes=hashes_json
        )
        await MessageService.update_messages_status(message_hashes, "READY_TO_SEND")

        # Update GUI if this is the currently viewed conversation
        if self.window.reply_panel.current_conversation_id == state.conversation_id:
            self.window.reply_panel.set_suggestion(state.conversation_id, gui_reply_text)

        # AUTO mode execution criteria
        can_auto_send = (
            state.mode == "AUTO"
            and not self.settings.dry_run
            and self.settings.global_auto_reply
            and not self.settings.is_paused
            and not self.settings.emergency_stop
        )

        if can_auto_send and self.sender:
            import random
            import asyncio
            logger.info(f"Auto-dispatching {len(out_messages)} replies to {state.match_name}...")
            
            # Transition to SENDING
            await ReplyService.update_status_raw(reply_id, "SENDING")
            await MessageService.update_messages_status(message_hashes, "SENDING")
            
            all_sent = True
            sent_messages: list[str] = []
            for i, msg in enumerate(out_messages):
                sent = await self.sender.send_reply(state.conversation_id, msg, is_auto=True)
                if sent:
                    await self._remember_sent(state.conversation_id, msg)
                    sent_messages.append(msg)
                else:
                    all_sent = False
                
                # Delay between multiple messages
                if i < len(out_messages) - 1:
                    await asyncio.sleep(random.uniform(2.5, 4.5))

            await self._record_reply_memory(state.conversation_id, sent_messages)
            if all_sent:
                await ReplyService.mark_sent(reply_id)
                await MessageService.update_messages_status(message_hashes, "SENT")
                self.window.reply_panel.clear_suggestion()
            else:
                await ReplyService.update_status_raw(reply_id, "FAILED")
                await MessageService.update_messages_status(message_hashes, "FAILED")
        else:
            logger.info(f"Reply presented as suggestion in GUI for {state.match_name} (Mode={state.mode})")

        # Update advanced memory
        is_opener = len(state.history) == 0
        await self.memory.update_advanced_memory(
            state.conversation_id,
            "",  # asked intent is persisted on real send (record_sent_reply)
            meta.get("topic", ""),
            meta.get("pattern_used", ""),
            is_opener=is_opener,
            sent_messages=out_messages
        )

        # Check if conversation wrap-up / goodnight / busy / text later -> auto transition to OFF
        combined_text = " ".join(message_texts)
        is_closing, closing_type = IntentClassifier.is_conversation_closing(combined_text)
        if intent in (IntentCategory.GOODNIGHT.value, IntentCategory.BUSY_LATER.value) or is_closing:
            actual_type = closing_type or ("GOODNIGHT" if intent == IntentCategory.GOODNIGHT.value else "BUSY_LATER")
            if actual_type == "GOODNIGHT":
                icon, label, log_desc = "🌙", "💤 Ngủ ngon (OFF)", "chúc ngủ ngon"
            else:
                icon, label, log_desc = "⏳", "⏳ Bận / Nhắn sau (OFF)", "báo bận / nhắn lại sau"

            logger.info(
                f"{icon} Phát hiện tin nhắn {log_desc} từ {state.match_name}. "
                f"Tự động chuyển chế độ sang OFF."
            )
            await self.handle_mode_update(state.conversation_id, "OFF")
            self.window.matches_panel.update_match_mode(state.conversation_id, "OFF")
            self.window.matches_panel.update_match_status(state.conversation_id, label)
            self.window.status_bar.showMessage(
                f"{icon} [{state.match_name}] {log_desc}. Đã tự chuyển sang OFF.", 8000
            )

    async def _record_reply_memory(self, conversation_id: str, sent_messages: list[str]) -> None:
        """Persist questions_already_asked / last_reply_styles for messages that were really sent."""
        meta = self._pending_reply_meta.pop(conversation_id, None) or {}
        sent_messages = [m for m in sent_messages if m and m.strip()]
        if not sent_messages:
            return
        try:
            from ai.question_detector import is_question

            question_texts = [m for m in sent_messages if is_question(m)]
            for q in meta.get("question_texts", []):
                if q in sent_messages and q not in question_texts:
                    question_texts.append(q)
            asked = bool(question_texts)
            await self.memory.record_sent_reply(
                conversation_id,
                reply_style=meta.get("reply_style", "") or ("question" if asked else ""),
                asked=asked,
                question_key=meta.get("question_key", "") if asked else "",
                question_texts=question_texts,
            )
        except Exception as e:
            logger.debug(f"Could not persist reply memory for {conversation_id}: {e}")

    @staticmethod
    def _norm_text(text: str) -> str:
        import re
        text = re.sub(r"^\s*(Bạn|You)\s*:\s*", "", text or "", flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip().lower()

    async def _remember_sent(self, conversation_id: str, text: str):
        """Record a message we sent so the monitor never treats it as incoming."""
        if not hasattr(self, "_sent_texts"):
            self._sent_texts = {}
        self._sent_texts.setdefault(conversation_id, set()).add(self._norm_text(text))
        try:
            from utils.helpers import compute_message_hash
            await MessageService.save_message_if_new(
                conversation_id=conversation_id,
                match_id=conversation_id,
                sender="You",
                role="outgoing",
                content=text,
                message_hash=compute_message_hash(conversation_id, "You", text),
            )
        except Exception as e:
            logger.debug(f"Could not persist sent message: {e}")

    async def handle_user_send_reply(self, conversation_id: str, text: str):
        """User clicked 'Send' button on GUI."""
        if self.sender:
            logger.info(f"Sending manually approved reply to {conversation_id}...")
            await self.sender.send_reply(conversation_id, text, is_auto=False)
            await self._remember_sent(conversation_id, text)
            await self._record_reply_memory(conversation_id, [line for line in text.split("\n") if line.strip()])
            
            # Mark the latest reply as SENT so it doesn't get resent on mode switch
            recent_reply = await ReplyService.get_latest_reply(conversation_id)
            if recent_reply and recent_reply.status == "READY_TO_SEND":
                await ReplyService.mark_sent(recent_reply.id)
                import json
                if recent_reply.message_hashes:
                    try:
                        hashes = json.loads(recent_reply.message_hashes)
                        await MessageService.update_messages_status(hashes, "SENT")
                    except Exception:
                        pass
                        
            self.window.reply_panel.clear()

            # If user sent a goodnight / busy / closing message, also transition to OFF
            is_closing, closing_type = IntentClassifier.is_conversation_closing(text)
            if is_closing:
                if closing_type == "GOODNIGHT":
                    icon, label, log_desc = "🌙", "💤 Ngủ ngon (OFF)", "chúc ngủ ngon"
                else:
                    icon, label, log_desc = "⏳", "⏳ Bận / Nhắn sau (OFF)", "báo bận / nhắn lại sau"

                logger.info(f"{icon} Bạn đã gửi tin nhắn {log_desc} tới {conversation_id}. Tự động chuyển sang OFF.")
                await self.handle_mode_update(conversation_id, "OFF")
                self.window.matches_panel.update_match_mode(conversation_id, "OFF")
                self.window.matches_panel.update_match_status(conversation_id, label)
                self.window.status_bar.showMessage(f"{icon} Đã gửi tin nhắn {log_desc}. Match đã chuyển sang OFF.", 5000)

    async def handle_user_regenerate_reply(self, conversation_id: str):
        state = self.conv_manager.get_state(conversation_id)
        if state and state.history:
            last_msg = state.history[-1]["content"] if state.history else "hi"
            if last_msg:
                self.window.reply_panel.set_suggestion(conversation_id, "Đang suy nghĩ lại...")
                memory_ctx = None
                try:
                    memory_ctx = await self.memory.build_context(conversation_id, [last_msg])
                except Exception as e:
                    logger.warning(f"Memory context failed for regenerate: {e}")
                out_messages, _, _, regen_meta = await self.ai_generator.generate_response(
                    state, [last_msg], memory=memory_ctx
                )
                if out_messages:
                    self._pending_reply_meta[conversation_id] = regen_meta
                    gui_reply_text = "\n".join(out_messages)
                    self.window.reply_panel.set_suggestion(conversation_id, gui_reply_text)
                else:
                    self.window.reply_panel.set_suggestion(conversation_id, "Không tạo được phản hồi")

    async def handle_mode_update(self, tinder_id: str, mode: str):
        await MatchService.set_mode(tinder_id, mode)
        self.conv_manager.set_mode(tinder_id, mode)
        
        if mode == "AUTO":
            asyncio.create_task(self._auto_dispatch_pending_on_mode_change(tinder_id))

    async def recover_pending_messages(self):
        """Discard stale work after a crash; only dispatch an already-generated reply for an explicit AUTO match."""
        from database.db import get_db_session
        from sqlalchemy import select
        from database.models import MessageModel, ConversationModel

        async with get_db_session() as session:
            # Never regenerate from old NEW/GENERATING/SENDING rows at startup.
            # Existing databases may contain historical messages marked NEW, and
            # replaying them causes the bot to answer an entire old transcript.
            stmt = select(MessageModel).where(
                MessageModel.status.in_(["NEW", "GENERATING", "SENDING"])
            )
            result = await session.execute(stmt)
            stale_hashes = [m.message_hash for m in result.scalars().all()]
            if stale_hashes:
                await MessageService.update_messages_status(stale_hashes, "IGNORED")
                logger.info(
                    f"Ignored {len(stale_hashes)} stale pending message(s) during safe startup recovery."
                )

            # Dispatch READY_TO_SEND messages only for the individual match that
            # is explicitly AUTO. OFF/SUGGEST modes are never changed here.
            stmt = select(ConversationModel)
            result = await session.execute(stmt)
            for conv in result.scalars().all():
                from services.match_service import MatchService
                mode = await MatchService.get_mode(conv.match_id)
                if mode == "AUTO":
                    await self._auto_dispatch_pending_on_mode_change(conv.match_id)

    async def _auto_dispatch_pending_on_mode_change(self, tinder_id: str):
        recent_reply = await ReplyService.get_latest_reply(tinder_id)
        if recent_reply and recent_reply.status == "READY_TO_SEND":
            if self.sender and self.settings.global_auto_reply and not self.settings.dry_run and not self.settings.is_paused:
                logger.info(f"Auto-dispatching pending generated reply for {tinder_id} after mode switch to AUTO.")
                out_messages = recent_reply.output_text.split('\n')
                all_sent = True
                
                # If currently viewing this conversation, update GUI
                if self.window.reply_panel.current_conversation_id == tinder_id:
                    self.window.reply_panel.lbl_status.setText("Sending pending...")
                    
                for i, msg in enumerate(out_messages):
                    msg = msg.strip()
                    if not msg:
                        continue
                    sent = await self.sender.send_reply(tinder_id, msg, is_auto=True)
                    if sent:
                        await self._remember_sent(tinder_id, msg)
                    else:
                        all_sent = False
                        
                    if i < len(out_messages) - 1:
                        import random
                        await asyncio.sleep(random.uniform(2.5, 4.5))
                
                import json
                message_hashes = []
                if recent_reply.message_hashes:
                    try:
                        message_hashes = json.loads(recent_reply.message_hashes)
                    except Exception:
                        pass

                if all_sent:
                    await self._record_reply_memory(tinder_id, [m.strip() for m in out_messages if m.strip()])
                    await ReplyService.mark_sent(recent_reply.id)
                    await MessageService.update_messages_status(message_hashes, "SENT")
                    if self.window.reply_panel.current_conversation_id == tinder_id:
                        self.window.reply_panel.clear_suggestion()
                else:
                    await ReplyService.update_status_raw(recent_reply.id, "FAILED")
                    await MessageService.update_messages_status(message_hashes, "FAILED")

    async def handle_match_selected(self, tinder_id: str):
        state = self.conv_manager.get_state(tinder_id)
        if state:
            name = state.match_name
            age = state.profile.get("age")
            bio = state.profile.get("bio")
            interests = state.profile.get("interests")
        else:
            match_db = await MatchService.get_match(tinder_id)
            if match_db:
                name = match_db.name
                age = getattr(match_db, "age", None)
                bio = getattr(match_db, "bio", "")
                interests = []
                import json
                if match_db.profile_json:
                    try:
                        p = json.loads(match_db.profile_json)
                        interests = p.get("interests", [])
                    except Exception:
                        pass
            else:
                name = "Unknown"
                age = None
                bio = ""
                interests = []

        self.window.conversation_panel.display_profile(
            name=name,
            age=age,
            bio=bio,
            interests=interests
        )
        recent_msgs = await MessageService.get_recent_messages(tinder_id)
        self.window.conversation_panel.display_messages(recent_msgs)
        self.window.reply_panel.current_conversation_id = tinder_id

    def stop_auto_swipe(self):
        engine = getattr(self, "_swipe_engine", None)
        if engine:
            engine.stop()

    async def handle_auto_swipe(self):
        """Trigger auto-liking on recs until likes run out."""
        if not self.browser_mgr.page or self.browser_mgr.page.is_closed():
            logger.warning("Browser is not active for auto-swipe.")
            return
        if getattr(self, "_swiping", False):
            # Clicking again while running = stop
            self.stop_auto_swipe()
            self.window.status_bar.showMessage("Đã dừng Auto-Like.", 6000)
            return
        if self._active_conversation_turn:
            self.window.status_bar.showMessage(
                f"Đang trả lời {self._active_conversation_name}; "
                "Auto-Like sẽ không chuyển trang lúc này.",
                8000,
            )
            return
        from browser.auto_swipe import AutoSwipeEngine
        engine = AutoSwipeEngine(self.browser_mgr.page)
        self._swipe_engine = engine
        self.window.btn_auto_swipe.setText("⏹ Dừng Auto-Like")
        self.window.status_bar.showMessage("Đang tự động like thẻ (bấm lại để dừng)...")
        self._swiping = True
        try:
            async with self._browser_operation_lock:
                if self._active_conversation_turn:
                    self.window.status_bar.showMessage(
                        f"Đang trả lời {self._active_conversation_name}; "
                        "đã hủy Auto-Like để giữ nguyên hội thoại.",
                        8000,
                    )
                    return
                results = await engine.run(
                    # No artificial cap: the loop already terminates on its own via
                    # is_out_of_likes() (Tinder's real "out of likes" modal) or should_stop().
                    max_swipes=10_000_000,
                    should_stop=lambda: self.settings.is_paused or self.settings.emergency_stop,
                )
        finally:
            self._swiping = False
            self._swipe_engine = None
            self.window.btn_auto_swipe.setText("⚡ Auto-Like (Hết lượt)")
        self.window.status_bar.showMessage(
            f"Hoàn tất quẹt: Đã like {results['swiped']}, Matches mới: {results['matches']}"
        )

    async def handle_auto_opener(self):
        """Trigger reading profile and sending subtle flirty openers to new matches."""
        if not self.browser_mgr.page or self.browser_mgr.page.is_closed():
            logger.warning("Browser is not active for auto-opener.")
            return
        if self._active_conversation_turn:
            self.window.status_bar.showMessage(
                f"Đang trả lời {self._active_conversation_name}; "
                "hãy chờ gửi xong trước khi mở lời người khác.",
                8000,
            )
            return
        if getattr(self, "_swiping", False):
            # Switch mode: stop auto-like, wait for it to finish, then run openers
            logger.info("Dừng Auto-Like để chuyển sang thả thính...")
            self.stop_auto_swipe()
            for _ in range(40):
                if not getattr(self, "_swiping", False):
                    break
                await asyncio.sleep(0.25)
        from browser.match_opener import MatchOpenerEngine
        from services.opener_service import OpenerService
        engine = MatchOpenerEngine(self.browser_mgr.page, OpenerService(self.llm_client))
        self.window.status_bar.showMessage("Đang tự động mở lời (thả thính nhẹ) cho các match mới...")
        async with self._browser_operation_lock:
            if self._active_conversation_turn:
                self.window.status_bar.showMessage(
                    f"Đang trả lời {self._active_conversation_name}; "
                    "đã hoãn mở lời người khác.",
                    8000,
                )
                return
            sent = await engine.run_openers_on_all_new_matches(max_openers=10)
        self.window.status_bar.showMessage(f"Hoàn tất mở lời: Đã gửi {sent} câu mở lời.")

    async def _auto_opener_background_loop(self):
        """Background loop: checks for matches without existing messages and automatically sends tailored openers."""
        await asyncio.sleep(6.0)
        logger.info("Auto-opener background loop initialized.")
        while self._is_running:
            try:
                if (
                    self.browser_mgr.page
                    and not self.browser_mgr.page.is_closed()
                    and self.settings.global_auto_reply
                    and not self.settings.is_paused
                    and not self.settings.emergency_stop
                    and not getattr(self, "_swiping", False)
                    and self._active_conversation_turn is None
                ):
                    from browser.match_opener import MatchOpenerEngine
                    from services.opener_service import OpenerService
                    engine = MatchOpenerEngine(self.browser_mgr.page, OpenerService(self.llm_client))
                    self.window.status_bar.showMessage("💌 Đang tự động mở lời (thả thính) cho các match mới...")
                    async with self._browser_operation_lock:
                        if self._active_conversation_turn:
                            sent = 0
                        else:
                            sent = await engine.run_openers_on_all_new_matches(max_openers=10)
                    if sent > 0:
                        self.window.status_bar.showMessage(f"💌 Hoàn tất mở lời: Đã tự động gửi {sent} câu mở lời!", 8000)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Auto-opener background loop error: {e}")

            # Sleep 120 seconds between opener sweeps
            await asyncio.sleep(120.0)

    async def _message_monitor_background_loop(self):
        """Continuously monitor active conversation window for incoming messages."""
        await asyncio.sleep(4.0)
        logger.info("Message monitor background loop started.")
        while self._is_running:
            try:
                if (
                    self.browser_mgr.page
                    and not self.browser_mgr.page.is_closed()
                    and not self.settings.is_paused
                    and not self.settings.emergency_stop
                ):
                    async with self._browser_operation_lock:
                        conv_id = self.tinder_browser.get_current_conversation_id()
                        reserved_id = self._active_conversation_turn
                        if reserved_id and conv_id != reserved_id:
                            logger.info(
                                f"↩️ Giữ nguyên lượt của "
                                f"{self._active_conversation_name or reserved_id}; "
                                "chưa chuyển sang người khác."
                            )
                            await self.browser_mgr.page.goto(
                                f"https://tinder.com/app/messages/{reserved_id}",
                                wait_until="networkidle",
                                timeout=15000,
                            )
                            conv_id = reserved_id

                        if not conv_id:
                            await asyncio.sleep(self.settings.scanner.message_scan_interval or 3.0)
                            continue

                        detector = MessageDetector(self.browser_mgr.page)
                        mode = await MatchService.get_mode(conv_id)
                        match_db = await MatchService.get_match(conv_id)
                        resolved_name = match_db.name if match_db else "Match"
                        state = await self.conv_manager.get_or_create_state(
                            conv_id, conv_id, resolved_name, mode=mode
                        )
                        match_name = state.match_name

                        first_visit = conv_id not in self._history_backfilled
                        if first_visit:
                            await detector.scroll_to_top_of_history()

                        msgs = await detector.detect_messages_in_current_chat(
                            conv_id, conv_id, match_name
                        )

                        # A genuinely empty AUTO chat is a new match: send exactly
                        # one opener. This does not depend on a red/unread badge.
                        if not msgs and mode == "AUTO" and conv_id not in self._opener_sent_or_checked:
                            from browser.match_opener import MatchOpenerEngine
                            from services.opener_service import OpenerService

                            opener_engine = MatchOpenerEngine(
                                self.browser_mgr.page,
                                OpenerService(self.llm_client),
                            )
                            if not await opener_engine.has_existing_messages():
                                profile = await opener_engine.read_current_chat_profile(
                                    default_name=match_name
                                )
                                opener = await opener_engine.opener_service.generate_opener(profile)
                                if await opener_engine.send_opener_to_current_chat(conv_id, opener):
                                    await self._remember_sent(conv_id, opener)
                                    logger.info(
                                        f"💌 Đã mở lời cho match AUTO mới {match_name}: \"{opener}\""
                                    )
                            self._opener_sent_or_checked.add(conv_id)
                            self._history_backfilled.add(conv_id)
                            continue

                        sent_texts = set(getattr(self, "_sent_texts", {}).get(conv_id, set()))
                        for dm in await MessageService.get_recent_messages(conv_id, limit=30):
                            if dm["role"] == "outgoing":
                                sent_texts.add(self._norm_text(dm["content"]))

                        any_saved = False
                        # An "incoming" bubble whose text we already sent is our own
                        # message that was mislabelled; treat it as outgoing so we
                        # never answer ourselves. Unknown-owner bubbles are never stored.
                        for msg in msgs:
                            if msg["role"] == "incoming" and self._norm_text(msg["content"]) in sent_texts:
                                msg["role"] = "outgoing"
                                msg["sender"] = "You"
                        for msg in msgs:
                            if msg["role"] == "unknown":
                                continue
                            saved = await MessageService.save_message_if_new(
                                conversation_id=msg["conversation_id"],
                                match_id=msg["match_id"],
                                sender=msg["sender"],
                                role=msg["role"],
                                content=msg["content"],
                                message_hash=msg["message_hash"],
                                status="IGNORED" if first_visit or mode == "OFF" else "NEW",
                            )
                            any_saved = any_saved or saved is not None

                        self._history_backfilled.add(conv_id)
                        self._unread_conversations.discard(conv_id)

                        # Determine who owes the next reply from message order, not
                        # from Tinder's unreliable unread indicator. Walk backward
                        # from the newest bubble until our last outgoing bubble.
                        incoming_tail: list[dict] = []
                        owner_unclear = False
                        for msg in reversed(msgs):
                            if msg["role"] == "outgoing":
                                break
                            if msg["role"] == "unknown":
                                owner_unclear = True
                                break
                            incoming_tail.append(msg)
                        incoming_tail.reverse()
                        if owner_unclear:
                            # Cannot tell who sent the newest bubble: do not guess, WAIT.
                            logger.warning(
                                f"Không xác định được người gửi tin mới nhất của {match_name}; bỏ qua lượt này (WAIT)."
                            )
                            incoming_tail = []

                        if mode in ("AUTO", "SUGGEST") and incoming_tail:
                            hashes = [msg["message_hash"] for msg in incoming_tail]
                            statuses = await MessageService.get_statuses_by_hashes(hashes)
                            pending_tail = [
                                msg for msg in incoming_tail
                                if statuses.get(msg["message_hash"]) in ("IGNORED", "NEW", "FAILED")
                                and msg["message_hash"] not in self._queued_message_hashes
                            ]
                            if pending_tail and self._reserve_conversation_turn(conv_id, match_name):
                                pending_hashes = [msg["message_hash"] for msg in pending_tail]
                                queued_successfully = False
                                try:
                                    self._queued_message_hashes.update(pending_hashes)
                                    await MessageService.update_messages_status(pending_hashes, "NEW")
                                    logger.info(
                                        f"💬 {match_name} đang chờ phản hồi ({len(pending_tail)} tin cuối), "
                                        "giữ nguyên hội thoại này đến khi gửi xong."
                                    )
                                    for msg in pending_tail:
                                        await self.conv_manager.receive_message(
                                            conversation_id=conv_id,
                                            match_id=conv_id,
                                            match_name=match_name,
                                            sender=match_name,
                                            content=msg["content"],
                                            message_hash=msg["message_hash"],
                                            mode=mode,
                                        )
                                    queued_successfully = True
                                finally:
                                    if not queued_successfully:
                                        self._queued_message_hashes.difference_update(pending_hashes)
                                        self._release_conversation_turn(conv_id)
                        elif mode == "OFF" and any_saved:
                            logger.info(
                                f"Match {match_name} đang OFF; chỉ đồng bộ lịch sử, không phản hồi."
                            )

                        if any_saved and self.window.reply_panel.current_conversation_id == conv_id:
                            recent_msgs = await MessageService.get_recent_messages(conv_id)
                            self.window.conversation_panel.display_messages(recent_msgs)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"Message monitor iteration failed; incoming messages may not be auto-replied: {e}",
                    exc_info=True,
                )

            await asyncio.sleep(self.settings.scanner.message_scan_interval or 3.0)

    async def handle_login(self):
        """Bring browser to front and initiate manual login flow."""
        logger.info("User clicked Login.")
        self.window.status_bar.showMessage("Đang mở trình duyệt để đăng nhập Tinder...")
        try:
            page = await self.browser_mgr.open_or_focus()
            self.sender = MessageSender(page)
            self.scanner = MatchScanner(page)

            is_logged_in = await self.browser_mgr.check_login_status()
            if is_logged_in:
                self.window.set_tinder_status(True, "Connected")
                self.window.status_bar.showMessage("Tài khoản Tinder đã đăng nhập sẵn!")
                await self.on_logged_in()
            else:
                self.window.set_tinder_status(False, "Waiting Login")
                self.window.status_bar.showMessage("Vui lòng đăng nhập trên cửa sổ trình duyệt...")
                asyncio.create_task(self._poll_for_login())
        except Exception as e:
            logger.error(f"Error opening browser for login: {e}")
            self.window.status_bar.showMessage(f"Lỗi mở trình duyệt: {e}")

    async def handle_logout(self):
        """Log out of current Tinder session and clear cache."""
        confirm = QMessageBox.question(
            self.window,
            "Xác nhận đăng xuất",
            "Bạn có chắc muốn đăng xuất khỏi tài khoản Tinder hiện tại?\n\nPhiên đăng nhập trên trình duyệt sẽ được xóa.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        logger.info("User confirmed logout.")
        self.window.status_bar.showMessage("Đang đăng xuất khỏi Tinder...")

        # Stop background tasks
        if self._scanner_task and not self._scanner_task.done():
            self._scanner_task.cancel()
            self._scanner_task = None
        if self._opener_task and not self._opener_task.done():
            self._opener_task.cancel()
            self._opener_task = None

        # Execute browser logout
        await self.browser_mgr.logout()

        # Update GUI
        self.window.set_tinder_status(False, "Đã đăng xuất")
        self.window.matches_panel.clear_matches()
        self.window.conversation_panel.clear_conversation()
        self.window.reply_panel.clear_suggestion()
        self.window.status_bar.showMessage("Đã đăng xuất khỏi Tinder. Bấm 'Đăng nhập' để đăng nhập tài khoản khác.")

        QMessageBox.information(
            self.window,
            "Đã đăng xuất",
            "Đã đăng xuất thành công khỏi Tinder!\n\nBạn có thể đăng nhập tài khoản mới ngay trên cửa sổ trình duyệt."
        )

    async def handle_switch_account(self, account_id: str):
        """Switch active account profile, restart browser, and rescan matches."""
        current_acc = AccountService.get_active_account()
        if current_acc.get("id") == account_id and self.browser_mgr.is_running:
            return

        acc = AccountService.get_account_by_id(account_id)
        if not acc:
            logger.warning(f"Account {account_id} not found.")
            return

        logger.info(f"Switching account to: {acc['name']} ({acc['profile_dir']})...")
        self.window.status_bar.showMessage(f"Đang chuyển sang tài khoản: {acc['name']}...")

        # 1. Stop background loops
        if self._scanner_task and not self._scanner_task.done():
            self._scanner_task.cancel()
            self._scanner_task = None
        if self._opener_task and not self._opener_task.done():
            self._opener_task.cancel()
            self._opener_task = None

        # 2. Clear GUI panels
        self.window.matches_panel.clear_matches()
        self.window.conversation_panel.clear_conversation()
        self.window.reply_panel.clear_suggestion()
        self.window.set_tinder_status(False, "Đang đổi nick...")

        # 3. Save active account in config
        AccountService.set_active_account(account_id)
        self.window.refresh_accounts()

        # 4. Restart browser with target profile directory
        try:
            page = await self.browser_mgr.restart_with_profile(acc["profile_dir"])
            self.sender = MessageSender(page)
            self.scanner = MatchScanner(page)

            # 5. Check login status of new profile
            is_logged_in = await self.browser_mgr.check_login_status()
            if is_logged_in:
                self.window.set_tinder_status(True, "Connected")
                self.window.status_bar.showMessage(f"Đã kết nối tài khoản: {acc['name']}")
                await self.on_logged_in()
            else:
                self.window.set_tinder_status(False, "Waiting Login")
                self.window.status_bar.showMessage(f"Tài khoản '{acc['name']}' chưa đăng nhập. Vui lòng đăng nhập trên trình duyệt...")
                asyncio.create_task(self._poll_for_login())
        except Exception as e:
            logger.error(f"Error switching account to {acc['name']}: {e}")
            self.window.set_tinder_status(False, "Error")
            self.window.status_bar.showMessage(f"Lỗi khi chuyển tài khoản: {e}")

    async def handle_add_account(self):
        """Prompt to create a new account profile and switch to it."""
        name, ok = QInputDialog.getText(
            self.window,
            "Thêm tài khoản Tinder mới",
            "Nhập tên gợi nhớ cho tài khoản mới (ví dụ: Nick 2, Nick Bida, v.v.):"
        )
        if not ok or not name.strip():
            return

        clean_name = name.strip()
        new_acc = AccountService.add_account(clean_name)
        logger.info(f"Created new account profile: {new_acc}")
        self.window.refresh_accounts()

        # Automatically switch to the newly created account profile
        await self.handle_switch_account(new_acc["id"])

    async def shutdown(self):
        """Clean shutdown of all background threads and browser."""
        self._is_running = False
        if self._scanner_task and not self._scanner_task.done():
            self._scanner_task.cancel()
        if self._opener_task and not self._opener_task.done():
            self._opener_task.cancel()
        if self._msg_monitor_task and not self._msg_monitor_task.done():
            self._msg_monitor_task.cancel()
        self.conv_manager.stop_all()
        await self.browser_mgr.close()
        logger.info("Application controller shutdown complete.")


async def main():
    settings = get_settings()
    logger.info("Starting Tinder AI Assistant Desktop...")

    window = MainWindow()
    controller = TinderAppController(window)
    await controller.initialize()

    # If INSPECT_DOM is true, start browser session
    if settings.inspect_dom:
        await controller.start_browser()

    window.show()

    # Keep async loop running until window closed
    close_event = asyncio.Event()
    window.destroyed.connect(lambda: close_event.set())
    await close_event.wait()

    await controller.shutdown()


def run():
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    sleep_preventer.prevent_sleep()
    try:
        with loop:
            loop.run_until_complete(main())
    finally:
        sleep_preventer.allow_sleep()


if __name__ == "__main__":
    run()
