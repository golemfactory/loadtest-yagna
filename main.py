#!/usr/bin/env python3
import argparse
import asyncio
import json
from datetime import datetime
from importlib import import_module
import os

from loadtest_framework.analysis.analyzer import analyze_results
from loadtest_framework.core.runner import run_suite
from loadtest_framework.suites.base_suite import BaseSuite
from loadtest_framework.core.tui import TUI
from utils import (
    build_parser,
    console,
    TEXT_COLOR_RED,
)


def main():
    parser = build_parser("Golem Load Testing Framework")
    parser.add_argument(
        "suites",
        nargs="*",
        help="The test suites to run (e.g., tests.nanotask_suite.NanoTaskSuite)",
    )
    parser.add_argument("--num-tasks", type=int, help="Number of tasks to run")
    parser.add_argument(
        "--max-workers", type=int, help="Maximum number of providers to use"
    )
    parser.add_argument(
        "--analyze-only",
        type=str,
        metavar="RESULTS_FILE",
        help="Skip running a test and only analyze an existing results file.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        help="Number of iterations for CPU stress test",
    )

    args = parser.parse_args()

    if args.analyze_only:
        console.print(f"--- Running Analysis on {args.analyze_only} ---")
        try:
            analyze_results(args.analyze_only)
        except Exception as e:
            console.print(
                f"[bold red]Error running analysis: {e}[/bold red]"
            )
        return

    all_results_dir = f"run_all_{datetime.now().strftime('%Y-%m-%d_%H.%M.%S')}"
    os.makedirs(all_results_dir, exist_ok=True)

    suites_to_run = args.suites
    if not suites_to_run:
        console.print(
            "[yellow]No test suites specified. Running all available suites.[/yellow]"
        )
        suites_to_run = []
        for filename in os.listdir("tests"):
            if filename.endswith("_suite.py"):
                module_name = filename[:-3]
                suites_to_run.append(f"tests.{module_name}")

    for suite_path in suites_to_run:
        try:
            suite_class = None
            module_path = suite_path
            try:
                # First, assume suite_path is a module path e.g. tests.nanotask_suite
                suite_module = import_module(suite_path)
                for name, obj in suite_module.__dict__.items():
                    try:
                        if issubclass(obj, BaseSuite) and obj is not BaseSuite:
                            suite_class = obj
                            break
                    except TypeError:
                        continue
            except ImportError:
                # If import fails, assume it's module.Class format e.g. tests.nanotask_suite.NanoTaskSuite
                module_path, class_name = suite_path.rsplit(".", 1)
                suite_module = import_module(module_path)
                suite_class = getattr(suite_module, class_name)

            if not suite_class:
                raise ImportError(
                    f"Could not find a BaseSuite subclass in {module_path}"
                )


            # Load settings from JSON file
            suite_base_name = module_path.rsplit(".", 1)[-1]
            settings_path = os.path.join(
                os.path.dirname(suite_module.__file__), f"{suite_base_name}.json"
            )
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            else:
                settings = {}

            # Prioritize CLI args over settings file
            num_tasks = args.num_tasks or settings.get("num_tasks", 10)
            max_workers = args.max_workers or settings.get("max_workers", 6)
            iterations = args.iterations or settings.get("iterations", 100000)

            if "CpuStressSuite" in suite_class.__name__:
                suite_instance = suite_class(iterations=iterations)
            else:
                suite_instance = suite_class()

        except (ImportError, AttributeError) as e:
            console.print(
                f"[bold red]Could not find or import the specified suite: {suite_path}[/bold red]"
            )
            console.print(f"Error: {e}")
            continue

        console.print(f"\n--- Running suite: [bold cyan]{suite_class.__name__}[/bold cyan] ---")
        console.print("  [bold]Settings:[/bold]")
        console.print(f"    - num_tasks: {num_tasks}")
        console.print(f"    - max_workers: {max_workers}")
        if "CpuStressSuite" in suite_class.__name__:
            console.print(f"    - iterations: {iterations}")
            console.print("----------------------------------------")
    
            app = TUI()
            run_suite_coro = run_suite(
                suite=suite_instance,
                subnet_tag=args.subnet_tag,
                payment_driver=args.payment_driver,
                payment_network=args.payment_network,
                num_tasks=num_tasks,
                max_workers=max_workers,
                output_dir_prefix=all_results_dir,
                app=app,
            )
            app.run_suite_coro = run_suite_coro
            app.run()


if __name__ == "__main__":
    main()