import os

import reflex as rx
from pinionai import AsyncPinionAIClient

from .state import AppState


async def create_pinion_client(
    agent_id: str | None = None,
    url_params: dict | str | None = None,
    host_url: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    version: str | None = None,
    **kwargs,
) -> AsyncPinionAIClient:
    """Initialize AsyncPinionAIClient with url_params pass-through support.

    If url_params is not provided, falls back to URL_PARAMS or url_params environment variables.
    """
    params = url_params or os.environ.get("URL_PARAMS") or os.environ.get("url_params") or None
    return await AsyncPinionAIClient.create(
        agent_id=agent_id or os.environ.get("agent_id"),
        host_url=host_url or os.environ.get("host_url"),
        client_id=client_id or os.environ.get("client_id"),
        client_secret=client_secret or os.environ.get("client_secret"),
        version=version or os.environ.get("version") or None,
        url_params=params,
        **kwargs,
    )


async def create_pinion_client_from_stream(
    file_stream: str,
    url_params: dict | str | None = None,
    host_url: str | None = None,
    key_secret: str | None = None,
    **kwargs,
) -> tuple[AsyncPinionAIClient | None, str]:
    """Initialize AsyncPinionAIClient from stream with url_params pass-through support.

    If url_params is not provided, falls back to URL_PARAMS or url_params environment variables.
    """
    params = url_params or os.environ.get("URL_PARAMS") or os.environ.get("url_params") or None
    return await AsyncPinionAIClient.create_from_stream(
        file_stream=file_stream,
        host_url=host_url or os.environ.get("host_url"),
        key_secret=key_secret,
        url_params=params,
        **kwargs,
    )

_MICROPHONE_SCRIPT = """
(async () => {
  try {
    const active = window.__pinionAudioRecorder;
    if (active?.recorder.state === "recording") {
      const stopped = new Promise((resolve) =>
        active.recorder.addEventListener("stop", resolve, { once: true })
      );
      active.recorder.stop();
      await stopped;
      active.stream.getTracks().forEach((track) => track.stop());
      window.__pinionAudioRecorder = null;
      const blob = new Blob(active.chunks, {
        type: active.recorder.mimeType || "audio/webm",
      });
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Could not read the recording."));
        reader.readAsDataURL(blob);
      });
      return `audio:${dataUrl.split(",")[1]}`;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      return "error:Microphone recording is not supported by this browser.";
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    recorder.start();
    window.__pinionAudioRecorder = { recorder, stream, chunks };
    return "recording";
  } catch (error) {
    const active = window.__pinionAudioRecorder;
    active?.stream.getTracks().forEach((track) => track.stop());
    window.__pinionAudioRecorder = null;
    return `error:${error instanceof Error ? error.message : String(error)}`;
  }
})()
"""

