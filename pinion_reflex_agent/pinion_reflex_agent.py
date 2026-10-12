import reflex as rx
from .state import AppState
from .pages import index  # Assuming you put the UI layouts in pages.py

# Initialize the Reflex App
app = rx.App()

# Bind the index page layout component to the root URL route (/)
app.add_page(
    index, 
    route="/", 
    title="PinionAI Chat",
    on_load=AppState.on_init # Fires your fallback client creation instantly
)
