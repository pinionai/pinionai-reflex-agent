import os
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ["PYTEST_CURRENT_TEST"] = "1"

import reflex as rx
from reflex.istate.data import RouterData, PageData, ReflexURL
from reflex.istate.manager.token import StateToken

from pinion_reflex_agent.state import AppState
from pinion_reflex_agent.agent_selection import merge_agent_capabilities
from pinion_reflex_agent.pages import create_pinion_client, create_pinion_client_from_stream


class TestUrlParamsSupport(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = rx.App()

    async def asyncSetUp(self):
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


if __name__ == "__main__":
    unittest.main()
