from abc import ABC, abstractmethod
from typing import AsyncGenerator, List
from yapapi import Task
from yapapi.payload import Payload
from yapapi import WorkContext


class BaseSuite(ABC):
    """
    An abstract base class for creating test suites.

    This class defines the essential components that every test suite must implement
    to be compatible with the load testing framework.
    """

    @abstractmethod
    async def get_payload(self) -> Payload:
        """
        Defines the Yapapi payload for the test suite.

        This method should create and return a `yapapi.payload.vm.Payload`
        configured with the required image hash and resource constraints.
        """
        pass

    @abstractmethod
    def get_tasks(self, num_tasks: int) -> List[Task]:
        """
        Generates the list of tasks to be executed.

        :param num_tasks: The number of tasks to generate.
        :return: A list of `yapapi.Task` objects.
        """
        pass

    @abstractmethod
    async def worker(self, context: WorkContext, tasks: AsyncGenerator[Task, None]):
        """
        The worker function that processes tasks on the provider node.

        This function contains the core logic for executing a single task,
        handling its results, and managing its lifecycle.

        :param context: The `WorkContext` for the current provider.
        :param tasks: An asynchronous generator yielding tasks to be processed.
        """
        pass