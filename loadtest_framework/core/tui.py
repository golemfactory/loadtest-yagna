from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Log
from textual.message import Message

from yapapi.events import (
    AgreementConfirmed,
    AgreementCreated,
    AgreementTerminated,
    ProposalReceived,
    TaskAccepted,
    TaskFinished,
    TaskRejected,
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

    def __init__(self):
        super().__init__()
        self.run_suite_coro = None
        self.providers_data = {}
        self.agreements_data = {}
        self.task_statuses = {"Initialized": 0, "Sent": 0, "Finished": 0}

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield DataTable(id="providers", zebra_stripes=True)
        yield DataTable(id="agreements", zebra_stripes=True)
        yield DataTable(id="tasks", zebra_stripes=True)
        yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        providers_table = self.query_one("#providers", DataTable)
        providers_table.add_columns("Provider ID", "Workers", "Network")

        agreements_table = self.query_one("#agreements", DataTable)
        agreements_table.add_columns("Agreement ID", "Provider ID", "Status", "Tasks")

        tasks_table = self.query_one("#tasks", DataTable)
        tasks_table.add_columns("Status", "Count")
        self.update_tasks_table()
        self.run_worker(self.run_suite_coro)

    def on_yapapi_event(self, message: YapapiEvent) -> None:
        """Called when a yapapi event is received."""
        event = message.event
        log = self.query_one("#log", Log)
        log.write_line(str(event))

        if isinstance(event, ProposalReceived):
            provider_id = event.provider_id
            if provider_id not in self.providers_data:
                self.providers_data[provider_id] = {"workers": "N/A", "network": "N/A"}
                self.update_providers_table()
        elif isinstance(event, AgreementCreated):
            agreement_id = event.agr_id
            provider_id = event.provider_id
            self.agreements_data[agreement_id] = {
                "provider_id": provider_id,
                "status": "Created",
                "tasks": 0,
            }
            self.update_agreements_table()
        elif isinstance(event, AgreementConfirmed):
            agreement_id = event.agr_id
            if agreement_id in self.agreements_data:
                self.agreements_data[agreement_id]["status"] = "Confirmed"
                self.update_agreements_table()
        elif isinstance(event, AgreementTerminated):
            agreement_id = event.agr_id
            if agreement_id in self.agreements_data:
                self.agreements_data[agreement_id]["status"] = "Terminated"
                self.update_agreements_table()
        elif isinstance(event, (TaskAccepted, TaskRejected, TaskFinished)):
            if isinstance(event, TaskFinished):
                self.task_statuses["Finished"] += 1
            elif isinstance(event, TaskAccepted):
                self.task_statuses["Sent"] += 1
            elif isinstance(event, TaskRejected):
                self.task_statuses["Initialized"] += 1
            self.update_tasks_table()

    def update_providers_table(self):
        table = self.query_one("#providers", DataTable)
        table.clear()
        for provider_id, data in self.providers_data.items():
            table.add_row(provider_id, data["workers"], data["network"])

    def update_agreements_table(self):
        table = self.query_one("#agreements", DataTable)
        table.clear()
        for agr_id, data in self.agreements_data.items():
            table.add_row(
                agr_id, data["provider_id"], data["status"], str(data["tasks"])
            )

    def update_tasks_table(self):
        table = self.query_one("#tasks", DataTable)
        table.clear()
        table.add_row("Initialized", str(self.task_statuses["Initialized"]))
        table.add_row("Sent", str(self.task_statuses["Sent"]))
        table.add_row("Finished", str(self.task_statuses["Finished"]))

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

