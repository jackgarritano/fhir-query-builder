"""
FHIR Query Builder TUI (Text User Interface)

A terminal-based interface for building FHIR search queries using AI agents.
"""

from textual.app import App, ComposeResult
from textual.containers import Center, Middle, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header,
    Footer,
    Input,
    Button,
    Static,
    Label,
    Select,
    TextArea,
    LoadingIndicator,
)
from textual.binding import Binding
from textual import on, work
from textual.screen import Screen
from dotenv import load_dotenv
import sys
import os
from pathlib import Path

# Add parent directory to path to import agents module
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents import (
    fetch_searchable_resources,
    SelectTypesAgent,
    CreateQueryAgent,
    SelectedResourceType,
    SelectTypeError,
    CreateQueryOutput,
    CreateQueryError,
    COMMON_SEARCH_PARAMS,
    FHIRMetadata,
)

# Load environment variables
load_dotenv()


class StatusMessage(Static):
    """A status message widget that can show different states"""

    def set_loading(self, message: str = "Loading..."):
        """Show loading state"""
        self.update(f"⏳ {message}")
        self.add_class("loading")
        self.remove_class("success")
        self.remove_class("error")

    def set_success(self, message: str):
        """Show success state"""
        self.update(f"✓ {message}")
        self.add_class("success")
        self.remove_class("loading")
        self.remove_class("error")

    def set_error(self, message: str):
        """Show error state"""
        self.update(f"✗ {message}")
        self.add_class("error")
        self.remove_class("loading")
        self.remove_class("success")

    def clear(self):
        """Clear the message"""
        self.update("")
        self.remove_class("loading")
        self.remove_class("success")
        self.remove_class("error")


class TypeOption(Static):
    """A clickable resource type option"""

    def __init__(self, index: int, selected_type: SelectedResourceType, **kwargs):
        self.type_index = index
        self.selected_type = selected_type
        content = (
            f"[{index + 1}] {selected_type.selected_type} "
            f"(confidence: {selected_type.confidence:.2f})\n"
            f"    {selected_type.reasoning}"
        )
        super().__init__(content, **kwargs)

    def on_click(self) -> None:
        """Handle click to select this type"""
        app = self.app
        if isinstance(app, FHIRQueryBuilderApp):
            app.select_type_at_index(self.type_index)

class FhirApp(App):
    CSS = """
    LoginScreen { align: center middle; }
    Middle { width: 50%; height: auto; border: solid green; }
    Input { margin: 1; }
    Button { width: 100%; }
    """

    def on_mount(self):
        self.push_screen(LoginScreen())

class LoginScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Middle(
            Center(
                Label("🔒 Restricted Access"),
                Input(placeholder="Password", password=True, id="password"),
                Button("Login", id="login_btn"),
            )
        )

    @on(Button.Pressed, "#login_btn")
    def check_password(self):
        # ⚠️ Replace this with a secure check (env var, etc)
        password_input = self.query_one("#password", Input)
        if password_input.value == os.getenv("TUI_PASSWORD"):
            self.app.push_screen(FHIRQueryBuilderApp())
        else:
            self.notify("Incorrect Password", severity="error")

