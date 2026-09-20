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
from ai.classifier import IntentClassifier, IntentCategory
from services.match_service import MatchService
from services.message_service import MessageService
from services.reply_service import ReplyService
from services.account_service import AccountService
from utils.logger import logger


class TinderAppController:
    """Master controller orchestrating GUI, background scanner tasks, and AI pipelines."""

    def __init__(self, window: MainWindow):
        self.window = window
        self.settings = get_settings()
        self.browser_mgr = BrowserManager()
        self.tinder_browser = TinderBrowser(self.browser_mgr)
        self.llm_client = LLMClient()
        self.ai_generator = ResponseGenerator(self.llm_client)
        
        # Conversation manager with async AI handler callback
        self.conv_manager = ConversationManager(ai_handler=self.on_bundled_messages_ready)
        
        self.sender: MessageSender | None = None
        self.scanner: MatchScanner | None = None
        self._scanner_task: asyncio.Task | None = None
        self._opener_task: asyncio.Task | None = None
        self._msg_monitor_task: asyncio.Task | None = None
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
        self.window.matches_panel.batch_mode_updated.connect(
            lambda mode: asyncio.create_task(self.handle_batch_mode_update(mode))
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
            self.sender = MessageSender(page)
            self.scanner = MatchScanner(page)

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

            # Automatically run auto-opener in background for new matches
            if self.settings.global_auto_reply:
                self._opener_task = asyncio.create_task(self._auto_opener_background_loop())

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

        # Automatically open and process unread messages for AUTO matches
        for m in matches:
            tinder_id = m.get("tinder_id")
            if (
                m.get("has_unread") and self.settings.global_auto_reply and not self.settings.is_paused
                and not getattr(self, "_swiping", False)
            ):
                mode = await MatchService.get_mode(tinder_id)
                if mode == "AUTO" and self.browser_mgr.page and not self.browser_mgr.page.is_closed():
                    current_url = self.browser_mgr.page.url or ""
                    if tinder_id not in current_url:
                        logger.info(f"🔔 Phát hiện tin nhắn mới chưa đọc từ {m.get('name')} ({tinder_id[:8]}...). Đang mở chat...")
                        try:
                            await self.browser_mgr.page.goto(f"https://tinder.com/app/messages/{tinder_id}", wait_until="networkidle", timeout=15000)
                            break
                        except Exception as e:
                            logger.warning(f"Error opening unread chat {tinder_id}: {e}")

        # Automatic cleanup: if someone was unmatched on Tinder, clean them from DB and UI
        active_ids = {m["tinder_id"] for m in matches}
        if len(active_ids) > 0:
            removed_ids = await MatchService.cleanup_unmatched(active_ids)
            for rid in removed_ids:
                self.window.matches_panel.remove_match(rid)

    async def on_bundled_messages_ready(self, state: ConversationState, bundled_messages: list[str]):
        """Triggered after debounce expires when messages are ready for AI processing."""
        logger.info(f"Processing AI reply for {state.match_name} ({len(bundled_messages)} messages)")

        # Load full two-way history (incl. our own messages) so the reply follows the real conversation
        try:
            db_msgs = await MessageService.get_recent_messages(state.conversation_id, limit=20)
            history = [{"sender": m["sender"], "content": m["content"]} for m in db_msgs]
            n = len(bundled_messages)
            if n and [h["content"] for h in history[-n:]] == list(bundled_messages):
                history = history[:-n]
            state.history = history
        except Exception as e:
            logger.debug(f"Could not load DB history: {e}")

        reply_text, is_safe_for_auto, intent = await self.ai_generator.generate_response(
            state, bundled_messages
        )

        # Save AI reply to DB
        reply_id = await ReplyService.record_reply(
            conversation_id=state.conversation_id,
            input_text=" \n ".join(bundled_messages),
            output_text=reply_text,
            status="GENERATED"
        )

        # Update GUI if this is the currently viewed conversation
        if self.window.reply_panel.current_conversation_id == state.conversation_id:
            self.window.reply_panel.set_suggestion(state.conversation_id, reply_text)

        # AUTO mode execution criteria
        can_auto_send = (
            state.mode == "AUTO"
            and not self.settings.dry_run
            and self.settings.global_auto_reply
            and not self.settings.is_paused
            and not self.settings.emergency_stop
            and is_safe_for_auto
        )

        if can_auto_send and self.sender:
            logger.info(f"Auto-dispatching reply to {state.match_name}...")
            sent = await self.sender.send_reply(state.conversation_id, reply_text, is_auto=True)
            if sent:
                await ReplyService.mark_sent(reply_id)
                await self._remember_sent(state.conversation_id, reply_text)
        else:
            logger.info(f"Reply presented as suggestion in GUI for {state.match_name} (Mode={state.mode})")

        # Check if conversation wrap-up / goodnight / busy / text later -> auto transition to OFF
        combined_text = " ".join(bundled_messages)
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
            reply_text, _, _ = await self.ai_generator.generate_response(state, [last_msg])
            self.window.reply_panel.set_suggestion(conversation_id, reply_text, "Regenerated")

    async def handle_mode_update(self, tinder_id: str, mode: str):
        await MatchService.set_mode(tinder_id, mode)
        self.conv_manager.set_mode(tinder_id, mode)

    async def handle_batch_mode_update(self, mode: str):
        """Batch update mode across all matches in database and runtime memory."""
        logger.info(f"Applying batch mode '{mode}' to all matches...")
        await MatchService.set_all_modes(mode)
        self.conv_manager.set_all_modes(mode)
        count = len(self.window.matches_panel._items_map)
        msg = f"⚡ Đã chuyển toàn bộ {count} cuộc trò chuyện sang chế độ {mode}."
        self.window.status_bar.showMessage(msg, 6000)
        logger.info(msg)

    async def handle_match_selected(self, tinder_id: str):
        state = self.conv_manager.get_state(tinder_id)
        if state:
            self.window.conversation_panel.display_profile(
                name=state.match_name,
                age=state.profile.get("age"),
                bio=state.profile.get("bio"),
                interests=state.profile.get("interests")
            )
            recent_msgs = await MessageService.get_recent_messages(tinder_id)
            self.window.conversation_panel.display_messages(recent_msgs)
            self.window.reply_panel.current_conversation_id = tinder_id

    async def handle_auto_swipe(self):
        """Trigger auto-liking on recs until likes run out."""
        if not self.browser_mgr.page or self.browser_mgr.page.is_closed():
            logger.warning("Browser is not active for auto-swipe.")
            return
        if getattr(self, "_swiping", False):
            logger.info("Auto-like is already running.")
            return
        from browser.auto_swipe import AutoSwipeEngine
        engine = AutoSwipeEngine(self.browser_mgr.page)
        self.window.status_bar.showMessage("Đang tự động like thẻ cho đến khi hết lượt...")
        self._swiping = True
        try:
            results = await engine.run(max_swipes=150)
        finally:
            self._swiping = False
        self.window.status_bar.showMessage(
            f"Hoàn tất quẹt: Đã like {results['swiped']}, Matches mới: {results['matches']}"
        )

    async def handle_auto_opener(self):
        """Trigger reading profile and sending subtle flirty openers to new matches."""
        if not self.browser_mgr.page or self.browser_mgr.page.is_closed():
            logger.warning("Browser is not active for auto-opener.")
            return
        if getattr(self, "_swiping", False):
            self.window.status_bar.showMessage("Đang auto-like, hãy chờ xong rồi mới thả thính.", 6000)
            return
        from browser.match_opener import MatchOpenerEngine
        from services.opener_service import OpenerService
        engine = MatchOpenerEngine(self.browser_mgr.page, OpenerService(self.llm_client))
        self.window.status_bar.showMessage("Đang tự động mở lời (thả thính nhẹ) cho các match mới...")
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
                ):
                    from browser.match_opener import MatchOpenerEngine
                    from services.opener_service import OpenerService
                    engine = MatchOpenerEngine(self.browser_mgr.page, OpenerService(self.llm_client))
                    self.window.status_bar.showMessage("💌 Đang tự động mở lời (thả thính) cho các match mới...")
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
                    import re
                    current_url = self.browser_mgr.page.url or ""
                    m = re.search(r"/app/messages/([a-zA-Z0-9_\-]+)", current_url)
                    if m:
                        conv_id = m.group(1)
                        detector = MessageDetector(self.browser_mgr.page)
                        mode = await MatchService.get_mode(conv_id)
                        state = await self.conv_manager.get_or_create_state(
                            conv_id, conv_id, "Match", mode=mode
                        )
                        match_name = state.match_name if state.match_name != "Match" else "Match"

                        msgs = await detector.detect_messages_in_current_chat(
                            conv_id, conv_id, match_name
                        )
                        sent_texts = getattr(self, "_sent_texts", {}).get(conv_id, set())
                        for msg in msgs:
                            if msg["role"] == "incoming" and self._norm_text(msg["content"]) in sent_texts:
                                continue
                            saved = await MessageService.save_message_if_new(
                                conversation_id=msg["conversation_id"],
                                match_id=msg["match_id"],
                                sender=msg["sender"],
                                role=msg["role"],
                                content=msg["content"],
                                message_hash=msg["message_hash"]
                            )
                            if saved and msg["role"] == "incoming":
                                logger.info(
                                    f"💬 Phát hiện tin nhắn mới từ {msg['sender']} ({conv_id[:8]}...): \"{msg['content']}\""
                                )
                                await self.conv_manager.receive_message(
                                    conversation_id=conv_id,
                                    match_id=conv_id,
                                    match_name=msg["sender"],
                                    sender=msg["sender"],
                                    content=msg["content"]
                                )
                                if self.window.reply_panel.current_conversation_id == conv_id:
                                    recent_msgs = await MessageService.get_recent_messages(conv_id)
                                    self.window.conversation_panel.display_messages(recent_msgs)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Message monitor loop iteration notice: {e}")

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
    with loop:
        loop.run_until_complete(main())


if __name__ == "__main__":
    run()
