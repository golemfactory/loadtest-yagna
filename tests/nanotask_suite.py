import os
from typing import AsyncGenerator, List

from yapapi import Task, WorkContext
from yapapi.payload import vm
from yapapi.script import CaptureContext, Script

from loadtest_framework.suites.base_suite import BaseSuite


class NanoTaskSuite(BaseSuite):
    """
    A test suite for running a simple shell command on provider nodes.
    """

    async def get_payload(self):
        return await vm.repo(
            image_hash="9a3b5d67b0b27746283cb5f287c13eab1beaa12d92a9f536b747c7ae",
            min_mem_gib=0.5,
            min_storage_gib=2.0,
        )

    def get_tasks(self, num_tasks: int) -> List[Task]:
        """Generate tasks for the nanotask suite."""
        return [Task(data=i) for i in range(num_tasks)]

    async def worker(self, context: WorkContext, tasks: AsyncGenerator[Task, None]):
        async for task in tasks:
            script: Script = context.new_script()
            future_result = script.run(
                "/bin/sh",
                "-c",
                "echo $((2+9))",
                stdout=CaptureContext.build(fmt="str"),
            )
            yield script

            result = (await future_result).stdout.strip()

            if result == "11":
                task.accept_result(result=result)
            else:
                task.reject_task(reason=f"Incorrect result: expected 11, got {result}")