class FHIRQueryBuilderApp(Screen):
    """FHIR Query Builder TUI Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    .section {
        border: solid $primary;
        margin: 1;
        padding: 1;
        height: auto;
    }

    .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    Input {
        margin: 1 0;
    }

    Horizontal {
        height: auto;
        width: 100%;
    }

    Horizontal Input {
        width: 1fr;
        margin: 1 1 1 0;
    }

    Horizontal Input:last-child {
        margin: 1 0;
    }

    Button {
        margin: 1 0;
    }

    .success {
        color: $success;
    }

    .error {
        color: $error;
    }

    .loading {
        color: $warning;
    }

    #selected-types {
        height: auto;
        border: solid $secondary;
        padding: 1;
        margin: 1 0;
    }

    #query-output {
        height: auto;
        min-height: 3;
        border: solid $accent;
        padding: 1;
        margin: 1 0;
        background: $panel;
    }

    .type-option {
        margin: 0 1;
        padding: 0 1;
    }

    .type-option:hover {
        background: $boost;
    }

    .type-option.selected {
        background: $accent;
        color: $text;
    }

    #selection-hint {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "reset", "Reset", show=True),
    ]

    TITLE = "FHIR Query Builder"
    SUB_TITLE = "AI-Powered FHIR Search Query Generator"

    def __init__(self):
        super().__init__()
        self.metadata: FHIRMetadata | None = None
        self.select_agent: SelectTypesAgent | None = None
        self.selected_types: list[SelectedResourceType] = []
        self.selected_type_index: int = 0
        self.last_query_url: str = ""  # Store the last generated URL
        self._pending_query: str = ""  # Store query for worker
        self._pending_server_url: str = ""  # Store server URL for worker
        self._pending_username: str | None = None  # Store username for worker
        self._pending_password: str | None = None  # Store password for worker

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with ScrollableContainer(id="main-container"):
            # Step 1: Server Configuration
            with Vertical(classes="section"):
                yield Label("Step 1: FHIR Server Configuration", classes="section-title")
                yield Label("Enter FHIR server base URL:")
                yield Input(
                    placeholder="https://r4.smarthealthit.org",
                    value="https://r4.smarthealthit.org",
                    id="server-url",
                )
                yield Label("Optional: Basic Authentication (leave empty if not needed)")
                with Horizontal():
                    yield Input(
                        placeholder="Username (optional)",
                        id="auth-username",
                    )
                    yield Input(
                        placeholder="Password (optional)",
                        password=True,
                        id="auth-password",
                    )
                yield Button("Connect to Server", id="connect-btn", variant="primary")
                yield StatusMessage(id="server-status")

            # Step 2: Query Input
            with Vertical(classes="section"):
                yield Label("Step 2: Enter Your Query", classes="section-title")
                yield Label("Describe what you want to search for:")
                yield Input(
                    placeholder="e.g., Find all female patients born after 1990",
                    id="query-input",
                )
                yield Button("Select Resource Types", id="select-types-btn", variant="primary")
                yield StatusMessage(id="select-status")

            # Step 3: Type Selection
            with Vertical(classes="section"):
                yield Label("Step 3: Select Resource Type", classes="section-title")
                yield Label("Click on a resource type to select it:", id="selection-hint")
                yield ScrollableContainer(id="selected-types")
                yield Button("Build Query", id="build-query-btn", variant="primary")
                yield StatusMessage(id="build-status")

            # Step 4: Query Output
            with Vertical(classes="section"):
                yield Label("Step 4: Generated FHIR Query", classes="section-title")
                yield Static(id="query-output")
                yield Button("Copy to Clipboard", id="copy-btn", variant="default")

        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount - disable buttons until server is connected"""
        self.query_one("#select-types-btn", Button).disabled = True
        self.query_one("#build-query-btn", Button).disabled = True
        self.query_one("#copy-btn", Button).disabled = True
        self.query_one("#selection-hint", Label).display = False

    def select_type_at_index(self, index: int) -> None:
        """Select a resource type at the given index"""
        if not self.selected_types or index >= len(self.selected_types):
            return

        # Update the selected index
        old_index = self.selected_type_index
        self.selected_type_index = index

        # Update visual selection
        types_container = self.query_one("#selected-types", ScrollableContainer)
        
        # Remove selection from old item
        try:
            old_widget = types_container.query_one(f"#type-{old_index}", TypeOption)
            old_widget.remove_class("selected")
        except Exception:
            pass

        # Add selection to new item
        try:
            new_widget = types_container.query_one(f"#type-{index}", TypeOption)
            new_widget.add_class("selected")
        except Exception:
            pass

        # Update build status to show which type is selected
        status = self.query_one("#build-status", StatusMessage)
        selected = self.selected_types[index]
        status.set_success(f"Selected: {selected.selected_type}")

    @on(Button.Pressed, "#connect-btn")
    async def connect_to_server(self) -> None:
        """Connect to FHIR server and fetch metadata"""
        url_input = self.query_one("#server-url", Input)
        username_input = self.query_one("#auth-username", Input)
        password_input = self.query_one("#auth-password", Input)
        status = self.query_one("#server-status", StatusMessage)

        server_url = url_input.value.strip()
        username = username_input.value.strip() or None
        password = password_input.value.strip() or None

        if not server_url:
            status.set_error("Please enter a server URL")
            return

        status.set_loading("Connecting to FHIR server...")
        self.query_one("#connect-btn", Button).disabled = True

        # Store credentials for worker
        self._pending_server_url = server_url
        self._pending_username = username
        self._pending_password = password
        self._run_connect_worker()

    @work(thread=True)
    def _run_connect_worker(self) -> None:
        """Worker that fetches metadata in background thread"""
        try:
            metadata = fetch_searchable_resources(
                self._pending_server_url,
                self._pending_username,
                self._pending_password
            )
            self.call_from_thread(self._handle_connect_success, metadata)
        except Exception as e:
            self.call_from_thread(self._handle_connect_error, e)

    def _handle_connect_success(self, metadata: FHIRMetadata) -> None:
        """Handle successful connection"""
        status = self.query_one("#server-status", StatusMessage)
        self.metadata = metadata
        self.select_agent = SelectTypesAgent(self.metadata)
        status.set_success(
            f"Connected! Found {len(self.metadata.searchable_types)} resource types"
        )
        self.query_one("#connect-btn", Button).disabled = False
        self.query_one("#select-types-btn", Button).disabled = False

    def _handle_connect_error(self, error: Exception) -> None:
        """Handle connection error"""
        status = self.query_one("#server-status", StatusMessage)
        status.set_error(f"Connection failed: {str(error)[:100]}")
        self.query_one("#connect-btn", Button).disabled = False

    @on(Button.Pressed, "#select-types-btn")
    async def select_resource_types(self) -> None:
        """Use AI to select appropriate resource types"""
        query_input = self.query_one("#query-input", Input)
        status = self.query_one("#select-status", StatusMessage)

        query = query_input.value.strip()
        if not query:
            status.set_error("Please enter a query")
            return

        if not self.select_agent:
            status.set_error("Please connect to a server first")
            return

        status.set_loading("Analyzing query and selecting types...")
        
        # Disable button while processing
        self.query_one("#select-types-btn", Button).disabled = True

        # Store query for use in worker
        self._pending_query = query
        self._run_select_types_worker()

    @work(thread=True)
    def _run_select_types_worker(self) -> None:
        """Worker that runs type selection in a background thread"""
        try:
            results = self.select_agent.select_types(self._pending_query)
            self.call_from_thread(self._handle_select_types_result, results)
        except Exception as e:
            self.call_from_thread(self._handle_select_types_error, e)

    def _handle_select_types_result(self, results) -> None:
        """Handle results from type selection worker"""
        status = self.query_one("#select-status", StatusMessage)
        types_container = self.query_one("#selected-types", ScrollableContainer)
        selection_hint = self.query_one("#selection-hint", Label)
        
        # Re-enable button
        self.query_one("#select-types-btn", Button).disabled = False

        # Clear previous results
        types_container.remove_children()

        if isinstance(results, SelectTypeError):
            status.set_error(f"Error: {results.error}")
            types_container.mount(
                Static(f"Reasoning: {results.reasoning}", classes="error")
            )
            selection_hint.display = False
            return

        # Display selected types
        self.selected_types = results
        self.selected_type_index = 0

        for i, selected_type in enumerate(results):
            classes = "type-option"
            if i == 0:
                classes += " selected"

            type_widget = TypeOption(
                index=i,
                selected_type=selected_type,
                classes=classes,
                id=f"type-{i}",
            )
            types_container.mount(type_widget)

        status.set_success(f"Found {len(results)} matching resource type(s)")
        selection_hint.display = True

        # Enable next step
        self.query_one("#build-query-btn", Button).disabled = False
        
        # Show which type is selected
        build_status = self.query_one("#build-status", StatusMessage)
        build_status.set_success(f"Selected: {results[0].selected_type}")

    def _handle_select_types_error(self, error: Exception) -> None:
        """Handle error from type selection worker"""
        status = self.query_one("#select-status", StatusMessage)
        status.set_error(f"Type selection failed: {str(error)[:100]}")
        self.query_one("#select-types-btn", Button).disabled = False

    @on(Button.Pressed, "#build-query-btn")
    async def build_query(self) -> None:
        """Build FHIR query for selected resource type"""
        query_input = self.query_one("#query-input", Input)
        status = self.query_one("#build-status", StatusMessage)

        if not self.selected_types:
            status.set_error("Please select resource types first")
            return

        # Use the currently selected type
        selected_type = self.selected_types[self.selected_type_index]

        status.set_loading(f"Building query for {selected_type.selected_type}...")
        
        # Disable button while processing
        self.query_one("#build-query-btn", Button).disabled = True
        
        # Store data for worker
        self._pending_query = query_input.value
        self._pending_selected_type = selected_type
        self._run_build_query_worker()

    @work(thread=True)
    def _run_build_query_worker(self) -> None:
        """Worker that builds query in background thread"""
        try:
            # Create query agent for this type
            query_agent = CreateQueryAgent(
                target_type=self._pending_selected_type.selected_type,
                metadata=self.metadata,
                common_search_params=COMMON_SEARCH_PARAMS,
            )
            # Generate query
            result = query_agent.agent.run_sync(self._pending_query)
            self.call_from_thread(self._handle_build_query_result, result.output)
        except Exception as e:
            self.call_from_thread(self._handle_build_query_error, e)

    def _handle_build_query_result(self, query_output) -> None:
        """Handle results from query building worker"""
        status = self.query_one("#build-status", StatusMessage)
        output = self.query_one("#query-output", Static)
        selected_type = self._pending_selected_type
        
        # Re-enable button
        self.query_one("#build-query-btn", Button).disabled = False

        if isinstance(query_output, CreateQueryError):
            status.set_error("Query generation failed")
            output.update(
                f"[bold red]Error:[/bold red] {query_output.error}\n\n"
                f"[yellow]Suggestion:[/yellow] {query_output.suggestion or 'N/A'}"
            )
            return

        # Display the query
        full_url = f"{self.metadata.server_url}/{selected_type.selected_type}?{query_output.query_string}"

        # Store the URL for copying
        self.last_query_url = full_url

        output.update(
            f"[bold green]Success![/bold green]\n\n"
            f"[bold]Resource Type:[/bold] {selected_type.selected_type}\n"
            f"[bold]Query String:[/bold] {query_output.query_string}\n\n"
            f"[bold]Full URL:[/bold]\n{full_url}"
        )

        status.set_success("Query generated successfully!")

        # Enable copy button
        self.query_one("#copy-btn", Button).disabled = False

    def _handle_build_query_error(self, error: Exception) -> None:
        """Handle error from query building worker"""
        status = self.query_one("#build-status", StatusMessage)
        status.set_error(f"Query building failed: {str(error)[:100]}")
        self.query_one("#build-query-btn", Button).disabled = False

    @on(Button.Pressed, "#copy-btn")
    def copy_to_clipboard(self) -> None:
        """Copy the generated query URL to clipboard"""
        if not self.last_query_url:
            self.notify("No query to copy", severity="warning")
            return

        # Try to copy to clipboard
        try:
            import pyperclip
            pyperclip.copy(self.last_query_url)
            self.notify("✓ Copied to clipboard!", severity="information")
        except ImportError:
            # If pyperclip not available, just show the URL
            self.notify(
                f"URL: {self.last_query_url}",
                severity="information",
                timeout=10
            )

    def action_reset(self) -> None:
        """Reset the application to initial state"""
        self.query_one("#query-input", Input).value = ""
        self.query_one("#selected-types", ScrollableContainer).remove_children()
        self.query_one("#query-output", Static).update("")
        self.query_one("#server-status", StatusMessage).clear()
        self.query_one("#select-status", StatusMessage).clear()
        self.query_one("#build-status", StatusMessage).clear()
        self.query_one("#selection-hint", Label).display = False

        self.selected_types = []
        self.selected_type_index = 0
        self.last_query_url = ""

        self.query_one("#select-types-btn", Button).disabled = True
        self.query_one("#build-query-btn", Button).disabled = True
        self.query_one("#copy-btn", Button).disabled = True


def main():
    """Run the FHIR Query Builder TUI"""
    app = FhirApp()
    app.run()


if __name__ == "__main__":
    main()