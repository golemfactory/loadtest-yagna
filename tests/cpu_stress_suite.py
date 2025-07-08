import hashlib
import os
import random
from typing import AsyncGenerator, List

from yapapi import Task, WorkContext
from yapapi.payload import vm
from yapapi.script import Script

from loadtest_framework.suites.base_suite import BaseSuite


def calculate_hash(start_string: str, iterations: int) -> str:
    """Calculates a chain of SHA-256 hashes."""
    current_hash = hashlib.sha256(start_string.encode()).hexdigest()
    for _ in range(iterations - 1):
        current_hash = hashlib.sha256(current_hash.encode()).hexdigest()
    return current_hash


class CpuStressSuite(BaseSuite):
    """
    A test suite designed to stress the CPU of provider nodes.
    """

    def __init__(self, iterations: int = 100000):
        self.iterations = iterations
        # We will verify 10% of the tasks
        self.verification_sample_rate = 0.1

    async def get_payload(self):
        return await vm.repo(
            image_hash="9a3b5d67b0b27746283cb5f287c13eab1beaa12d92a9f536b747c7ae",
            min_mem_gib=0.5,
            min_storage_gib=2.0,
        )

    def get_tasks(self, num_tasks: int) -> List[Task]:
        """Generate tasks for the CPU stress suite."""
        tasks = []
        for i in range(num_tasks):
            task_data = {
                "task_id": i,
                "start_string": f"golem_{i}",
                "iterations": self.iterations,
            }
            tasks.append(Task(data=task_data))
        return tasks

    async def worker(self, context: WorkContext, tasks: AsyncGenerator[Task, None]):
        async for task in tasks:
            task_data = task.data
            start_string = task_data["start_string"]
            iterations = task_data["iterations"]

            # This script will be executed on the provider
            provider_script = f"""
import hashlib

def calculate_hash(start_string, iterations):
    current_hash = hashlib.sha256(start_string.encode()).hexdigest()
    for _ in range(iterations - 1):
        current_hash = hashlib.sha256(current_hash.encode()).hexdigest()
    return current_hash

result = calculate_hash('{start_string}', {iterations})
with open('/golem/output/result.txt', 'w') as f:
    f.write(result)
"""
            script: Script = context.new_script()
            script.run("/usr/bin/python3", "-c", provider_script)
            output_file = f"result_{task.id}.txt"
            script.download_file("/golem/output/result.txt", output_file)

            yield script

            with open(output_file, "r") as f:
                provider_result = f.read().strip()

            # Verify a sample of the results
            if random.random() < self.verification_sample_rate:
                expected_result = calculate_hash(start_string, iterations)
                if provider_result == expected_result:
                    task.accept_result(result=provider_result)
                else:
                    task.reject_task(
                        reason=f"Incorrect result: expected {expected_result}, got {provider_result}"
                    )
            else:
                # For tasks we don't verify, we just accept the result
                task.accept_result(result=provider_result)

            if os.path.exists(output_file):
                os.remove(output_file)