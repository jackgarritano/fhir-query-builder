"""
FHIR Query Builder TUI (Text User Interface)

A terminal-based interface for building FHIR search queries using AI agents.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
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
from textual import on
from textual.validation import Function
from dotenv import load_dotenv
import sys
from pathlib import Path

# Add parent directory to path to import agents module
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import (
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


class FHIRQueryBuilderApp(App):
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
        max-height: 10;
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

    .selected {
        background: $accent;
        color: $text;
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

    @on(Button.Pressed, "#connect-btn")
    async def connect_to_server(self) -> None:
        """Connect to FHIR server and fetch metadata"""
        url_input = self.query_one("#server-url", Input)
        status = self.query_one("#server-status", StatusMessage)

        server_url = url_input.value.strip()
        if not server_url:
            status.set_error("Please enter a server URL")
            return

        status.set_loading("Connecting to FHIR server...")

        def fetch_metadata():
            return fetch_searchable_resources(server_url)

        try:
            # Fetch metadata from server in a thread
            worker = self.run_worker(fetch_metadata, thread=True)
            self.metadata = await worker.wait()

            # Initialize select agent
            self.select_agent = SelectTypesAgent(self.metadata)

            status.set_success(
                f"Connected! Found {len(self.metadata.searchable_types)} resource types"
            )

            # Enable next step
            self.query_one("#select-types-btn", Button).disabled = False

        except Exception as e:
            status.set_error(f"Connection failed: {str(e)[:100]}")

    @on(Button.Pressed, "#select-types-btn")
    async def select_resource_types(self) -> None:
        """Use AI to select appropriate resource types"""
        query_input = self.query_one("#query-input", Input)
        status = self.query_one("#select-status", StatusMessage)
        types_container = self.query_one("#selected-types", ScrollableContainer)

        query = query_input.value.strip()
        if not query:
            status.set_error("Please enter a query")
            return

        if not self.select_agent:
            status.set_error("Please connect to a server first")
            return

        status.set_loading("Analyzing query and selecting types...")

        def select_types():
            return self.select_agent.select_types(query)

        try:
            # Run type selection in a thread
            worker = self.run_worker(select_types, thread=True)
            results = await worker.wait()

            # Clear previous results
            await types_container.remove_children()

            if isinstance(results, SelectTypeError):
                status.set_error(f"Error: {results.error}")
                await types_container.mount(
                    Static(f"Reasoning: {results.reasoning}", classes="error")
                )
                return

            # Display selected types
            self.selected_types = results
            self.selected_type_index = 0

            for i, selected_type in enumerate(results):
                classes = "type-option"
                if i == 0:
                    classes += " selected"

                type_widget = Static(
                    f"[{i + 1}] {selected_type.selected_type} "
                    f"(confidence: {selected_type.confidence:.2f})\n"
                    f"    {selected_type.reasoning}",
                    classes=classes,
                    id=f"type-{i}",
                )
                await types_container.mount(type_widget)

            status.set_success(f"Found {len(results)} matching resource type(s)")

            # Enable next step
            self.query_one("#build-query-btn", Button).disabled = False

        except Exception as e:
            status.set_error(f"Type selection failed: {str(e)[:100]}")

    @on(Button.Pressed, "#build-query-btn")
    async def build_query(self) -> None:
        """Build FHIR query for selected resource type"""
        query_input = self.query_one("#query-input", Input)
        status = self.query_one("#build-status", StatusMessage)
        output = self.query_one("#query-output", Static)

        if not self.selected_types:
            status.set_error("Please select resource types first")
            return

        # Use the first selected type (or allow user to choose)
        selected_type = self.selected_types[self.selected_type_index]

        status.set_loading(f"Building query for {selected_type.selected_type}...")

        def build_query_string():
            # Create query agent for this type
            query_agent = CreateQueryAgent(
                target_type=selected_type.selected_type,
                metadata=self.metadata,
                common_search_params=COMMON_SEARCH_PARAMS,
            )
            # Generate query
            return query_agent.agent.run_sync(query_input.value)

        try:
            # Run query building in a thread
            worker = self.run_worker(build_query_string, thread=True)
            result = await worker.wait()

            query_output = result.output

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

        except Exception as e:
            status.set_error(f"Query building failed: {str(e)[:100]}")

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

        self.selected_types = []
        self.selected_type_index = 0
        self.last_query_url = ""

        self.query_one("#select-types-btn", Button).disabled = True
        self.query_one("#build-query-btn", Button).disabled = True
        self.query_one("#copy-btn", Button).disabled = True


def main():
    """Run the FHIR Query Builder TUI"""
    app = FHIRQueryBuilderApp()
    app.run()


if __name__ == "__main__":
    main()
