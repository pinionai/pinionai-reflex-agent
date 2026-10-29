__lazy_modules__ = {
    "pinionai.file_type_detection",
}

import reflex as rx
import asyncio
import base64
import binascii
import os
import time
from pinionai import AsyncPinionAIClient
from pinionai.file_type_detection import is_text_file_type
from pinionai.exceptions import PinionAIConfigurationError, PinionAIError
from .agent_selection import get_available_agents, merge_agent_capabilities, switch_agent_capabilities

# Pinion clients contain CFFI handles and must stay outside serialized Reflex state.
_CLIENTS_BY_TOKEN: dict[str, AsyncPinionAIClient] = {}

class AppState(rx.State):
    """The central state engine managing the full application context and asynchronous network loops."""

    # --- UI & Meta Variables ---
    agent_title: str = "Thinking..."
    agent_subtitle: str = "Loading your AI assistant..."
    accent_color: str = "teal"
    agentlist_mode: bool = os.environ.get("AGENTLIST_MODE", "true").lower() in ("true", "1", "yes")
    locale: str = "en"
    language: str = "en"
    current_stock: str = ""
    assistant_img: str = "/IconCircle144.png"
    user_img: str = ""
    status_message: str = "Ready"
    connection_status: str = "AI Mode Active"

    # --- Flow Control Toggles (Replaces st.session_state flags) ---
    awaiting_key_secret: bool = False
    merging_aia: bool = False
    switching_aia: bool = False
    is_merging: bool = False
    aia_mode: str = "start"
    end_chat_clicked: bool = False
    transfer_allowed: bool = True
    is_live_agent_mode: bool = False
    is_thinking: bool = False

    # --- Active Input Context Trackers ---
    secret_key: str = ""
    chat_messages: list[dict[str, str]] = []
    available_agents: list[dict[str, str]] = []
    selected_agent_uid: str = ""
    agent_list_error: str = ""
    agent_selection_status: str = ""

    # --- Audio Engine Variable Bindings (STT / TTS) ---
    is_processing_audio: bool = False
    is_recording_audio: bool = False
    is_generating_audio: bool = False
    audio_file: str = ""  # Filename inside rx.get_upload_dir(), served via rx.get_upload_url()
    stt_enabled: bool = False  # Tracked dynamically by agent var metadata
    tts_enabled: bool = False  # Tracked dynamically by agent var metadata

    # --- Private Session Data ---
    _saved_file_content: str = ""
    _audio_counter: int = 0
    _listening_task_active: bool = False

    @property
    def _client(self) -> AsyncPinionAIClient | None:
        """Return this browser session's client without storing it in serializable state."""
        return _CLIENTS_BY_TOKEN.get(self.router.session.client_token)

    @_client.setter
    def _client(self, client: AsyncPinionAIClient | None) -> None:
        token = self.router.session.client_token
        if client is None:
            _CLIENTS_BY_TOKEN.pop(token, None)
        else:
            _CLIENTS_BY_TOKEN[token] = client

    def get_url_params(self) -> dict[str, str] | str | None:
        """Extract URL parameters from router query parameters or fallback environment variable."""
        try:
            params = dict(self.router.url.query_parameters)
            if params:
                return params
        except Exception:
            pass

        try:
            query_str = self.router.url.query
            if query_str:
                return query_str
        except Exception:
            pass

        # Fallback to environment variable (for testing/CLI-style deployments)
        env_params = os.environ.get("URL_PARAMS") or os.environ.get("url_params")
        if env_params:
            return env_params

        # Fallback to page params if present
        try:
            raw_page = getattr(self.router, "_page", None)
            if raw_page and getattr(raw_page, "params", None):
                return dict(raw_page.params)
        except Exception:
            pass

        return None

    @rx.var
    def url_params(self) -> dict[str, str]:
        """Expose current URL query parameters as a reactive dictionary."""
        params = self.get_url_params()
        if isinstance(params, dict):
            return params
        if isinstance(params, str):
            from pinionai.client import _parse_url_params
            return _parse_url_params(params)
        return {}

    @rx.var
    def current_page_url(self) -> str:
        """The current page URL including query parameters."""
        try:
            path = self.router.url.path or "/"
            query = self.router.url.query
            if query:
                return f"{path}?{query}"
            return path
        except Exception:
            return "/"

    async def on_init(self):
        """Runs automatically when a user opens the application layout page."""
        # Clean down structural triggers
        self.end_chat_clicked = False
        self.is_thinking = False
        self.is_recording_audio = False

        # Read URL params for agentlist_mode, locale/language, stock
        params = self.get_url_params()
        if isinstance(params, dict):
            if "agentlist_mode" in params:
                self.agentlist_mode = str(params["agentlist_mode"]).lower() in ("true", "1", "yes")
            raw_lang = params.get("language") or params.get("lang") or params.get("locale")
            if raw_lang:
                self.locale = str(raw_lang).strip().lower()
                self.language = self.locale
            if "stock" in params:
                self.current_stock = str(params["stock"]).strip().upper()

        if self.locale == "en":
            env_lang = os.environ.get("LANGUAGE") or os.environ.get("language")
            if env_lang:
                self.locale = env_lang.strip().lower()
                self.language = self.locale

        await self._ensure_client()
        client = self._client
        if client is not None:
            if self.language and self.language != "en":
                client.var["user_language"] = self.language
            elif client.var.get("user_language"):
                self.language = client.var["user_language"]
                self.locale = self.language
            self.sync_agent_ui_variables()
            if self.agentlist_mode:
                await self._load_available_agents(client)
            self._ensure_initial_greeting()

    def set_language(self, lang: str):
        """Sets the active translation language."""
        self.language = lang.strip().lower()
        self.locale = self.language
        client = self._client
        if client is not None:
            client.var["user_language"] = self.language

    def _ensure_initial_greeting(self):
        """Sets up context-aware onboarding greeting if chat history is empty."""
        client = self._client
        if client is None:
            return
        if client.chat_messages:
            self._refresh_messages()
            return

        is_es = self.locale.startswith("es") or self.language.startswith("es")
        if self.current_stock:
            if is_es:
                msg = f"¡Hola! Soy tu Asistente de CityAuto. Veo que estás viendo el vehículo #{self.current_stock}. ¿Te gustaría consultar opciones de financiamiento, la inspección de 150 puntos o calcular el precio total?"
            else:
                msg = f"Hello! I am your CityAuto Assistant. I see you are looking at vehicle stock #{self.current_stock}. Would you like to check financing estimates, view the 150-point inspection results, or calculate your out-the-door price?"
        else:
            if is_es:
                msg = "¡Hola! Bienvenido a CityAuto. ¿En qué puedo ayudarte hoy? Puedes pedirme buscar inventario, verificar términos de financiamiento, calcular precios finales o consultar horarios de nuestras tiendas."
            else:
                msg = "Hello! Welcome to CityAuto. How can I help you today? Ask me to search our live inventory, estimate financing, calculate out-the-door pricing, or check store hours."

        client.add_message_to_history("assistant", msg)
        self._refresh_messages()

    async def _ensure_client(self) -> bool:
        """Creates the env-configured client if this session does not have one yet.

        The client lives only in this worker's memory (it cannot be pickled), so it
        can be missing after a backend restart or when a websocket reconnects to a
        different worker. Recreate it lazily instead of silently dropping messages.
        """
        if self._client is not None:
            if self.status_message.startswith("Failed to initialize"):
                self.status_message = "Ready"
            return True
        available_uids = {agent["uid"] for agent in self.available_agents}
        agent_id = (
            self.selected_agent_uid
            if self.selected_agent_uid in available_uids
            else os.environ.get("agent_id")
        )
        if not agent_id:
            self.status_message = "No agent_id configured. Upload an .aia file to load an agent."
            return False
        try:
            self._client = await AsyncPinionAIClient.create(
                agent_id=agent_id,
                host_url=os.environ.get("host_url"),
                client_id=os.environ.get("client_id"),
                client_secret=os.environ.get("client_secret"),
                version=os.environ.get("version") or None,
                url_params=self.get_url_params(),
            )
            self.status_message = "Ready"
            return True
        except PinionAIConfigurationError as e:
            self.status_message = f"Failed to initialize configuration: {e}"
        except Exception as e:
            self.status_message = f"Failed to initialize PinionAI client: {e}"
        return False

    async def _load_available_agents(self, client: AsyncPinionAIClient) -> None:
        """Load account agents and keep the configured or active agent selected."""
        try:
            agents = await get_available_agents(client)
            self.available_agents = [
                {"uid": str(agent["uid"]), "agent_name": str(agent["agent_name"])}
                for agent in agents
            ]
            self.agent_list_error = ""
            available_uids = {agent["uid"] for agent in self.available_agents}
            active_agent_uid = getattr(client, "_agent_id", None)
            configured_agent_uid = os.environ.get("agent_id")
            if self.selected_agent_uid not in available_uids:
                self.selected_agent_uid = next(
                    (
                        candidate
                        for candidate in (configured_agent_uid, active_agent_uid)
                        if candidate in available_uids
                    ),
                    self.available_agents[0]["uid"] if self.available_agents else "",
                )
        except Exception as e:
            self.available_agents = []
            self.selected_agent_uid = ""
            self.agent_list_error = str(e)

    @rx.event
    def select_available_agent(self, agent_uid: str):
        """Update the selected account agent."""
        self.selected_agent_uid = agent_uid
        self.agent_selection_status = ""

    @rx.event
    async def refresh_available_agents(self):
        """Retry loading the account's available agents."""
        if not await self._ensure_client():
            self.agent_list_error = self.status_message
            return
        client = self._client
        if client is not None:
            await self._load_available_agents(client)

    @rx.event
    async def load_selected_agent(self):
        """Replace the current chat client with the selected account agent."""
        selected_uid = self.selected_agent_uid
        selected_agent = next(
            (agent for agent in self.available_agents if agent["uid"] == selected_uid),
            None,
        )
        if selected_agent is None:
            self.agent_selection_status = "Select an available agent before loading."
            return

        current_client = self._client
        if current_client is not None and getattr(current_client, "_agent_id", None) == selected_uid:
            self.agent_selection_status = f"{selected_agent['agent_name']} is already loaded."
            return

        try:
            new_client = await AsyncPinionAIClient.create(
                agent_id=selected_uid,
                host_url=os.environ.get("host_url"),
                client_id=os.environ.get("client_id"),
                client_secret=os.environ.get("client_secret"),
                version=os.environ.get("version") or None,
                url_params=self.get_url_params(),
            )
            if not new_client.chat_messages and new_client.var.get("agentStart"):
                new_client.add_message_to_history(
                    "assistant", new_client.var["agentStart"]
                )
            if current_client is not None:
                if self.is_live_agent_mode:
                    await current_client.end_grpc_chat_session()
                await current_client.close()

            self._client = new_client
            self.is_live_agent_mode = False
            self.end_chat_clicked = False
            self.connection_status = "AI Mode Active"
            self.status_message = "Ready"
            self.sync_agent_ui_variables()
            self.agent_selection_status = f"Loaded agent: {selected_agent['agent_name']}."
        except Exception as e:
            self.agent_selection_status = f"Failed to load selected agent: {e}"

    @rx.event
    async def start_selected_agent(self):
        """Replace the current chat client with the selected account agent (fresh session)."""
        await self.load_selected_agent()

    @rx.event
    async def switch_selected_agent(self):
        """Switch to the selected account agent's behavior and intents while retaining current conversation variables."""
        client = self._client
        if client is None:
            self.agent_selection_status = "No active chat agent is available to switch."
            return

        selected_uid = self.selected_agent_uid
        selected_agent = next(
            (
                agent
                for agent in self.available_agents
                if agent["uid"] == selected_uid
            ),
            None,
        )
        if selected_agent is None:
            self.agent_selection_status = "Select an available agent before switching."
            return

        if getattr(client, "_agent_id", None) == selected_uid:
            self.agent_selection_status = f"{selected_agent['agent_name']} is already active."
            return

        try:
            await switch_agent_capabilities(
                client,
                selected_agent["uid"],
                host_url=os.environ.get("host_url"),
                client_id=os.environ.get("client_id"),
                client_secret=os.environ.get("client_secret"),
                version=os.environ.get("version") or None,
                url_params=self.get_url_params(),
            )
            self.sync_agent_ui_variables()
            self.agent_selection_status = (
                f"Switched to agent: {selected_agent['agent_name']}. Existing session variables preserved."
            )
        except Exception as e:
            self.agent_selection_status = f"Failed to switch selected agent: {e}"

    @rx.event
    async def merge_selected_agent(self):
        """Add the selected account agent's capabilities to the current chat."""
        client = self._client
        if client is None:
            self.agent_selection_status = "No active chat agent is available to merge into."
            return

        selected_agent = next(
            (
                agent
                for agent in self.available_agents
                if agent["uid"] == self.selected_agent_uid
            ),
            None,
        )
        if selected_agent is None:
            self.agent_selection_status = "Select an available agent before merging."
            return

        try:
            await merge_agent_capabilities(
                client,
                selected_agent["uid"],
                host_url=os.environ.get("host_url"),
                client_id=os.environ.get("client_id"),
                client_secret=os.environ.get("client_secret"),
                version=os.environ.get("version") or None,
                url_params=self.get_url_params(),
            )
            self.sync_agent_ui_variables()
            self.agent_selection_status = (
                f"Capabilities from {selected_agent['agent_name']} "
                "merged into the current session."
            )
        except Exception as e:
            self.agent_selection_status = f"Failed to merge selected agent: {e}"

    def _refresh_messages(self):
        """Copies the client's chat history into the frontend var.

        get_chat_messages_for_display() returns the client's own list, so take a
        copy rather than aliasing it into state.
        """
        client = self._client
        if client is None:
            return
        self.chat_messages = [
            {
                "role": str(m.get("role", "")),
                "content": str(m.get("content", "")),
                "file_type": str(m.get("file_type") or "text/plain"),
            }
            for m in client.get_chat_messages_for_display()
        ]

    def sync_agent_ui_variables(self):
        """Extracts dynamic presentation keys directly from the active Pinion Client layout dictionary."""
        client = self._client
        if client is None:
            return

        var = client.var
        self.agent_title = var.get("agentTitle") or "CityAuto Assistant"
        self.agent_subtitle = var.get("agentSubtitle") or (
            "Asistente de Compra y Soporte de CityAuto" if self.locale.startswith("es") else "Your CityAuto Car Buying & Support Guide"
        )
        self.accent_color = var.get("accentColor") or "teal"
        self.assistant_img = var.get("assistImage") or "/avatar.png"
        self.user_img = var.get("userImage") or self.user_img
        self.transfer_allowed = bool(var.get("transferAllowed", True))
        # These hold provider names (e.g. "pinionai stt whisper server") when enabled
        self.stt_enabled = bool(var.get("sttAudio"))
        self.tts_enabled = bool(var.get("ttsAudio"))

        # Inject standard onboarding greeting if history container is empty
        if not client.chat_messages and var.get("agentStart"):
            client.add_message_to_history("assistant", var["agentStart"])

        # Load the chat display cache array
        self._refresh_messages()

    # =========================================================================
    # --- File Upload & Merging Logic (Replaces StringIO / st.file_uploader) ---
    # =========================================================================

    async def handle_aia_upload(self, files: list[rx.UploadFile]):
        """Triggered instantly when an .aia agent configuration file object is uploaded."""
        if not files:
            return
        try:
            upload_file = files[0]
            file_bytes = await upload_file.read()
            self._saved_file_content = file_bytes.decode("utf-8")
            await self._execute_agent_action()
        except Exception as e:
            self.status_message = f"File reading sequence error: {str(e)}"

    def set_secret_key(self, value: str):
        self.secret_key = value

    async def submit_secret_key(self):
        """Invoked when unlocking private decryption payloads."""
        await self._execute_agent_action()

    async def _execute_agent_action(self):
        """Internal router calling PinionAI dependent on start, switch, or merge modes."""
        try:
            key = self.secret_key if self.secret_key else None

            if self.switching_aia or (self.aia_mode == "switch" and not self.awaiting_key_secret and not self.merging_aia):
                # --- CAPABILITIES SWITCH FLOW ---
                client = self._client
                if client is None:
                    self.status_message = "No active session to switch."
                    return
                result_msg = await client.switch_agent_from_aia(
                    file_stream=self._saved_file_content,
                    key_secret=key,
                )
                if result_msg == 'key_secret required for private version':
                    self.switching_aia = True
                    self.merging_aia = False
                    self.awaiting_key_secret = False
                elif "Error" not in result_msg:
                    self.reset_flow_states()
                    self.sync_agent_ui_variables()
                    self.status_message = result_msg
                else:
                    self.status_message = f"Switch error: {result_msg}"
            elif self.merging_aia or self.is_merging or self.aia_mode == "merge":
                # --- CAPABILITIES MERGE FLOW ---
                client = self._client
                if client is None:
                    self.status_message = "No active session to merge into."
                    return
                result_msg = await client.add_agent_from_aia(
                    file_stream=self._saved_file_content,
                    key_secret=key,
                )
                if result_msg == 'key_secret required for private version':
                    self.merging_aia = True
                    self.switching_aia = False
                    self.awaiting_key_secret = False
                elif "Error" not in result_msg:
                    self.reset_flow_states()
                    self.sync_agent_ui_variables()
                    self.status_message = result_msg
                else:
                    self.status_message = f"Merge error: {result_msg}"
            else:
                # --- FRESH INITIAL START FLOW ---
                client, init_message = await AsyncPinionAIClient.create_from_stream(
                    file_stream=self._saved_file_content,
                    host_url=os.environ.get("host_url"),
                    key_secret=key,
                    url_params=self.get_url_params(),
                )
                if init_message == 'key_secret required for private version':
                    self.awaiting_key_secret = True
                    self.merging_aia = False
                    self.switching_aia = False
                elif client:
                    previous_client = self._client
                    if previous_client is not None:
                        if self.is_live_agent_mode:
                            await previous_client.end_grpc_chat_session()
                        await previous_client.close()
                    self._client = client
                    self.is_live_agent_mode = False
                    self.end_chat_clicked = False
                    self.connection_status = "AI Mode Active"
                    self.reset_flow_states()
                    self.sync_agent_ui_variables()
                    self.status_message = "Agent loaded from file source successfully!"
                else:
                    self.status_message = f"Load configuration error: {init_message}"
        except Exception as e:
            self.status_message = f"Action wrapper failure: {str(e)}"

    def set_mode_start(self):
        self.aia_mode = "start"
        self.is_merging = False
        self.status_message = "Awaiting brand new agent profile configuration stream."

    def set_mode_load(self):
        self.set_mode_start()

    def set_mode_switch(self):
        self.aia_mode = "switch"
        self.is_merging = False
        self.status_message = "Awaiting agent profile configuration stream to switch behavior."

    def set_mode_merge(self):
        self.aia_mode = "merge"
        self.is_merging = True
        self.status_message = "Awaiting secondary capabilities extension stream."

    def reset_flow_states(self):
        self.awaiting_key_secret = False
        self.merging_aia = False
        self.switching_aia = False
        self.secret_key = ""
        self._saved_file_content = ""

    # =========================================================================
    # --- Live Routing & gRPC Multi-Threading Loops (Background Tasks) ---
    # =========================================================================

    async def _start_live_agent(self) -> bool:
        """Starts the gRPC listener (if needed) and switches the session into live-agent mode."""
        client = self._client
        if client is None:
            self.connection_status = "No active backend engine profile initialized."
            self.is_live_agent_mode = False
            return False
        if not client._grpc_stub:
            try:
                is_started = await client.start_grpc_client_listener(sender_id="user")
            except Exception as e:
                self.connection_status = f"gRPC listener trace error: {e}"
                self.is_live_agent_mode = False
                return False
            if not is_started:
                self.connection_status = "Could not reach live routing endpoint service."
                self.is_live_agent_mode = False
                return False
        self.is_live_agent_mode = True
        self.connection_status = "Connected to Live Human Agent"
        return True

    async def toggle_live_agent_mode(self):
        """Triggers the human client intercept handoff."""
        if self._client is None:
            yield rx.window_alert("No active backend engine profile initialized.")
            return

        self.connection_status = "Connecting to live agent server..."
        yield

        if await self._start_live_agent():
            # Safe parallel launch of continuous background daemon loop
            yield AppState.listen_to_grpc_updates

    @rx.event(background=True)
    async def listen_to_grpc_updates(self):
        """Replaces poll_for_updates(). Runs on backend context without choking user interaction loops."""
        async with self:
            if self._listening_task_active:
                return
            self._listening_task_active = True

        # Mirror poll_for_updates(): gRPC is the primary signal, HTTP is a slow fallback
        http_poll_start = 30
        http_poll_interval = 5
        next_http_poll_time = time.time() + http_poll_start

        while True:
            async with self:
                client_ref = self._client
                if not self.is_live_agent_mode or client_ref is None:
                    self._listening_task_active = False
                    break
                if len(client_ref.chat_messages) != len(self.chat_messages):
                    self._refresh_messages()
                # The listener clears transfer_requested when the human agent hands back to AI
                if not client_ref.transfer_requested and not client_ref._grpc_stub:
                    self.is_live_agent_mode = False
                    self.connection_status = "AI Mode Active"
                    self._listening_task_active = False
                    break
                last_http_time = client_ref.last_session_post_modified

            now = time.time()
            if now >= next_http_poll_time:
                next_http_poll_time = now + http_poll_interval
                try:
                    server_time, _ = await client_ref.get_latest_session_modification_time()
                    if server_time and server_time != last_http_time:
                        await client_ref.update_pinion_session()
                        async with self:
                            self._refresh_messages()
                except Exception as e:
                    print(f"Fallback thread check skipped: {e}")

            # Yield control back to server event loop (Prevents CPU busy-waiting)
            await asyncio.sleep(0.5)

    @rx.event
    async def end_live_session(self):
        """Safely cleans up live routing socket locks."""
        self.is_live_agent_mode = False
        self.connection_status = "AI Mode Active"
        client = self._client
        if client is not None:
            await client.end_grpc_chat_session()
        yield

    async def terminate_conversation(self):
        self.end_chat_clicked = True
        self.is_live_agent_mode = False
        self.connection_status = "Conversation Session Halted Permanently"
        client = self._client
        if client is not None:
            try:
                await client.end_grpc_chat_session()
            except Exception as e:
                print(f"end_grpc_chat_session failed: {e}")

    @rx.event
    async def restart_interface(self):
        """Reset conversation session and reinitialize client preserving active url_params."""
        self.end_chat_clicked = False
        self.is_live_agent_mode = False
        self.connection_status = "AI Mode Active"
        self.is_thinking = False
        self.is_recording_audio = False
        current = self._client
        if current is not None:
            try:
                if self.is_live_agent_mode:
                    await current.end_grpc_chat_session()
                await current.close()
            except Exception:
                pass
            self._client = None
        await self._ensure_client()
        client = self._client
        if client is not None:
            self.sync_agent_ui_variables()
            await self._load_available_agents(client)

    # =========================================================================
    # --- Conversational Dialog Core & Audio Processing Hooks (STT/TTS) ---
    # =========================================================================

    async def handle_text_submit(self, form_data_or_text: dict | str):
        """Receives, dispatches, and yields responses for conversational text entries."""
        if isinstance(form_data_or_text, dict):
            message = form_data_or_text.get("user_input_field", "")
        else:
            message = str(form_data_or_text or "")

        message = message.strip()
        if not message:
            return
        if not await self._ensure_client():
            yield rx.toast.error(self.status_message)
            return
        client = self._client
        if client is None:
            yield rx.toast.error("The chat client could not be restored. Please reload the page.")
            return

        # 1. Update text variables for immediate user rendering
        client.add_message_to_history("user", message)
        self._refresh_messages()
        self.is_thinking = not self.is_live_agent_mode
        yield rx.set_value("user_input_field", "") # Clears text panel box natively

        try:
            # 2. Routing Decision Fork
            if self.is_live_agent_mode:
                await client.update_pinion_session()
                await client.send_grpc_message(message)
                yield
                return

            # Standard conversational path
            active_lang = self.language or self.locale
            ai_response, ai_file_type = await client.process_user_input(
                message, sender="user", language=active_lang
            )
            self._refresh_messages()
            await client.update_pinion_session()
            if not ai_response:
                yield rx.toast.warning("The agent returned an empty response. Check the server log for model configuration errors.")
            yield

            # Fire TTS speaker tracking if feature is flagged active
            if self.tts_enabled and ai_response and is_text_file_type(ai_file_type):
                async for ev in self.generate_voice_response(ai_response):
                    yield ev

            # Keep popping inline structural intents if next_intent chains are nested active
            while client.next_intent:
                chained_response, chained_file_type = await client.process_user_input(
                    user_input="", sender="user", language=active_lang
                )
                self._refresh_messages()
                await client.update_pinion_session()
                yield
                if self.tts_enabled and chained_response and is_text_file_type(chained_file_type):
                    async for ev in self.generate_voice_response(chained_response):
                        yield ev

            # The AI flow may request a handoff to a human agent
            if client.transfer_requested and not self.is_live_agent_mode:
                self.is_thinking = False
                self.connection_status = "Transfer to live agent initiated... Waiting for agent to connect."
                yield
                if await self._start_live_agent():
                    yield AppState.listen_to_grpc_updates
        except PinionAIError as e:
            yield rx.toast.error(f"Error from PinionAI: {e}")
        except Exception as e:
            yield rx.toast.error(f"Unexpected error: {e}")
        finally:
            self.is_thinking = False

    async def handle_recording_result(self, result: str):
        """Handle browser microphone start/error results or a completed audio recording."""
        if result == "recording":
            self.is_recording_audio = True
            return

        self.is_recording_audio = False
        if result.startswith("error:"):
            yield rx.window_alert(result.removeprefix("error:"))
            return
        if not result.startswith("audio:"):
            yield rx.window_alert("The microphone did not return an audio recording.")
            return

        client = self._client
        if not self.stt_enabled or client is None:
            yield rx.window_alert("Voice input is unavailable for the current agent.")
            return

        try:
            audio_bytes = base64.b64decode(result.removeprefix("audio:"), validate=True)
        except (binascii.Error, ValueError) as e:
            yield rx.window_alert(f"Could not read the microphone recording: {e}")
            return
        if not audio_bytes:
            yield rx.window_alert("No audio was recorded. Please try again.")
            return

        self.is_processing_audio = True
        yield
        try:
            transcribed_text = await client.convert_audio_to_text(audio_bytes)
        except Exception as e:
            yield rx.window_alert(f"STT synthesis failure: {e}")
            return
        finally:
            self.is_processing_audio = False
        if not transcribed_text.strip():
            yield rx.toast.warning("No speech was recognized. Please try again.")
            return
        async for event in self.handle_text_submit(transcribed_text):
            yield event

    async def generate_voice_response(self, text_to_speak: str):
        """Generates voice synthesis data files and links them directly into visible layout objects."""
        client = self._client
        if not text_to_speak or client is None:
            return

        self.is_generating_audio = True
        yield

        try:
            audio_bytes = await client.convert_text_to_audio(text_to_speak)
            if not audio_bytes:
                return

            # Read structural identifier prefixes to pick file formatting types
            suffix = ".mp3"
            if audio_bytes.startswith(b"RIFF"):
                suffix = ".wav"
            elif audio_bytes.startswith(b"OggS"):
                suffix = ".ogg"
            self._audio_counter += 1
            # Runtime files go in the upload dir; assets/ is only bundled at build time
            filename = f"speak_{self.router.session.client_token}_{self._audio_counter}{suffix}"
            upload_dir = rx.get_upload_dir()
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / filename).write_bytes(audio_bytes)

            # Set audio asset file name; the page resolves it with rx.get_upload_url()
            self.audio_file = filename
        except Exception as e:
            print(f"TTS pipeline exception suppressed: {e}")
        finally:
            self.is_generating_audio = False
            yield
