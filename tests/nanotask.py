import os
import logging.config
from datetime import datetime, timedelta
import math
import logging
import time
import uuid
import threading

from locust import task, between, events

from yagna import YagnaHttpUser
from utils import prepare_demand, get_formatted_timestamp, calculate_budget
from metrics import get_metrics, reset_global_metrics

# Global user counter for controlled delay distribution
user_counter = 0

def reset_user_counter():
    global user_counter
    user_counter = 0

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    reset_user_counter()
    reset_global_metrics()
    metrics = get_metrics()
    metrics.set_loadtest_status('running')

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    reset_user_counter()
    metrics = get_metrics()
    if metrics:
        metrics.set_loadtest_status('stopped')

class YagnaRequestor(YagnaHttpUser):
    wait_time = between(10, 30)
    maxStartPrice = 0.5
    maxCpuPerHourPrice = 1
    maxEnvPerHourPrice = 0.5
    lasting = float(os.getenv("RENT_TIME", 30 * 60))
    payment_platform = os.getenv("PAYMENT_PLATFORM", "erc20-polygon-glm")
    margin = float(os.getenv("MARGIN", 2 * 60))
    user_delay = float(os.getenv("USER_DELAY", 5.0))  # Delay in seconds between user starts

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debit_note_thread = None
        self.stop_debit_notes_tracking = threading.Event()
        logging.config.dictConfig({
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default"
                },
                "file": {
                    "class": "logging.FileHandler",
                    "formatter": "default",
                    "filename": "load_test.log"
                }
            },
            "root": {"handlers": ["console", "file"], "level": "INFO"}
        })

    def _stop_debit_note_thread(self):
        """Stop the debit note handling thread."""
        if self.debit_note_thread and self.debit_note_thread.is_alive():
            logging.info("Stopping debit note thread")
            self.stop_debit_notes_tracking.set()
            self.debit_note_thread.join(timeout=5)
            if self.debit_note_thread.is_alive():
                logging.warning("Debit note thread did not stop gracefully")

    def on_stop(self):
        """
        Called when the user stops. Ensures debit note thread is stopped.
        
        This method is part of Locust's User class lifecycle and is automatically
        called when a simulated user stops running. See:
        https://docs.locust.io/en/stable/writing-a-locustfile.html#on-start-and-on-stop-methods
        """
        logging.info("on_stop called - cleaning up debit note thread")
        self._stop_debit_note_thread()

    def _delay_user_start(self):
        """Add a calculated delay based on user counter to spread out user execution over time."""
        global user_counter
        if self.user_delay > 0:
            # Calculate delay based on user counter
            delay = user_counter * self.user_delay
            user_counter += 1
            logging.info(f"Delaying user start by {delay:.2f} seconds (user #{user_counter}) to spread execution")
            time.sleep(delay)

    def _start_debit_note_thread(self, agreement_id: str, allocation_id: str):
        """Start the debit note handling thread."""
        self.stop_debit_notes_tracking.clear()
        self.debit_note_thread = threading.Thread(
            target=self._handle_debit_notes,
            args=(agreement_id, allocation_id),
            daemon=True
        )
        self.debit_note_thread.start()
        logging.info("Started debit note handling thread")

    def _handle_debit_notes(self, agreement_id: str, allocation_id: str):
        """Handle debit notes in a separate thread."""
        while not self.stop_debit_notes_tracking.is_set():
            try:
                debit_notes = self.get_debit_notes(agreement_id=agreement_id, after_timestamp=get_formatted_timestamp(shift=-self.lasting))
                if debit_notes:
                    logging.info(f"Debit notes: {debit_notes}")
                    for debit_note in debit_notes:
                        if self.stop_debit_notes_tracking.is_set():
                            break
                        if self.accept_debit_note(debit_note["debitNoteId"], debit_note["totalAmountDue"], allocation_id):
                            logging.info(f"Accepted debit note {debit_note['debitNoteId']}")
                        else:
                            logging.error(f"Failed to accept debit note {debit_note['debitNoteId']}")
                            break
            except Exception as e:
                logging.error(f"Error handling debit notes: {e}")
            
            # Wait with timeout to allow checking stop event
            self.stop_debit_notes_tracking.wait(timeout=0.5)

    @task
    def run_test_flow(self):
        try:
            # Add calculated delay to spread out user execution over time to avoid failures
            # due to overloading yagna with requests.
            self._delay_user_start()
            
            # Create new user ID for this task run
            self.userId = str(uuid.uuid4())
            self.metrics.update_user_count(self.environment)
            logging.info(f"Starting new task with User ID: {self.userId}")
        
            # get profile
            profile = self.get_profile()
            self.metrics.initialize(instance_id=profile.identity)

            # create allocation
            allocation_id = self.create_allocation(
                amount=calculate_budget(self.maxStartPrice, self.maxCpuPerHourPrice, self.maxEnvPerHourPrice, self.lasting), 
                payment_platform=self.payment_platform,
                address=profile.identity,
                timeout=self.lasting + self.margin)
            if allocation_id is None:
                logging.error("Failed to create allocation")
                return
            logging.info(f"Allocation id: {allocation_id}")

            # prepare demand
            expiration = math.floor((datetime.now() + timedelta(seconds=self.lasting + self.margin)).timestamp() * 1000)
            demand = prepare_demand(
                sender_address=profile.identity,
                expiration=expiration,
                subnet="public",
                payment_platform=self.payment_platform
            )
            subscription_id = self.send_demand(demand)
            logging.info(f"Subscription id: {subscription_id}")

            # scan for proposals
            proposals = self.scan_for_proposals(subscription_id, "Initial")
            logging.info(f"Found {len(proposals)} proposals")

            # send counter offers - confirm our demand
            self.send_counter_offers(subscription_id, demand, proposals)
                
            # poll demand events
            proposals = self.scan_for_proposals(subscription_id, "Draft")
            logging.info(f"Found {len(proposals)} negotiated proposals")

            # arrange agreement
            agreement_id: str | None = self.arrange_agreement(proposals, expiration)
            if agreement_id is None:
                logging.error("Failed to arrange agreement")
                self.clear_all(subscription_id, agreement_id, allocation_id)
                return
            self.metrics.increment_task_count()
            logging.info(f"Arranged agreement id: {agreement_id}")

            # create activity
            activity_id: str | None = self.create_activity(agreement_id)
            if activity_id is None:
                logging.error("Failed to create activity")
                self.clear_all(subscription_id, agreement_id, allocation_id, "ActivityCreationFailed")
                return
            logging.info(f"Created activity id: {activity_id} for agreement {agreement_id}")

            # launch VM and wait for it to be ready
            if not self.prepare_vm_for_activity(activity_id):
                logging.error(f"Failed to prepare VM for activity {activity_id}")
                self.clear_all(subscription_id, agreement_id, allocation_id, "VmDeploymentFailed")
                return

            # Start debit note handling thread
            self._start_debit_note_thread(agreement_id, allocation_id)

            # execute activity in a loop till lasting time is over
            start_time = time.time()
            reason = "Success"
            while time.time() - start_time < self.lasting:
                try:
                    result = self.execute_activity(activity_id, "echo $((2+9))")
                    logging.info(f"Activity {activity_id} result: {result}")
                except Exception as e:
                    logging.error(f"Failed to execute activity {activity_id}: {e}")
                    reason = "ActivityExecutionFailed"
                    break
                time.sleep(0.5)

            # Stop debit note thread
            self._stop_debit_note_thread()

            # clear all
            self.metrics.record_task_metrics(self.lasting, time.time() - start_time, self.userId)
            self.clear_all(subscription_id, agreement_id, allocation_id, reason)
            
        finally:
            # Ensure debit note thread is stopped
            self._stop_debit_note_thread()
            # Update user count at task end
            self.metrics.update_user_count(self.environment)
