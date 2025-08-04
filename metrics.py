import os
import logging
import threading
import time
from prometheus_client import CollectorRegistry, push_to_gateway, Counter, Gauge, Histogram, Summary, disable_created_metrics

# Prometheus Push Gateway constants
PUSHGATEWAY_HOST = os.getenv("PUSHGATEWAY_HOST", "metrics.golem.network")
PUSHGATEWAY_PORT = os.getenv("PUSHGATEWAY_PORT", "9092")
PUSHGATEWAY_BASE_URL = f"https://{PUSHGATEWAY_HOST}:{PUSHGATEWAY_PORT}"
JOB_NAME = os.getenv("JOB_NAME", "golembase-AR")
INSTANCE_ID = os.getenv("INSTANCE_ID", "0xf98bb0842a7e744beedd291c98e7cd2c9b27f300")


class Metrics:
    """
    A class to handle Prometheus metrics collection and pushing to push gateway
    """
    
    def __init__(self, instance_id: str = None, push_interval: int = 30):
        """
        Initialize the Metrics class
        
        Args:
            instance_id: Instance ID for metrics (defaults to INSTANCE_ID constant)
            push_interval: Interval in seconds for pushing metrics to gateway (defaults to 30)
        """
        self.job_name = JOB_NAME
        self.instance_id = instance_id or INSTANCE_ID
        self.push_interval = push_interval
        self.registry = CollectorRegistry()
        self._stop_event = threading.Event()
        self._push_thread = None

        disable_created_metrics()
        
        # Initialize common metrics
        self._init_metrics()
    
    def initialize(self, instance_id: str = None, push_interval: int = 30):
        """
        Initialize the Metrics instance with new parameters
        
        Args:
            instance_id: Instance ID for metrics (defaults to INSTANCE_ID constant)
            push_interval: Interval in seconds for pushing metrics to gateway (defaults to 30)
        """
        self.instance_id = instance_id or INSTANCE_ID
        self.push_interval = push_interval
        
        # Restart the background task with new interval
        self.stop_push_task()
        self._start_push_task()
    
    def _init_metrics(self):
        """Initialize common metrics for Yagna load testing"""
        
        # Demand metrics
        self.demands_sent = Counter(
            'loadtest_demands_sent',
            'Total number of demands sent',
            registry=self.registry
        )
        
        # Rejection metrics
        self.proposals_rejected = Counter(
            'loadtest_proposals_rejected',
            'Total number of proposals rejected aggregated by Reason',
            ['reason'],
            registry=self.registry
        )
        
        # Proposal state metrics
        self.proposals_by_state = Counter(
            'loadtest_proposals_by_state',
            'Total number of proposals by state',
            ['state'],
            registry=self.registry
        )
    
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
    
    def record_demand_sent(self):
        """Record a demand sent"""
        self.demands_sent.inc()
    
    def record_proposal_rejection(self, reason: str):
        """Record a proposal rejection with reason"""
        self.proposals_rejected.labels(reason=reason).inc()
    
    def record_proposals_by_state(self, proposals: list):
        """Record the number of proposals by their individual states"""
        state_counts = {}
        for proposal in proposals:
            if hasattr(proposal, 'proposal') and hasattr(proposal.proposal, 'state'):
                state = proposal.proposal.state
                state_counts[state] = state_counts.get(state, 0) + 1
        
        for state, count in state_counts.items():
            self.proposals_by_state.labels(state=state).inc(count)
    
    def report_proposal_rejection(self, proposals: list):
        """Report proposal rejections from a list of proposals"""
        for proposal in proposals:
            if hasattr(proposal, 'event_type') and proposal.event_type == "ProposalEvent":
                if hasattr(proposal, 'proposal') and hasattr(proposal.proposal, 'state') and proposal.proposal.state == "Rejected":
                    # Record rejection with reason
                    reason = proposal.proposal.reason if hasattr(proposal.proposal, 'reason') else "unknown"
                    self.record_proposal_rejection(reason)
    
    def push_metrics(self, grouping_key: dict = None):
        """
        Push metrics to Prometheus Push Gateway
        
        Args:
            grouping_key: Dictionary of labels for grouping metrics
        """
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
            logging.info(f"Metrics pushed to {push_url} for job: {self.job_name}")
        except Exception as e:
            logging.error(f"Failed to push metrics to {push_url}: {e}")
    
    def get_registry(self):
        """Get the CollectorRegistry instance"""
        return self.registry 