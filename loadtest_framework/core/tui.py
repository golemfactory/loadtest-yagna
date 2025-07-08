from collections import defaultdict
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static
from textual.message import Message

from yapapi.events import (
    AgreementConfirmed,
    AgreementCreated,
    AgreementTerminated,
    ProposalReceived,
    TaskAccepted,
    TaskFinished,
    TaskRejected,
    WorkerStarted,
    TaskStarted,
    Event,
)


class YapapiEvent(Message):
    """A message that wraps a yapapi event."""

    def __init__(self, event: Event) -> None:
        self.event = event
        super().__init__()


class TUI(App):
    """A Textual UI for the Golem Load Testing Framework."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def __init__(self, suite_name: str, start_time: datetime, settings: dict, **kwargs):
        super().__init__(**kwargs)
        self.run_suite_coro = None
        self.providers_data = {}
        self.tasks_data = defaultdict(int)
        self.total_tasks = 0
        self.suite_name = suite_name
        self.start_time = start_time
        self.settings = settings

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Static(id="suite_info")
        yield DataTable(id="providers", zebra_stripes=True)
        yield DataTable(id="tasks", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.update_suite_info()
        self.set_interval(1, self.update_suite_info)

        providers_table = self.query_one("#providers", DataTable)
        providers_table.add_columns(
            "Provider ID", "Name", "Status", "Tasks (Running/Total)", "Network"
        )

        tasks_table = self.query_one("#tasks", DataTable)
        tasks_table.add_columns("Status", "Count")
        self.update_tasks_table()

        self.run_worker(self.run_suite_coro)

    def on_yapapi_event(self, message: YapapiEvent) -> None:
        """Called when a yapapi event is received."""
        event = message.event

        if isinstance(event, ProposalReceived):
            provider_id = event.provider_id
            if provider_id not in self.providers_data:
                self.providers_data[provider_id] = {
                    "name": "N/A",
                    "status": "Negotiating",
                    "tasks_running": 0,
                    "tasks_total": 0,
                    "network": "N/A",
                    "agreement_id": None,
                }
                self.update_providers_table()
        elif isinstance(event, AgreementCreated):
            provider_id = event.provider_id
            if provider_id in self.providers_data:
                self.providers_data[provider_id]["status"] = "Agreement Creating"
                self.providers_data[provider_id]["agreement_id"] = event.agr_id
                self.providers_data[provider_id]["name"] = event.provider_info.name
                self.update_providers_table()
        elif isinstance(event, AgreementConfirmed):
            provider_id = event.provider_id
            if provider_id in self.providers_data:
                self.providers_data[provider_id]["status"] = "Confirmed"
                self.update_providers_table()
        elif isinstance(event, WorkerStarted):
            provider_id = event.provider_id
            if provider_id in self.providers_data:
                self.providers_data[provider_id]["status"] = "Initializing"
                self.update_providers_table()
        elif isinstance(event, TaskStarted):
            provider_id = self.get_provider_id_by_agreement(event.agr_id)
            if provider_id and provider_id in self.providers_data:
                self.providers_data[provider_id]["status"] = "Computing"
                self.providers_data[provider_id]["tasks_running"] += 1
                self.providers_data[provider_id]["tasks_total"] += 1
                self.tasks_data["Running"] += 1
                self.update_providers_table()
                self.update_tasks_table()
        elif isinstance(event, (TaskFinished, TaskAccepted, TaskRejected)):
            provider_id = self.get_provider_id_by_agreement(event.agr_id)
            if provider_id and provider_id in self.providers_data:
                self.providers_data[provider_id]["tasks_running"] -= 1
                if self.providers_data[provider_id]["tasks_running"] == 0:
                    self.providers_data[provider_id]["status"] = "Confirmed"
                self.update_providers_table()

            if isinstance(event, TaskFinished):
                self.tasks_data["Finished"] += 1
            elif isinstance(event, TaskAccepted):
                self.tasks_data["Accepted"] += 1
            elif isinstance(event, TaskRejected):
                self.tasks_data["Rejected"] += 1
            self.tasks_data["Running"] -= 1
            self.update_tasks_table()
        elif isinstance(event, AgreementTerminated):
            provider_id = self.get_provider_id_by_agreement(event.agr_id)
            if provider_id and provider_id in self.providers_data:
                self.providers_data[provider_id]["status"] = "Terminated"
                self.update_providers_table()

    def get_provider_id_by_agreement(self, agr_id: str):
        for provider_id, data in self.providers_data.items():
            if data["agreement_id"] == agr_id:
                return provider_id
        return None

    def update_suite_info(self):
        suite_info = self.query_one("#suite_info", Static)
        elapsed_time = datetime.now() - self.start_time
        settings_str = "  |  ".join(
            f"[bold]{k}:[/bold] {v}" for k, v in self.settings.items()
        )
        suite_info.update(
            f"Suite: [bold]{self.suite_name}[/bold]  |  Elapsed Time: [bold]{str(elapsed_time).split('.')[0]}[/bold]\n"
            f"Settings: {settings_str}"
        )

    def update_providers_table(self):
        table = self.query_one("#providers", DataTable)
        table.clear()
        for provider_id, data in self.providers_data.items():
            tasks_str = f"{data['tasks_running']}/{data['tasks_total']}"
            table.add_row(
                provider_id, data["name"], data["status"], tasks_str, data["network"]
            )

    def update_tasks_table(self):
        table = self.query_one("#tasks", DataTable)
        table.clear()
        for status, count in self.tasks_data.items():
            table.add_row(status, str(count))
        table.add_row("Total", str(self.total_tasks))

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    async def run_async(self):
        """Run the app asynchronously."""
        await self._process_messages()
