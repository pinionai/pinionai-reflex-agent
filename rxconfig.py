import reflex as rx
import os
from typing import Any
from dotenv import load_dotenv

# Load local environment variables from the .env file
load_dotenv()

# Only pin api_url when it is explicitly configured. Otherwise Reflex derives it
# from the actual port, which is what we want in every supported setup:
#   - `reflex run` / `reflex run --backend-port 8001` (dev, separate ports)
#   - `reflex run --env prod --single-port` (Docker / Cloud Run, one port)
# The compiled frontend rewrites a localhost backend URL to the page's own host
# (and to wss:// behind HTTPS), so Cloud Run needs no PUBLIC_URL.
# Set PUBLIC_URL (or BACKEND_URL) only if the backend lives on a different host.
_api_url = os.environ.get("PUBLIC_URL") or os.environ.get("BACKEND_URL")
_extra_config: dict[str, Any] = {"api_url": _api_url} if _api_url else {}

from reflex.plugins.sitemap import SitemapPlugin
from pinion_reflex_agent.state import AppState

config = rx.Config(
    app_name="pinion_reflex_agent",

    # 1. Port Configuration
    # Cloud Run injects PORT (8080); locally it comes from .env or defaults to 3000.
    # With --single-port, frontend and backend are served together on this port.
    frontend_port=int(os.environ.get("PORT", 3000)),

    # 2. Backend API URL mapping
    # This tells the compiled React code in the user's browser exactly where
    # to send WebSocket events and gRPC tracking requests (see _extra_config).
    **_extra_config,

    # 3. Telemetry and optimization tweaks for container deployment
    telemetry_enabled=False,

    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="light",
                has_background=True,
                radius="large",
                accent_color=AppState.accent_color,
            )
        )
    ],
    disable_plugins=[SitemapPlugin],
)
