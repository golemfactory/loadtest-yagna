import os
import logging
import threading
import time
from prometheus_client import CollectorRegistry, push_to_gateway, Counter, Gauge, Histogram, Summary, Enum, disable_created_metrics

# Prometheus Push Gateway constants
PUSHGATEWAY_HOST = os.getenv("PUSHGATEWAY_HOST", "metrics.golem.network")
PUSHGATEWAY_PORT = os.getenv("PUSHGATEWAY_PORT", "9092")
PUSHGATEWAY_BASE_URL = f"https://{PUSHGATEWAY_HOST}:{PUSHGATEWAY_PORT}"
JOB_NAME = os.getenv("JOB_NAME", "golembase-AR")
INSTANCE_ID = os.getenv("INSTANCE_ID", None)
DEFAULT_PUSH_INTERVAL = 5  # Default interval in seconds for pushing metrics

# Global metrics instance
_metrics_instance = None


def get_metrics():
    """Get the global metrics instance"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = Metrics()
        logging.info("Created new metrics instance")
    return _metrics_instance


def reset_global_metrics():
    """Reset the global metrics instance - stops current instance and creates a new one"""
    global _metrics_instance
    if _metrics_instance:
        _metrics_instance.stop_push_task()
        logging.info("Stopped previous metrics instance")
    _metrics_instance = get_metrics()  # Create new instance
    

class Metrics:
    """
    A class to handle Prometheus metrics collection and pushing to push gateway
    """
    
    def __init__(self, instance_id: str = None, push_interval: int = DEFAULT_PUSH_INTERVAL):
        """
        Initialize the Metrics class
        
        Args:
            instance_id: Instance ID for metrics (defaults to INSTANCE_ID constant)
            push_interval: Interval in seconds for pushing metrics to gateway (defaults to 5)
        """
        self.job_name = JOB_NAME
        self.instance_id = instance_id or INSTANCE_ID
        self.push_interval = push_interval
        self.registry = CollectorRegistry()
        self._stop_event = threading.Event()
        self._push_thread = None
        self._initialized = False

        disable_created_metrics()
        
        # Initialize common metrics
        self._init_metrics()
    
    def initialize(self, instance_id: str = None, push_interval: int = DEFAULT_PUSH_INTERVAL):
        """
        Initialize the Metrics instance with new parameters and start background threads.
        This should only be called once per application run.
        
        Args:
            instance_id: Instance ID for metrics (defaults to INSTANCE_ID constant)
            push_interval: Interval in seconds for pushing metrics to gateway (defaults to 5)
        """
        self.instance_id = instance_id or INSTANCE_ID
        self.push_interval = push_interval

        if self._initialized:
            return
        
        # Start the background task
        self._start_push_task()
        self._initialized = True
    
    def _init_metrics(self):
        """Initialize common metrics for Yagna load testing"""
        
        # Demand metrics
        self.demands_sent = Counter(
            'loadtest_demands_sent',
            'Total number of demands sent',
            ['userId'],
            registry=self.registry
        )
        
        # Rejection metrics
        self.proposals_rejected = Counter(
            'loadtest_proposals_rejected',
            'Total number of proposals rejected aggregated by Reason',
            ['reason', 'userId'],
            registry=self.registry
        )
        
        # Proposal state metrics
        self.proposals_by_state = Counter(
            'loadtest_proposals_by_state',
            'Total number of proposals by state',
            ['state', 'userId'],
            registry=self.registry
        )
        
        # Agreement metrics
        self.agreements_proposed = Counter(
            'loadtest_agreements_proposed',
            'Total number of agreements proposed',
            ['userId'],
            registry=self.registry
        )
        
        self.agreements_created = Counter(
            'loadtest_agreements_created',
            'Total number of agreements successfully created',
            ['userId'],
            registry=self.registry
        )
        
        self.agreements_terminated = Counter(
            'loadtest_agreements_terminated',
            'Total number of agreements terminated',
            ['userId'],
            registry=self.registry
        )
        
        # Task metrics
        self.task_count = Gauge(
            'loadtest_task_count',
            'Current number of active tasks',
            registry=self.registry
        )
        self.task_count.set(0)
        
        self.task_computation_time = Histogram(
            'loadtest_task_computation_time_seconds',
            'Time taken to compute tasks in seconds',
            ['userId'],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0],
            registry=self.registry
        )
        
        self.running_time_percentage = Histogram(
            'loadtest_running_time_percentage',
            'Percentage of maximum running time actually used (0-100)',
            ['userId'],
            buckets=[10, 25, 50, 75, 90, 95, 100],
            registry=self.registry
        )
        
        # Load test status metric
        self.loadtest_running = Enum(
            'loadtest_status',
            'Current status of the load test',
            states=['stopped', 'running'],
            registry=self.registry
        )
        self.loadtest_running.state('stopped')  # Start as stopped
        
        # Current user count metric
        self.current_user_count = Gauge(
            'loadtest_current_user_count',
            'Current number of active users in the load test',
            registry=self.registry
        )
        self.current_user_count.set(0)  # Start with 0 users
    
    def _start_push_task(self):
        """Start the background task for periodic metric pushing"""
        self._push_thread = threading.Thread(target=self._push_metrics_loop, daemon=True)
        self._push_thread.start()
        logging.info(f"Started background metrics push task with {self.push_interval}s interval")
    
    def _push_metrics_loop(self):
        """Background loop for pushing metrics at regular intervals"""
        while not self._stop_event.is_set():
            try:
                self.push_metrics()
                # Wait for the specified interval or until stop event is set
                self._stop_event.wait(self.push_interval)
            except Exception as e:
                logging.error(f"Error in metrics push loop: {e}")
                # Wait a bit before retrying
                self._stop_event.wait(5)
    
    def stop_push_task(self):
        """Stop the background metrics push task"""
        if self._push_thread and self._push_thread.is_alive():
            self._stop_event.set()
            self._push_thread.join(timeout=5)
            logging.info("Stopped background metrics push task")
    
    def record_demand_sent(self, userId: str):
        """Record a demand sent"""
        self.demands_sent.labels(userId=userId).inc()
    
    def record_proposal_rejection(self, reason: str, userId: str):
        """Record a proposal rejection with reason"""
        self.proposals_rejected.labels(reason=reason, userId=userId).inc()
    
    def record_proposals_by_state(self, proposals: list, userId: str):
        """Record the number of proposals by their individual states"""
        state_counts = {}
        for proposal in proposals:
            if hasattr(proposal, 'proposal') and hasattr(proposal.proposal, 'state'):
                state = proposal.proposal.state
                state_counts[state] = state_counts.get(state, 0) + 1
        
        for state, count in state_counts.items():
            self.proposals_by_state.labels(state=state, userId=userId).inc(count)
    
    def report_proposal_rejection(self, proposals: list, userId: str):
        """Report proposal rejections from a list of proposals"""
        for proposal in proposals:
            if hasattr(proposal, 'event_type') and proposal.event_type == "ProposalEvent":
                if hasattr(proposal, 'proposal') and hasattr(proposal.proposal, 'state') and proposal.proposal.state == "Rejected":
                    # Record rejection with reason
                    reason = proposal.proposal.reason if hasattr(proposal.proposal, 'reason') else "unknown"
                    self.record_proposal_rejection(reason, userId)
    
    def record_agreement_proposed(self, userId: str):
        """Record an agreement being proposed"""
        self.agreements_proposed.labels(userId=userId).inc()
    
    def record_agreement_created(self, userId: str):
        """Record an agreement being successfully created"""
        self.agreements_created.labels(userId=userId).inc()
    
    def record_agreement_terminated(self, userId: str):
        """Record an agreement being terminated"""
        self.agreements_terminated.labels(userId=userId).inc()
    
    def increment_task_count(self):
        """Increment the task count gauge"""
        self.task_count.inc()
    
    def decrement_task_count(self):
        """Decrement the task count gauge"""
        self.task_count.dec()
    
    def record_task_metrics(self, expected_seconds: float, actual_seconds: float, userId: str):
        """Record both task computation time and running time percentage"""
        if expected_seconds > 0:
            # Record task computation time
            self.task_computation_time.labels(userId=userId).observe(actual_seconds)
            # Record running time percentage
            percentage_used = (actual_seconds / expected_seconds) * 100
            self.running_time_percentage.labels(userId=userId).observe(percentage_used)
    
    def push_metrics(self, grouping_key: dict = None):
        """
        Push metrics to Prometheus Push Gateway
        
        Args:
            grouping_key: Dictionary of labels for grouping metrics
        """
        # Don't push metrics if instance_id is not set
        if self.instance_id is None:
            logging.debug("Skipping metrics push - instance_id not set")
            return
            
        try:
            # Use push gateway URL with job name in path
            push_url = f"{PUSHGATEWAY_BASE_URL}"
            
            # Set default grouping key with instance and hostname
            default_grouping_key = {
                "job": f"{self.job_name}",
                "instance": f"{self.instance_id}",
                "hostname": f"locust-{self.instance_id}"
            }
            
            # Merge with provided grouping key
            final_grouping_key = {**default_grouping_key, **(grouping_key or {})}
            
            push_to_gateway(
                push_url,
                job=self.job_name,
                registry=self.registry,
                grouping_key=final_grouping_key
            )
            logging.debug(f"Metrics pushed to {push_url} for job: {self.job_name}")
        except Exception as e:
            logging.error(f"Failed to push metrics to {push_url}: {e}")
    
    def get_registry(self):
        """Get the CollectorRegistry instance"""
        return self.registry
    
    def set_loadtest_status(self, status: str):
        """Set the load test status"""
        if status in ['stopped', 'running']:
            self.loadtest_running.state(status)
            logging.info(f"Load test status set to: {status}")
        else:
            logging.warning(f"Invalid load test status: {status}. Valid states: stopped, running")
        return self.registry
    
    def update_user_count(self, environment):
        """Update the current user count from Locust environment"""
        user_count = environment.runner.user_count
        self.current_user_count.set(user_count)
        