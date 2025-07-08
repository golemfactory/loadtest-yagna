from datetime import datetime
from yapapi import events
from rich.console import Console
 
console = Console()
events_log = []


def event_consumer(event: events.Event):
    """A generic event consumer that logs event data."""
    timestamp = datetime.now()
    event_data = {"event": event.__class__.__name__, "timestamp": timestamp.isoformat()}

    if isinstance(event, events.ProposalReceived):
        event_data.update({"provider_id": event.provider_id})
    elif isinstance(event, events.AgreementCreated):
        event_data.update(
            {
                "agr_id": event.agr_id,
                "provider_id": event.provider_id,
                "provider_name": event.provider_info.name,
            }
        )
    elif isinstance(event, events.TaskStarted):
        event_data.update({"task_id": event.task_id, "agr_id": event.agr_id})
    elif isinstance(event, events.TaskAccepted):
        event_data.update(
            {
                "task_id": event.task_id,
                "result": event.result,
            }
        )
    elif isinstance(event, events.TaskRejected):
        event_data.update(
            {
                "task_id": event.task_id,
                "reason": str(event.reason) if hasattr(event, "reason") else "No reason given",
            }
        )
    elif isinstance(event, events.WorkerFinished) and event.exc_info:
        event_data["event"] = "TaskFailed"
        event_data.update(
            {
                "activity_id": event.activity.id,
                "agr_id": event.agr_id,
                "reason": str(event.exception),
            }
        )
    elif isinstance(event, events.DebitNoteReceived):
        event_data.update({"agr_id": event.agr_id, "amount": str(event.amount)})
    elif isinstance(event, events.AgreementTerminated):
        event_data.update({"agr_id": event.agr_id, "reason": str(event.reason)})
    elif isinstance(event, events.WorkerStarted):
        event_data.update({"agr_id": event.agr_id})

    events_log.append(event_data)


def get_events_log():
    """Returns the collected events log."""
    return events_log


def clear_events_log():
    """Clears the events log."""
    global events_log
    events_log = []