def render_chat_bubble(message: dict[str, str]) -> rx.Component:
    """Renders individual chat messages securely using correct avatar bindings."""
    is_user = message["role"] == "user"
    file_type = message["file_type"]
    content = message["content"]
    office_file = (
        file_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ) | (
        file_type
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ) | (
        file_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    office_filename = rx.cond(
        file_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "response.xlsx",
        rx.cond(
            file_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "response.pptx",
            "response.docx",
        ),
    )
    rendered_content = rx.cond(
        file_type == "text/markdown",
        rx.markdown(content),
        rx.cond(
            file_type == "text/csv",
            rx.vstack(
                rx.text(content, white_space="pre-wrap"),
                rx.cond(
                    content.startswith("http"),
                    rx.el.a(
                        "Download CSV",
                        href=content,
                        download="response.csv",
                    ),
                    rx.button(
                        "Download CSV",
                        on_click=rx.download(
                            data=content,
                            filename="response.csv",
                            mime_type="text/csv",
                        ),
                    ),
                ),
                align="start",
            ),
            rx.cond(
                file_type.startswith("text/")
                | (file_type == "application/json")
                | (file_type == "application/xml")
                | (file_type == "application/javascript"),
                rx.text(content, white_space="pre-wrap"),
                rx.cond(
                    office_file,
                    rx.vstack(
                        rx.text(f"File response: {file_type}"),
                        rx.el.a(
                            "Download file",
                            href=content,
                            download=office_filename,
                            target="_blank",
                        ),
                        align="start",
                    ),
                    rx.cond(
                        file_type == "application/pdf",
                        rx.vstack(
                            rx.el.iframe(
                                src=content,
                                title="PDF response",
                                width="100%",
                                height="600px",
                            ),
                            rx.el.a(
                                "Download PDF",
                                href=content,
                                download="response.pdf",
                                target="_blank",
                            ),
                            width="100%",
                            align="start",
                        ),
                        rx.cond(
                            file_type.startswith("image/"),
                            rx.image(src=content, alt="Agent response"),
                            rx.link(
                                f"Open/download {file_type}",
                                href=content,
                                is_external=True,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    return rx.hstack(
        # Assistant Avatar Display Left
        rx.cond(
            ~is_user,
            rx.avatar(src=AppState.assistant_img, fallback="AI", size="2", radius="full")
        ),
        # Message Dialog Bubble Wrapper
        rx.box(
            rendered_content,
            background_color=rx.cond(is_user, "var(--accent-9)", "var(--gray-2)"),
            color=rx.cond(is_user, "white", "var(--gray-12)"),
            padding="0.4em 1em",
            border_radius="lg",
            max_width="75%",
            border="1px solid var(--gray-4)",
            box_shadow="sm",
        ),
        # User Avatar Display Right
        rx.cond(
            is_user,
            rx.avatar(src=AppState.user_img, fallback="U", size="2", radius="full")
        ),
        justify=rx.cond(is_user, "end", "start"),
        width="100%",
        spacing="3",
        align_items="start",
    )

def agent_selection_subpanel() -> rx.Component:
    """Renders account agents that can be started, switched, or merged into this chat."""
    return rx.vstack(
        rx.hstack(
            rx.text(
                "Select Agent",
                font_weight="bold",
                size="2",
                color="var(--gray-12)",
            ),
            rx.spacer(),
            rx.button(
                rx.icon(tag="refresh-cw", size=14),
                "Refresh",
                variant="ghost",
                size="1",
                on_click=AppState.refresh_available_agents,
            ),
            width="100%",
            align_items="center",
        ),
        rx.select.root(
            rx.select.trigger(placeholder="Select an agent"),
            rx.select.content(
                rx.foreach(
                    AppState.available_agents,
                    lambda agent: rx.select.item(
                        agent["agent_name"],
                        value=agent["uid"],
                    ),
                )
            ),
            value=AppState.selected_agent_uid,
            on_change=AppState.select_available_agent,
            disabled=AppState.selected_agent_uid == "",
            width="100%",
        ),
        rx.hstack(
            rx.button(
                "Start Agent",
                color_scheme=AppState.accent_color,
                variant="soft",
                size="1",
                on_click=AppState.start_selected_agent,
                disabled=AppState.selected_agent_uid == "",
                flex="1",
                title="Start fresh with this agent, resetting conversation history and session variables.",
            ),
            rx.button(
                "Switch Agent",
                color_scheme=AppState.accent_color,
                variant="soft",
                size="1",
                on_click=AppState.switch_selected_agent,
                disabled=AppState.selected_agent_uid == "",
                flex="1",
                title="Switch to this agent's behavior and intents while retaining current conversation variables.",
            ),
            rx.button(
                "Merge Agent",
                color_scheme=AppState.accent_color,
                variant="soft",
                size="1",
                on_click=AppState.merge_selected_agent,
                disabled=AppState.selected_agent_uid == "",
                flex="1",
                title="Add this agent's capabilities to the current chat without replacing its session.",
            ),
            width="100%",
            spacing="2",
        ),
        rx.cond(
            AppState.agent_list_error != "",
            rx.text(
                "Available agents could not be loaded: ",
                AppState.agent_list_error,
                size="1",
                color="orange.700",
            ),
            rx.cond(
                AppState.selected_agent_uid == "",
                rx.text(
                    "No account agents are available. Check account credentials and refresh.",
                    size="1",
                    color="gray.600",
                ),
                rx.fragment(),
            ),
        ),
        rx.cond(
            AppState.agent_selection_status != "",
            rx.text(AppState.agent_selection_status, size="1", color="gray.700"),
        ),
        width="100%",
        spacing="2",
        padding="1em",
        background_color="white",
        border_radius="md",
        border="1px solid #e2e8f0",
    )

def aia_management_subpanel() -> rx.Component:
    """Renders the drag-and-drop .aia file workspace context controller."""
    return rx.vstack(
        rx.text(
            "Upload AIA File",
            font_weight="bold",
            size="2",
            color="var(--gray-12)",
        ),
        rx.text(
            "Start a saved agent, switch behavior, or merge its capabilities into the current chat.",
            size="1",
            color="var(--gray-11)",
        ),
        
        # Segmented Tab Selection to switch workflow mode intent before loading
        rx.hstack(
            rx.button(
                "Start AIA", 
                color_scheme=rx.cond(AppState.aia_mode == "start", AppState.accent_color, "gray"),
                variant=rx.cond(AppState.aia_mode == "start", "soft", "surface"),
                size="1",
                flex="1",
                title="Start fresh with this AIA file.",
                on_click=AppState.set_mode_start,
            ),
            rx.button(
                "Switch AIA", 
                color_scheme=rx.cond(AppState.aia_mode == "switch", AppState.accent_color, "gray"),
                variant=rx.cond(AppState.aia_mode == "switch", "soft", "surface"),
                size="1",
                flex="1",
                title="Switch to this AIA agent retaining current variables.",
                on_click=AppState.set_mode_switch,
            ),
            rx.button(
                "Merge AIA", 
                color_scheme=rx.cond(AppState.aia_mode == "merge", AppState.accent_color, "gray"),
                variant=rx.cond(AppState.aia_mode == "merge", "soft", "surface"),
                size="1",
                flex="1",
                title="Merge this AIA agent capabilities additively.",
                on_click=AppState.set_mode_merge,
            ),
            width="100%",
            spacing="2",
        ),
        
        # Central operational toggle branch: Intercept layout if password lock matches
        rx.cond(
            AppState.awaiting_key_secret | AppState.merging_aia | AppState.switching_aia,
            
            # --- Decryption Key Subform Overlay ---
            rx.vstack(
                rx.text("🔓 Private AIA File. Key Needed:", color_scheme="red", size="1"),
                rx.input(
                    placeholder="Enter decryption secret...", 
                    type="password", 
                    size="1",
                    value=AppState.secret_key,
                    on_change=AppState.set_secret_key,
                    width="100%"
                ),
                rx.hstack(
                    rx.button(
                        rx.cond(
                            AppState.merging_aia,
                            "Unlock and Merge Agent",
                            rx.cond(
                                AppState.switching_aia,
                                "Unlock and Switch Agent",
                                "Unlock and Start Agent",
                            ),
                        ),
                        color_scheme="green",
                        size="1",
                        on_click=AppState.submit_secret_key,
                    ),
                    rx.button("Cancel", color_scheme="gray", size="1", on_click=AppState.reset_flow_states)
                ),
                width="100%",
                spacing="2"
            ),
            
            # --- Standard Dropzone Upload Interactive Area ---
            rx.upload(
                rx.vstack(
                    rx.icon(tag="upload", size=18),
                    rx.text("Drop file (.aia)", size="1", text_align="center"),
                    spacing="1",
                    align="center",
                    justify="center"
                ),
                id="aia_uploader",
                multiple=False,
                accept={".aia": []},
                max_files=1,
                border="1px dashed #cbd5e1",
                padding="1em",
                border_radius="md",
                width="100%",
                on_drop=AppState.handle_aia_upload(
                    rx.upload_files(upload_id="aia_uploader")
                )
            )
        ),
        rx.text(AppState.status_message, size="1", color="gray.500", italic=True),
        width="100%",
        spacing="3",
        padding="1em",
        background_color="white",
        border_radius="md",
        border="1px solid #e2e8f0"
    )

def render_customer_session(session: dict[str, str]) -> rx.Component:
    return rx.vstack(
        rx.text(
            rx.cond(session["name"] != "", session["name"], "Untitled session"),
            font_weight="bold",
        ),
        rx.text(session["summary"], size="1", color="gray"),
        rx.button(
            "Resume",
            on_click=AppState.resume_customer_session(session["uid"]),
            size="1",
            variant="outline",
        ),
        width="100%",
        align_items="start",
        spacing="1",
        padding="0.5em",
        border="1px solid var(--gray-4)",
        border_radius="md",
    )


def customer_session_panel() -> rx.Component:
    return rx.vstack(
        rx.text("Customer history", font_weight="bold", size="2"),
        rx.cond(
            AppState.customer_signed_in,
            rx.vstack(
                rx.text("Signed in. Only your linked sessions are shown.", size="1"),
                rx.button(
                    "Refresh sessions",
                    on_click=AppState.refresh_customer_sessions,
                    size="2",
                    variant="outline",
                ),
                rx.foreach(AppState.customer_sessions, render_customer_session),
                rx.button(
                    "Sign out",
                    on_click=AppState.sign_out_customer,
                    size="2",
                    variant="ghost",
                ),
                width="100%",
                align_items="stretch",
                spacing="2",
            ),
            rx.cond(
                AppState.customer_auth_type == "phone_otp",
                rx.cond(
                    AppState.customer_otp_challenge_id != "",
                    rx.form(
                        rx.vstack(
                            rx.input(
                                name="code",
                                type="password",
                                placeholder="Six-digit verification code",
                                max_length=6,
                                required=True,
                            ),
                            rx.button("Verify code", type="submit", width="100%"),
                            rx.button(
                                "Request another code",
                                on_click=AppState.reset_customer_otp,
                                variant="ghost",
                                width="100%",
                            ),
                            width="100%",
                            spacing="2",
                        ),
                        on_submit=AppState.verify_customer_otp,
                        reset_on_submit=True,
                        width="100%",
                    ),
                    rx.vstack(
                        rx.segmented_control.root(
                            rx.segmented_control.item("Sign In", value="signin"),
                            rx.segmented_control.item("Sign Up", value="signup"),
                            value=AppState.customer_auth_tab,
                            on_change=AppState.set_customer_auth_tab,
                            size="1",
                            width="100%",
                        ),
                        rx.cond(
                            AppState.customer_auth_tab == "signup",
                            rx.form(
                                rx.vstack(
                                    rx.input(
                                        name="phone",
                                        placeholder="Phone number (+15551234567)",
                                        required=True,
                                    ),
                                    rx.input(
                                        name="first_name",
                                        placeholder="First name",
                                    ),
                                    rx.input(
                                        name="last_name",
                                        placeholder="Last name",
                                    ),
                                    rx.button("Sign up with phone", type="submit", width="100%"),
                                    width="100%",
                                    spacing="2",
                                ),
                                on_submit=AppState.register_customer_otp,
                                reset_on_submit=True,
                                width="100%",
                            ),
                            rx.form(
                                rx.vstack(
                                    rx.input(
                                        name="phone",
                                        placeholder="Saved phone number (+15551234567)",
                                        required=True,
                                    ),
                                    rx.button("Send verification code", type="submit", width="100%"),
                                    width="100%",
                                    spacing="2",
                                ),
                                on_submit=AppState.request_customer_otp,
                                reset_on_submit=True,
                                width="100%",
                            ),
                        ),
                        width="100%",
                        spacing="2",
                    ),
                ),
                rx.cond(
                    AppState.customer_auth_type == "password",
                    rx.vstack(
                        rx.segmented_control.root(
                            rx.segmented_control.item("Sign In", value="signin"),
                            rx.segmented_control.item("Sign Up", value="signup"),
                            value=AppState.customer_auth_tab,
                            on_change=AppState.set_customer_auth_tab,
                            size="1",
                            width="100%",
                        ),
                        rx.cond(
                            AppState.customer_auth_tab == "signup",
                            rx.form(
                                rx.vstack(
                                    rx.input(
                                        name="identifier",
                                        placeholder="Phone or email",
                                        required=True,
                                    ),
                                    rx.input(
                                        name="password",
                                        type="password",
                                        placeholder="Password",
                                        required=True,
                                    ),
                                    rx.input(
                                        name="first_name",
                                        placeholder="First name",
                                    ),
                                    rx.input(
                                        name="last_name",
                                        placeholder="Last name",
                                    ),
                                    rx.button("Sign up", type="submit", width="100%"),
                                    width="100%",
                                    spacing="2",
                                ),
                                on_submit=AppState.register_customer,
                                reset_on_submit=True,
                                width="100%",
                            ),
                            rx.form(
                                rx.vstack(
                                    rx.input(
                                        name="identifier",
                                        placeholder="Phone, email or ID",
                                        required=True,
                                    ),
                                    rx.input(
                                        name="password",
                                        type="password",
                                        placeholder="Password",
                                        required=True,
                                    ),
                                    rx.button("Sign in", type="submit", width="100%"),
                                    width="100%",
                                    spacing="2",
                                ),
                                on_submit=AppState.sign_in_customer,
                                reset_on_submit=True,
                                width="100%",
                            ),
                        ),
                        width="100%",
                        spacing="2",
                    ),
                    rx.text("Customer session history sign-in is disabled for this agent.", size="1"),
                ),
            ),
        ),
        width="100%",
        align_items="stretch",
        spacing="2",
    )


def sidebar_panel() -> rx.Component:
    """The compact agent and session controls shown above the chat."""
    return rx.vstack(
        # 1. Choose an account agent to start, switch, or merge.
        agent_selection_subpanel(),
        rx.divider(),

        # 2. Start, switch, or merge a saved AIA file.
        aia_management_subpanel(),
        rx.divider(),

        customer_session_panel(),
        rx.divider(),

        # 3. Session routing controls follow agent selection and loading.
        rx.vstack(
            rx.text("Session Route:", font_weight="bold", size="2"),
            rx.badge(
                AppState.connection_status,
                color_scheme=rx.cond(AppState.is_live_agent_mode, "green", "gray"),
                variant="surface",
            ),
            
            rx.cond(
                AppState.is_live_agent_mode,
                rx.button(
                    "Disconnect Live Agent", 
                    color_scheme="red", 
                    variant="outline", 
                    size="2",
                    width="100%",
                    on_click=AppState.end_live_session
                )
            ),
            rx.cond(
                AppState.transfer_allowed,
                rx.button(
                    "End Chat Session",
                    color_scheme="red",
                    variant="surface",
                    width="100%",
                    on_click=AppState.terminate_conversation,
                ),
            ),
            width="100%",
            spacing="2"
        ),
        spacing="2",
        padding="0.75em",
        max_height="45vh",
        overflow_y="auto",
        background_color="var(--gray-1)",
        border="1px solid var(--gray-4)",
        border_radius="md",
        width="100%",
    )

def main_chat_area() -> rx.Component:
    """The main communication chat canvas containing tracking indicators and inputs."""
    return rx.vstack(
        rx.cond(
            AppState.agentlist_mode,
            rx.accordion.root(
                rx.accordion.item(
                    header=rx.hstack(
                        rx.text("Agent Controls", size="2", align="right", color="var(--gray-11)", font_weight="medium"),
                        rx.spacer(),
                        align_items="center",
                        width="100%",
                        border_radius="md",
                    ),
                    content=sidebar_panel(),
                    value="agent-controls",
                ),
                type="single",
                collapsible=True,
                width="100%",
                flex_shrink="0",
                variant="outline",
            ),
        ),

        # Hidden native HTML5 Audio player block synced instantly to URL changes
        rx.cond(
            AppState.audio_file != "",
            rx.el.audio(
                src=rx.get_upload_url(AppState.audio_file),
                auto_play=True,
                controls=False,
                style={"display": "none"}
            )
        ),
        
        # Dynamic Stream Process Spinner Badges
        rx.hstack(
            rx.cond(
                AppState.is_processing_audio,
                rx.badge("🎙️ Transcribing voice input...", color_scheme="amber", variant="solid")
            ),
            rx.cond(
                AppState.is_generating_audio,
                rx.badge("🔊 Rendering Voice Response...", color_scheme="blue", variant="solid")
            ),
            position="absolute",
            top="1em",
            right="2em",
            spacing="2",
            z_index="10"
        ),

        # Thread Layout Presentation Title Headers
        rx.hstack(
            rx.vstack(
                rx.heading(AppState.agent_title, size="6"),
                rx.text(AppState.agent_subtitle, size="2", color="gray"),
                align_items="start",
                spacing="1"
            ),
            rx.spacer(),
            rx.image(src=AppState.assistant_img, width="44px", height="44px", border_radius="full"),
            width="100%",
            padding_bottom="1em",
            border_bottom="1px solid #edf2f7",
        ),
        
        # Thread Discussion Context Content Frame Box
        rx.auto_scroll(
            rx.vstack(
                rx.foreach(AppState.chat_messages, render_chat_bubble),
                rx.cond(
                    AppState.is_thinking,
                    rx.hstack(
                        rx.avatar(src=AppState.assistant_img, fallback="AI", size="2", radius="full"),
                        rx.spinner(size="2"),
                        rx.text("Thinking...", size="2", color="gray"),
                        spacing="3",
                        align="center",
                    ),
                ),
                spacing="2",
                width="100%",
            ),
            flex="1",
            min_height="0",
            width="100%",
            padding_y="0.5em",
        ),
        
        # Bottom Prompt Submission Dock Layout
        rx.hstack(
            rx.form(
                rx.hstack(
                    rx.input(
                        placeholder=rx.cond(
                            AppState.locale == "es",
                            "Escriba una pregunta sobre autos, financiamiento...",
                            "Type your question here.",
                        ),
                        id="user_input_field",
                        name="user_input_field",
                        width="100%",
                        size="3",
                    ),
                    rx.button(
                        rx.icon(tag="send", size=18),
                        type="submit",
                        variant="solid",
                        color_scheme=AppState.accent_color,
                        size="3",
                        cursor="pointer",
                    ),
                    width="100%",
                    spacing="2",
                    align_items="center",
                ),
                on_submit=AppState.handle_text_submit,
                reset_on_submit=True,
                flex="1",
                min_width="0",
            ),
            # Record microphone audio in the browser and pass the completed recording to state.
            rx.cond(
                AppState.stt_enabled,
                rx.button(
                    rx.cond(
                        AppState.is_recording_audio,
                        rx.icon(tag="square", size=16),
                        rx.icon(tag="mic", size=16),
                    ),
                    variant="soft",
                    color_scheme=rx.cond(
                        AppState.is_recording_audio,
                        "red",
                        AppState.accent_color,
                    ),
                    cursor="pointer",
                    size="2",
                    type="button",
                    width="2.5rem",
                    height="2.5rem",
                    min_width="2.5rem",
                    padding="0",
                    aria_label=rx.cond(
                        AppState.is_recording_audio,
                        "Stop recording",
                        "Start voice recording",
                    ),
                    disabled=AppState.is_processing_audio,
                    on_click=rx.call_script(
                        _MICROPHONE_SCRIPT,
                        callback=AppState.handle_recording_result,
                    ),
                )
            ),
            width="100%",
            spacing="3",
            padding_top="1em",
            border_top="1px solid var(--gray-4)",
            background_color="var(--gray-1)",
            align_items="center"
        ),
        spacing="2",
        padding="0.75em",
        flex="1",
        height="100%",
        min_height="0",
        position="relative"
    )

def index() -> rx.Component:
    """The root template index wrapper mapping base logic constraints cleanly."""
    return rx.vstack(
        # Hard Intercept Panel displaying summary message if conversion has dropped terminated
        rx.cond(
            AppState.end_chat_clicked,
            rx.center(
                rx.card(
                    rx.vstack(
                        rx.icon(tag="circle-alert", size=36, color="red"),
                        rx.heading("Conversation Halted", size="5"),
                        rx.text("This active routing conversation has closed successfully.", text_align="center", size="2"),
                        rx.button("Restart Fresh Interface", color_scheme=AppState.accent_color, on_click=AppState.restart_interface),
                        align="center",
                        spacing="4",
                    ),
                    padding="2em",
                    max_width="400px"
                ),
                width="100%",
                height="100dvh",
                background_color="#f8fafc"
            ),
            # Full-width chat with controls that can be opened when needed.
            rx.box(
                main_chat_area(),
                width="100%",
                height="100dvh",
                min_height="0",
                overflow="hidden",
            )
        ),
        width="100%",
        height="100dvh",
        spacing="0",
    )