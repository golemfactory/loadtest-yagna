import asyncio
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Callable

from yapapi import Golem
from yapapi.events import Event
from yapapi.log import enable_default_logger

from loadtest_framework.analysis.analyzer import analyze_results
from loadtest_framework.core.event_collector import (
    clear_events_log,
    event_consumer,
    get_events_log,
)
from loadtest_framework.core.tui import TUI
from loadtest_framework.suites.base_suite import BaseSuite
from utils import (
    print_env_info,
    TEXT_COLOR_CYAN,
    TEXT_COLOR_DEFAULT,
)


from loadtest_framework.core.tui import YapapiEvent


def tui_event_consumer(app: TUI) -> Callable[[Event], None]:
    """
    Creates an event consumer that updates the Textual UI.
    """
    def consumer(event: Event):
        event_consumer(event)  # Call the original event consumer
        app.post_message(YapapiEvent(event))

    return consumer


async def run_suite(
    suite: BaseSuite,
    subnet_tag: str,
    payment_driver: str,
    payment_network: str,
    num_tasks: int,
    max_workers: int,
    output_dir_prefix: str = None,
    app: "TUI" = None,
):
    """Runs a given test suite."""
    clear_events_log()
    payload = await suite.get_payload()
    tasks = suite.get_tasks(num_tasks)

    # TODO: Make timeout configurable
    init_overhead = 3
    min_timeout, max_timeout = 6, 30
    timeout = timedelta(
        minutes=max(min(init_overhead + len(tasks) * 2, max_timeout), min_timeout)
    )

    start_time = datetime.now()

    async with Golem(
        budget=10.0,
        subnet_tag=subnet_tag,
        payment_driver=payment_driver,
        payment_network=payment_network,
        event_consumer=tui_event_consumer(app),
    ) as golem:
        print_env_info(golem)

        get_events_log().append(
            {"event": "script_start", "timestamp": start_time.isoformat()}
        )

        completed_tasks_iterator = golem.execute_tasks(
            suite.worker,
            tasks,
            payload=payload,
            max_workers=max_workers,
            timeout=timeout,
        )

        completed_tasks_count = 0
        async for task in completed_tasks_iterator:
            completed_tasks_count += 1

        print(
            f"{TEXT_COLOR_CYAN}"
            f"{completed_tasks_count} tasks computed, total time: {datetime.now() - start_time}"
            f"{TEXT_COLOR_DEFAULT}"
        )

    if app:
        app.exit()

    get_events_log().append(
        {"event": "script_end", "timestamp": datetime.now().isoformat()}
    )

    suite_name = suite.__class__.__name__
    run_dir_name = f"run_{suite_name}_{start_time.strftime('%Y-%m-%d_%H.%M.%S')}"
    if output_dir_prefix:
        output_dir = os.path.join(output_dir_prefix, run_dir_name)
    else:
        output_dir = run_dir_name
    os.makedirs(output_dir, exist_ok=True)

    results_filename = os.path.join(output_dir, "events.json")
    with open(results_filename, "w") as f:
        json.dump(get_events_log(), f, indent=4)

    print(f"Event logs saved to {results_filename}")
    analyze_results(results_filename)
    return results_filename