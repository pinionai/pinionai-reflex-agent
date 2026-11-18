import os
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ["PYTEST_CURRENT_TEST"] = "1"

import reflex as rx
from reflex.istate.data import RouterData, PageData, ReflexURL
from reflex.istate.manager.token import StateToken

from pinion_reflex_agent.state import AppState
from pinion_reflex_agent.agent_selection import merge_agent_capabilities, switch_agent_capabilities
from pinion_reflex_agent.pages import (
    create_pinion_client,
    create_pinion_client_from_stream,
    agent_selection_subpanel,
    aia_management_subpanel,
)


class TestUrlParamsSupport(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from reflex_base.registry import RegistrationContext
        ctx = RegistrationContext.ensure_context()
        try:
            _ = ctx.app
            RegistrationContext.set(ctx.fork())
        except Exception:
            pass
        cls.app = rx.App()

    async def asyncSetUp(self):
        from pinion_reflex_agent.state import _CLIENTS_BY_TOKEN
        _CLIENTS_BY_TOKEN.clear()
        self.token = StateToken(ident=f"test_token_{self._testMethodName}", cls=AppState)
        self.state = await self.app.state_manager.get_state(self.token)

    def test_get_url_params_from_query_parameters(self):
        """Verify get_url_params extracts dict from router.url.query_parameters."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com&table=12")
        )
        params = self.state.get_url_params()
        self.assertEqual(params, {"email": "alan@pinionai.com", "table": "12"})
        self.assertEqual(self.state.url_params, {"email": "alan@pinionai.com", "table": "12"})

    def test_get_url_params_from_raw_query(self):
        """Verify get_url_params extracts query string if parameters mapping is not present."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com&mode=active")
        )
        params = self.state.get_url_params()
        self.assertEqual(params, {"email": "alan@pinionai.com", "mode": "active"})
        self.assertEqual(self.state.url_params, {"email": "alan@pinionai.com", "mode": "active"})

    def test_get_url_params_from_page_params(self):
        """Verify get_url_params extracts from router._page.params if url components are empty."""
        self.state.router = RouterData(_page=PageData(params={"email": "alan@pinionai.com"}))

        params = self.state.get_url_params()
        self.assertEqual(params, {"email": "alan@pinionai.com"})
        self.assertEqual(self.state.url_params, {"email": "alan@pinionai.com"})

    def test_get_url_params_from_env_fallback(self):
        """Verify get_url_params falls back to environment variable URL_PARAMS when router is empty."""
        self.state.router = RouterData()
        with patch.dict(os.environ, {"URL_PARAMS": "?email=env@pinionai.com&table=9"}):
            params = self.state.get_url_params()
            self.assertEqual(params, "?email=env@pinionai.com&table=9")
            self.assertEqual(self.state.url_params, {"email": "env@pinionai.com", "table": "9"})

    def test_get_url_params_empty(self):
        """Verify get_url_params returns None and url_params returns empty dict when nothing is set."""
        self.state.router = RouterData()
        with patch.dict(os.environ, {}, clear=True):
            params = self.state.get_url_params()
            self.assertIsNone(params)
            self.assertEqual(self.state.url_params, {})

    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_ensure_client_passes_url_params(self, mock_client_create):
        """Verify _ensure_client passes url_params to AsyncPinionAIClient.create."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com")
        )
        fake_client = MagicMock()
        mock_client_create.return_value = fake_client

        with patch.dict(os.environ, {
            "agent_id": "test_agent_123",
            "host_url": "https://api.pinionai.com",
            "client_id": "cid_abc",
            "client_secret": "csec_xyz",
            "version": ""
        }):
            self.state._client = None
            success = await self.state._ensure_client()
            self.assertTrue(success)

            mock_client_create.assert_awaited_once_with(
                agent_id="test_agent_123",
                host_url="https://api.pinionai.com",
                client_id="cid_abc",
                client_secret="csec_xyz",
                version=None,
                url_params={"email": "alan@pinionai.com"}
            )

    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_load_selected_agent_passes_url_params(self, mock_client_create):
        """Verify load_selected_agent passes url_params when creating new client."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com&table=5")
        )
        fake_client = MagicMock()
        fake_client.chat_messages = []
        fake_client.var = {}
        mock_client_create.return_value = fake_client

        self.state.available_agents = [{"uid": "agent_target_456", "agent_name": "Target Agent"}]
        self.state.selected_agent_uid = "agent_target_456"

        with patch.dict(os.environ, {
            "host_url": "https://api.pinionai.com",
            "client_id": "cid_abc",
            "client_secret": "csec_xyz",
            "version": ""
        }):
            await self.state.load_selected_agent()

            mock_client_create.assert_awaited_once_with(
                agent_id="agent_target_456",
                host_url="https://api.pinionai.com",
                client_id="cid_abc",
                client_secret="csec_xyz",
                version=None,
                url_params={"email": "alan@pinionai.com", "table": "5"}
            )
            self.assertEqual(self.state.status_message, "Ready")

    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_ensure_client_resets_status_message_on_success(self, mock_client_create):
        """Verify _ensure_client resets status_message to Ready after a prior failure."""
        fake_client = MagicMock()
        mock_client_create.return_value = fake_client

        self.state.status_message = "Failed to initialize configuration: Network error"
        self.state._client = None

        with patch.dict(os.environ, {
            "agent_id": "test_agent_123",
            "host_url": "https://api.pinionai.com",
            "client_id": "cid_abc",
            "client_secret": "csec_xyz",
        }):
            success = await self.state._ensure_client()
            self.assertTrue(success)
            self.assertEqual(self.state.status_message, "Ready")

    async def test_ensure_client_clears_stale_error_when_client_already_active(self):
        """Verify _ensure_client resets stale failure status_message if client is already present."""
        self.state._client = MagicMock()
        self.state.status_message = "Failed to initialize configuration: Connection refused"

        success = await self.state._ensure_client()
        self.assertTrue(success)
        self.assertEqual(self.state.status_message, "Ready")

    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create_from_stream", new_callable=AsyncMock)
    async def test_execute_agent_action_load_passes_url_params(self, mock_create_from_stream):
        """Verify loading from .aia stream passes url_params to create_from_stream."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com")
        )
        fake_client = MagicMock()
        fake_client.var = {}
        mock_create_from_stream.return_value = (fake_client, "Loaded successfully")

        self.state.is_merging = False
        self.state._saved_file_content = "dummy_stream_content"
        self.state.secret_key = "dummy_key"

        with patch.dict(os.environ, {"host_url": "https://api.pinionai.com"}):
            await self.state._execute_agent_action()

            mock_create_from_stream.assert_awaited_once_with(
                file_stream="dummy_stream_content",
                host_url="https://api.pinionai.com",
                key_secret="dummy_key",
                url_params={"email": "alan@pinionai.com"}
            )

    @patch("pinion_reflex_agent.agent_selection.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_merge_agent_capabilities_passes_url_params(self, mock_client_create):
        """Verify merge_agent_capabilities forwards url_params to AsyncPinionAIClient.create."""
        mock_source = MagicMock()
        mock_source.get_pinionai_version_info = AsyncMock(return_value={"version": "1.0"})
        mock_source.close = AsyncMock()
        mock_client_create.return_value = mock_source

        mock_client = MagicMock()
        mock_client.merge_new_agent = AsyncMock(return_value="Merged")

        result = await merge_agent_capabilities(
            client=mock_client,
            agent_id="agent_to_merge",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec",
            version="live",
            url_params={"email": "alan@pinionai.com"}
        )
        self.assertEqual(result, "Merged")
        mock_client_create.assert_awaited_once_with(
            agent_id="agent_to_merge",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec",
            version="live",
            url_params={"email": "alan@pinionai.com"}
        )

    @patch("pinion_reflex_agent.pages.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_pages_create_pinion_client_with_url_params(self, mock_client_create):
        """Verify create_pinion_client helper in pages.py passes url_params."""
        mock_client_create.return_value = MagicMock()

        await create_pinion_client(
            agent_id="agent_123",
            url_params="?email=alan@pinionai.com",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec"
        )
        mock_client_create.assert_awaited_once_with(
            agent_id="agent_123",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec",
            version=None,
            url_params="?email=alan@pinionai.com"
        )

    @patch("pinion_reflex_agent.pages.AsyncPinionAIClient.create_from_stream", new_callable=AsyncMock)
    async def test_pages_create_pinion_client_from_stream_with_url_params(self, mock_stream_create):
        """Verify create_pinion_client_from_stream helper in pages.py passes url_params."""
        mock_stream_create.return_value = (MagicMock(), "Success")

        await create_pinion_client_from_stream(
            file_stream="stream_data",
            url_params={"email": "alan@pinionai.com"},
            host_url="https://api.pinionai.com"
        )
        mock_stream_create.assert_awaited_once_with(
            file_stream="stream_data",
            host_url="https://api.pinionai.com",
            key_secret=None,
            url_params={"email": "alan@pinionai.com"}
        )


    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_language_param_in_url_params(self, mock_create):
        """Verify language/lang query parameter sets locale and language in state."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?language=es")
        )
        fake_client = MagicMock()
        fake_client.chat_messages = []
        fake_client.var = {}
        mock_create.return_value = fake_client
        with patch.dict(os.environ, {
            "agent_id": "test_agent",
            "host_url": "https://api.pinionai.com",
            "client_id": "cid",
            "client_secret": "csec",
        }):
            self.state.agentlist_mode = False
            await self.state.on_init()
            self.assertEqual(self.state.language, "es")
            self.assertEqual(self.state.locale, "es")
            self.assertEqual(fake_client.var.get("user_language"), "es")

    @patch("pinion_reflex_agent.state.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_language_env_var_fallback(self, mock_create):
        """Verify LANGUAGE env var sets language and locale when URL has no language."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/")
        )
        fake_client = MagicMock()
        fake_client.chat_messages = []
        fake_client.var = {}
        mock_create.return_value = fake_client
        with patch.dict(os.environ, {
            "agent_id": "test_agent",
            "host_url": "https://api.pinionai.com",
            "client_id": "cid",
            "client_secret": "csec",
            "LANGUAGE": "fr",
        }):
            self.state.agentlist_mode = False
            await self.state.on_init()
            self.assertEqual(self.state.language, "fr")
            self.assertEqual(self.state.locale, "fr")
            self.assertEqual(fake_client.var.get("user_language"), "fr")

    def test_set_language_method(self):
        """Verify set_language updates state and client.var."""
        fake_client = MagicMock()
        fake_client.var = {}
        self.state._client = fake_client
        self.state.set_language("de")
        self.assertEqual(self.state.language, "de")
        self.assertEqual(self.state.locale, "de")
        self.assertEqual(fake_client.var.get("user_language"), "de")

    async def test_handle_text_submit_passes_language(self):
        """Verify handle_text_submit passes language to client.process_user_input."""
        fake_client = MagicMock()
        fake_client.process_user_input = AsyncMock(return_value=("Hola", "text/plain"))
        fake_client.update_pinion_session = AsyncMock()
        fake_client.transfer_requested = False
        fake_client.next_intent = None
        fake_client.chat_messages = []
        fake_client.var = {}

        self.state._client = fake_client
        self.state.language = "es"
        self.state.locale = "es"
        self.state.tts_enabled = False

        events = [ev async for ev in self.state.handle_text_submit("¿A qué hora abren?")]
        fake_client.process_user_input.assert_awaited_once_with(
            "¿A qué hora abren?", sender="user", language="es"
        )

    @patch("pinion_reflex_agent.agent_selection.AsyncPinionAIClient.create", new_callable=AsyncMock)
    async def test_switch_agent_capabilities_passes_url_params(self, mock_client_create):
        """Verify switch_agent_capabilities forwards url_params to AsyncPinionAIClient.create and calls client.switch_agent."""
        mock_source = MagicMock()
        mock_source.get_pinionai_version_info = AsyncMock(return_value={"version": "2.0"})
        mock_source.close = AsyncMock()
        mock_client_create.return_value = mock_source

        mock_client = MagicMock()
        mock_client.switch_agent = AsyncMock(return_value="Switched")

        result = await switch_agent_capabilities(
            client=mock_client,
            agent_id="agent_to_switch",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec",
            version="live",
            url_params={"email": "alan@pinionai.com"}
        )
        self.assertEqual(result, "Switched")
        mock_client_create.assert_awaited_once_with(
            agent_id="agent_to_switch",
            host_url="https://api.pinionai.com",
            client_id="cid",
            client_secret="csec",
            version="live",
            url_params={"email": "alan@pinionai.com"}
        )
        mock_client.switch_agent.assert_awaited_once_with({"version": "2.0"})

    @patch("pinion_reflex_agent.state.switch_agent_capabilities", new_callable=AsyncMock)
    async def test_switch_selected_agent(self, mock_switch):
        """Verify switch_selected_agent delegates to switch_agent_capabilities and updates state."""
        self.state.router = RouterData(
            url=ReflexURL("http://localhost:3000/?email=alan@pinionai.com")
        )
        fake_client = MagicMock()
        fake_client._agent_id = "agent_current"
        fake_client.var = {}
        fake_client.chat_messages = []
        self.state._client = fake_client

        self.state.available_agents = [
            {"uid": "agent_current", "agent_name": "Current Agent"},
            {"uid": "agent_new", "agent_name": "New Agent"},
        ]
        self.state.selected_agent_uid = "agent_new"

        with patch.dict(os.environ, {
            "host_url": "https://api.pinionai.com",
            "client_id": "cid",
            "client_secret": "csec",
            "version": "",
        }):
            await self.state.switch_selected_agent()
            mock_switch.assert_awaited_once_with(
                fake_client,
                "agent_new",
                host_url="https://api.pinionai.com",
                client_id="cid",
                client_secret="csec",
                version=None,
                url_params={"email": "alan@pinionai.com"},
            )
            self.assertIn("Switched to agent: New Agent", self.state.agent_selection_status)

    async def test_switch_selected_agent_already_active(self):
        """Verify switch_selected_agent informs user if agent is already active."""
        fake_client = MagicMock()
        fake_client._agent_id = "agent_active"
        self.state._client = fake_client

        self.state.available_agents = [{"uid": "agent_active", "agent_name": "Active Agent"}]
        self.state.selected_agent_uid = "agent_active"

        await self.state.switch_selected_agent()
        self.assertEqual(self.state.agent_selection_status, "Active Agent is already active.")

    async def test_switch_selected_agent_no_client(self):
        """Verify switch_selected_agent handles no client state."""
        self.state._client = None
        await self.state.switch_selected_agent()
        self.assertEqual(self.state.agent_selection_status, "No active chat agent is available to switch.")

    @patch.object(AppState, "load_selected_agent", new_callable=AsyncMock)
    async def test_start_selected_agent_calls_load(self, mock_load):
        """Verify start_selected_agent forwards to load_selected_agent."""
        await self.state.start_selected_agent()
        mock_load.assert_awaited_once()

    async def test_set_mode_methods(self):
        """Verify set_mode_start, set_mode_switch, and set_mode_merge update aia_mode and is_merging."""
        self.state.set_mode_start()
        self.assertEqual(self.state.aia_mode, "start")
        self.assertFalse(self.state.is_merging)

        self.state.set_mode_switch()
        self.assertEqual(self.state.aia_mode, "switch")
        self.assertFalse(self.state.is_merging)

        self.state.set_mode_merge()
        self.assertEqual(self.state.aia_mode, "merge")
        self.assertTrue(self.state.is_merging)

        self.state.set_mode_load()
        self.assertEqual(self.state.aia_mode, "start")
        self.assertFalse(self.state.is_merging)

    async def test_execute_agent_action_switch_aia_success(self):
        """Verify _execute_agent_action in switch mode calls switch_agent_from_aia."""
        fake_client = MagicMock()
        fake_client.switch_agent_from_aia = AsyncMock(return_value="Agent switched successfully!")
        fake_client.var = {}
        fake_client.chat_messages = []
        self.state._client = fake_client

        self.state.aia_mode = "switch"
        self.state._saved_file_content = "dummy_switch_file"
        self.state.secret_key = "test_key"

        await self.state._execute_agent_action()

        fake_client.switch_agent_from_aia.assert_awaited_once_with(
            file_stream="dummy_switch_file",
            key_secret="test_key",
        )
        self.assertEqual(self.state.status_message, "Agent switched successfully!")
        self.assertFalse(self.state.switching_aia)
        self.assertEqual(self.state.secret_key, "")

    async def test_execute_agent_action_switch_aia_key_required(self):
        """Verify _execute_agent_action sets switching_aia=True when private key is required."""
        fake_client = MagicMock()
        fake_client.switch_agent_from_aia = AsyncMock(
            return_value="key_secret required for private version"
        )
        self.state._client = fake_client

        self.state.aia_mode = "switch"
        self.state._saved_file_content = "encrypted_aia_content"
        self.state.secret_key = ""

        await self.state._execute_agent_action()

        self.assertTrue(self.state.switching_aia)
        self.assertFalse(self.state.merging_aia)
        self.assertFalse(self.state.awaiting_key_secret)

    async def test_execute_agent_action_switch_aia_unlock_flow(self):
        """Verify unlocking private AIA in switch mode calls switch_agent_from_aia with key."""
        fake_client = MagicMock()
        fake_client.switch_agent_from_aia = AsyncMock(return_value="Decrypted and switched!")
        fake_client.var = {}
        fake_client.chat_messages = []
        self.state._client = fake_client

        self.state.switching_aia = True
        self.state._saved_file_content = "encrypted_aia_content"
        self.state.set_secret_key("supersecret")

        await self.state.submit_secret_key()

        fake_client.switch_agent_from_aia.assert_awaited_once_with(
            file_stream="encrypted_aia_content",
            key_secret="supersecret",
        )
        self.assertFalse(self.state.switching_aia)
        self.assertEqual(self.state.status_message, "Decrypted and switched!")

    def test_render_subpanels(self):
        """Verify agent_selection_subpanel and aia_management_subpanel render correctly as Reflex components."""
        agent_sub = agent_selection_subpanel()
        self.assertIsNotNone(agent_sub)
        aia_sub = aia_management_subpanel()
        self.assertIsNotNone(aia_sub)

    def _make_legacy_client(self):
        from pinionai import AsyncPinionAIClient
        mock_client = MagicMock(spec=AsyncPinionAIClient)
        mock_client.chat_messages = []
        mock_client.var = {}
        mock_client.get_chat_messages_for_display.return_value = []
        for attr in (
            "_customer_access_token",
            "login_customer",
            "register_customer",
            "request_customer_otp",
            "register_customer_otp",
            "verify_customer_otp",
            "list_customer_sessions",
            "resume_customer_session",
            "logout_customer",
        ):
            if hasattr(mock_client, attr):
                delattr(mock_client, attr)
        return mock_client

    async def test_on_init_legacy_client_without_customer_token(self):
        """Verify on_init does not raise AttributeError if client lacks customer auth methods."""
        mock_client = self._make_legacy_client()
        self.state._client = mock_client

        await self.state.on_init()
        self.assertFalse(self.state.customer_signed_in)
        self.assertEqual(self.state.customer_auth_type, "disabled")

    async def test_on_init_client_with_customer_token(self):
        """Verify on_init correctly handles client when _customer_access_token is present."""
        mock_client = MagicMock()
        mock_client._customer_access_token = "test_token_123"
        mock_client.chat_messages = []
        mock_client.var = {"resumeSessionAuthType": "phone_otp"}
        self.state._client = mock_client

        await self.state.on_init()
        self.assertTrue(self.state.customer_signed_in)
        self.assertEqual(self.state.customer_auth_type, "phone_otp")

    async def test_customer_events_graceful_on_legacy_client(self):
        """Verify customer auth event handlers yield toast errors instead of crashing when client lacks methods."""
        mock_client = self._make_legacy_client()
        self.state._client = mock_client

        # sign_in_customer
        events = [ev async for ev in self.state.sign_in_customer({"identifier": "u", "password": "p"})]
        self.assertEqual(len(events), 1)

        # register_customer
        events = [ev async for ev in self.state.register_customer({"identifier": "u", "password": "p"})]
        self.assertEqual(len(events), 1)

        # request_customer_otp
        events = [ev async for ev in self.state.request_customer_otp({"phone": "123"})]
        self.assertEqual(len(events), 1)

        # register_customer_otp
        events = [ev async for ev in self.state.register_customer_otp({"phone": "123"})]
        self.assertEqual(len(events), 1)

        # verify_customer_otp
        self.state.customer_otp_challenge_id = "chall_id"
        events = [ev async for ev in self.state.verify_customer_otp({"code": "123456"})]
        self.assertEqual(len(events), 1)

        # refresh_customer_sessions
        events = [ev async for ev in self.state.refresh_customer_sessions()]
        self.assertEqual(len(events), 1)

        # resume_customer_session
        events = [ev async for ev in self.state.resume_customer_session("ses_uid")]
        self.assertEqual(len(events), 1)

        # sign_out_customer
        events = [ev async for ev in self.state.sign_out_customer()]
        self.assertEqual(len(events), 1)
        self.assertFalse(self.state.customer_signed_in)

    async def test_customer_events_with_supported_client(self):
        """Verify customer auth event handlers succeed when client implements customer methods."""
        mock_client = MagicMock()
        mock_client.login_customer = AsyncMock(return_value={"customer_uid": "c1", "expires_in": 3600})
        mock_client.register_customer = AsyncMock(return_value={"customer_uid": "c1", "expires_in": 3600})
        mock_client.request_customer_otp = AsyncMock(return_value="chall_1")
        mock_client.register_customer_otp = AsyncMock(return_value="chall_2")
        mock_client.verify_customer_otp = AsyncMock(return_value={"customer_uid": "c1", "expires_in": 3600})
        mock_client.list_customer_sessions = AsyncMock(return_value=[{"uid": "s1", "name": "Session 1", "summary": "Sum"}])
        mock_client._customer_access_token = "access_tok"
        mock_client.var = {}
        mock_client.chat_messages = []
        self.state._client = mock_client

        events = [ev async for ev in self.state.sign_in_customer({"identifier": "user", "password": "pw"})]
        self.assertTrue(self.state.customer_signed_in)
        self.assertEqual(len(self.state.customer_sessions), 1)
        mock_client.login_customer.assert_awaited_once_with("user", "pw")

        self.state.customer_signed_in = False
        events = [ev async for ev in self.state.register_customer({"identifier": "user2", "password": "pw", "first_name": "A", "last_name": "B"})]
        self.assertTrue(self.state.customer_signed_in)
        mock_client.register_customer.assert_awaited_once_with("user2", "pw", first_name="A", last_name="B")

        events = [ev async for ev in self.state.register_customer_otp({"phone": "+15551234567", "first_name": "A", "last_name": "B"})]
        self.assertEqual(self.state.customer_otp_challenge_id, "chall_2")
        mock_client.register_customer_otp.assert_awaited_once_with("+15551234567", first_name="A", last_name="B")

        self.state.set_customer_auth_tab("signup")
        self.assertEqual(self.state.customer_auth_tab, "signup")

    def test_customer_session_panel_renders(self):
        """Verify customer_session_panel component builds without error."""
        from pinion_reflex_agent.pages import customer_session_panel
        panel = customer_session_panel()
        self.assertIsNotNone(panel)


if __name__ == "__main__":
    unittest.main()
