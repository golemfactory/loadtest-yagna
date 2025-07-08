import json
import os
from datetime import datetime
from decimal import Decimal, getcontext

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
 
console = Console()
 
 
def analyze_results(file_path):
    """
    Analyzes the results of a load test run.
    """
    getcontext().prec = 50

    with open(file_path, "r") as f:
        events = json.load(f)

    script_start_time, script_end_time = None, None
    proposals, agreements, tasks = {}, {}, {}
    debit_notes, terminations = [], {}
    provider_stats = {}

    for event in events:
        event_name = event.get("event")
        timestamp = datetime.fromisoformat(event.get("timestamp"))

        if event_name == "script_start":
            script_start_time = timestamp
        elif event_name == "script_end":
            script_end_time = timestamp
        elif event_name == "ProposalReceived":
            provider_id = event.get("provider_id")
            if provider_id not in proposals:
                proposals[provider_id] = timestamp
        elif event_name == "AgreementCreated":
            agr_id = event.get("agr_id")
            agreements[agr_id] = {
                "provider_id": event.get("provider_id"),
                "created_at": timestamp,
                "proposal_at": proposals.get(event.get("provider_id")),
                "provider_name": event.get("provider_name"),
            }
            provider_id = event.get("provider_id")
            if provider_id not in provider_stats:
                provider_stats[provider_id] = {
                    "name": event.get("provider_name"),
                    "tasks_run": 0,
                    "tasks_successful": 0,
                    "tasks_failed": 0,
                }
        elif event_name == "WorkerStarted":
            if (agr_id := event.get("agr_id")) in agreements:
                agreements[agr_id]["worker_started_at"] = timestamp
        elif event_name == "TaskStarted":
            task_id = event.get("task_id")
            agr_id = event.get("agr_id")
            tasks[task_id] = {"started_at": timestamp, "agr_id": agr_id}
            if agr_id in agreements:
                provider_id = agreements[agr_id]["provider_id"]
                if provider_id in provider_stats:
                    provider_stats[provider_id]["tasks_run"] += 1
        elif event_name == "TaskAccepted":
            if (task_id := event.get("task_id")) in tasks:
                tasks[task_id]["finished_at"] = timestamp
                tasks[task_id]["duration"] = (
                    timestamp - tasks[task_id]["started_at"]
                ).total_seconds()
                tasks[task_id]["result"] = event.get("result")
                agr_id = tasks[task_id].get("agr_id")
                if agr_id in agreements:
                    provider_id = agreements[agr_id]["provider_id"]
                    if provider_id in provider_stats:
                        provider_stats[provider_id]["tasks_successful"] += 1
        elif event_name in ["TaskRejected", "TaskFailed"]:
            if (task_id := event.get("task_id")) in tasks:
                tasks[task_id]["finished_at"] = timestamp
                tasks[task_id]["result"] = "Failed"
                agr_id = tasks[task_id].get("agr_id")
                if agr_id in agreements:
                    provider_id = agreements[agr_id]["provider_id"]
                    if provider_id in provider_stats:
                        provider_stats[provider_id]["tasks_failed"] += 1
        elif event_name == "DebitNoteReceived":
            debit_notes.append(Decimal(event["amount"]))
        elif event_name == "AgreementTerminated":
            reason = str(event.get("reason", "Unknown"))
            terminations[reason] = terminations.get(reason, 0) + 1

    if not script_start_time:
        console.print("[bold red]Error: Script start time not found in logs.[/bold red]")
        return
 
    # --- Calculations ---
    provider_to_agreement_times = [
        (data["created_at"] - data["proposal_at"]).total_seconds()
        for data in agreements.values()
        if data.get("proposal_at")
    ]
    script_to_agreement_times = [
        (data["created_at"] - script_start_time).total_seconds()
        for data in agreements.values()
    ]
    script_to_task_start_times = [
        (data["started_at"] - script_start_time).total_seconds()
        for data in tasks.values()
    ]
    task_durations = [
        data["duration"] for data in tasks.values() if "duration" in data
    ]
    provider_to_task_start_times = [
        (task_data["started_at"] - agreement["proposal_at"]).total_seconds()
        for task_id, task_data in tasks.items()
        if (agr_id := task_data.get("agr_id"))
        and (agreement := agreements.get(agr_id))
        and agreement.get("proposal_at")
    ]
    provider_setup_times = [
        (data["worker_started_at"] - data["created_at"]).total_seconds()
        for data in agreements.values()
        if "created_at" in data and "worker_started_at" in data
    ]

    total_duration = (
        (script_end_time - script_start_time).total_seconds() if script_end_time else None
    )
    successful_tasks = sum(
        1 for data in tasks.values() if data.get("result") != "Failed"
    )
    failed_tasks = len(tasks) - successful_tasks
    total_cost_gwei = sum(debit_notes)
    total_cost_glm = total_cost_gwei / Decimal("1e18")

    # --- Aggregation and Output ---
    output_dir = os.path.dirname(file_path)
    summary_path = os.path.join(output_dir, "summary.json")

    def get_stats_dict(data):
        if not data:
            return {
                "count": 0,
                "mean": None,
                "std": None,
                "min": None,
                "25%": None,
                "50%": None,
                "75%": None,
                "max": None,
            }
        return pd.Series(data).describe().to_dict()

    summary_data = {
        "analysis_info": {
            "analyzed_file": file_path,
            "total_script_duration_seconds": round(total_duration, 2)
            if total_duration is not None
            else None,
        },
        "task_results": {"successful": successful_tasks, "failed": failed_tasks},
        "cost_analysis": {
            "total_cost_glm": str(total_cost_glm),
            "total_cost_gwei": str(total_cost_gwei),
        },
        "agreement_health": {"termination_reasons": terminations},
        "provider_analysis": provider_stats,
        "performance_metrics": {
            "provider_found_to_agreement_seconds": get_stats_dict(
                provider_to_agreement_times
            ),
            "script_start_to_agreement_seconds": get_stats_dict(
                script_to_agreement_times
            ),
            "provider_setup_time_seconds": get_stats_dict(provider_setup_times),
            "script_start_to_task_start_seconds": get_stats_dict(
                script_to_task_start_times
            ),
            "task_execution_duration_seconds": get_stats_dict(task_durations),
            "provider_found_to_task_start_seconds": get_stats_dict(
                provider_to_task_start_times
            ),
        },
    }

    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=4)
    console.print(f"Analysis summary saved to [green]{summary_path}[/green]")
 
    # --- Rich Console Output ---
    console.print("\n[bold underline]Analysis Summary[/bold underline]")
 
    # Task Results
    table = Table(title="Task Results")
    table.add_column("Status", style="cyan")
    table.add_column("Count", style="magenta")
    table.add_row("Successful", str(successful_tasks))
    table.add_row("Failed", str(failed_tasks))
    console.print(table)
 
    # Cost Analysis
    table = Table(title="Cost Analysis")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("Total Cost (GLM)", f"{total_cost_glm:.18f}")
    console.print(table)
 
    # Provider Analysis
    table = Table(title="Provider Analysis")
    table.add_column("Provider ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Tasks Run", style="yellow")
    table.add_column("Tasks Successful", style="green")
    table.add_column("Tasks Failed", style="red")
    for provider_id, data in provider_stats.items():
        table.add_row(
            provider_id,
            data["name"],
            str(data["tasks_run"]),
            str(data["tasks_successful"]),
            str(data["tasks_failed"]),
        )
    console.print(table)
 
    # Performance Metrics
    table = Table(title="Performance Metrics (seconds)")
    table.add_column("Metric", style="cyan")
    table.add_column("Mean", style="magenta")
    table.add_column("Std Dev", style="yellow")
    table.add_column("Min", style="green")
    table.add_column("Median", style="blue")
    table.add_column("Max", style="red")
 
    for metric, stats in summary_data["performance_metrics"].items():
        if stats["count"] > 0:
            table.add_row(
                metric.replace("_seconds", "").replace("_", " ").title(),
                f"{stats['mean']:.2f}",
                f"{stats['std']:.2f}",
                f"{stats['min']:.2f}",
                f"{stats['50%']:.2f}",
                f"{stats['max']:.2f}",
            )
    console.print(table)
 
    # --- Charting ---
    fig, axs = plt.subplots(3, 2, figsize=(20, 18))
    fig.suptitle("Stress Test Performance Analysis", fontsize=16)

    def plot_boxplot(ax, data, title):
        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center")
            ax.set_title(title)
            ax.set_xlabel("Time (seconds)")
            return

        ax.boxplot(
            data,
            vert=False,
            patch_artist=True,
            boxprops=dict(facecolor="skyblue"),
            medianprops=dict(color="red", linewidth=2),
        )
        mean_val, median_val = np.mean(data), np.median(data)
        ax.axvline(
            mean_val, color="green", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.2f}s"
        )
        ax.axvline(
            median_val, color="red", linestyle="-", linewidth=2, label=f"Median: {median_val:.2f}s"
        )
        ax.set_title(title)
        ax.set_xlabel("Time (seconds)")
        ax.legend()

    plot_boxplot(
        axs[0, 0], provider_to_agreement_times, "Provider Found to Agreement Time"
    )
    plot_boxplot(axs[0, 1], script_to_agreement_times, "Script Start to Agreement Time")
    plot_boxplot(axs[1, 0], provider_setup_times, "Provider Setup Time")
    plot_boxplot(
        axs[1, 1], script_to_task_start_times, "Script Start to Task Start Time"
    )
    plot_boxplot(axs[2, 0], task_durations, "Task Execution Duration")

    if successful_tasks > 0 or failed_tasks > 0:
        axs[2, 1].pie(
            [successful_tasks, failed_tasks],
            labels=["Successful", "Failed"],
            autopct="%1.1f%%",
            colors=["lightgreen", "lightcoral"],
        )
        axs[2, 1].set_title("Task Success Rate")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    chart_filename = os.path.join(output_dir, "charts.png")
    plt.savefig(chart_filename)
    console.print(f"Charts saved to [green]{chart_filename}[/green]")