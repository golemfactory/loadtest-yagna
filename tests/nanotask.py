import os
import logging.config
from datetime import datetime, timedelta
import math
import logging
import time

from locust import task, between

from yagna import YagnaHttpUser
from utils import prepare_demand, get_formatted_timestamp, calculate_budget

class YagnaRequestor(YagnaHttpUser):
    wait_time = between(10, 30)
    maxStartPrice = 0.5
    maxCpuPerHourPrice = 1
    maxEnvPerHourPrice = 0.5
    lasting = float(os.getenv("RENT_TIME", 10 * 60))
    payment_platform = os.getenv("PAYMENT_PLATFORM", "erc20-polygon-glm")
    margin = float(os.getenv("MARGIN", 2 * 60))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    @task
    def run_test_flow(self):
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
        logging.info(f"Arranged agreement id: {agreement_id}")

        # create activity
        activity_id: str | None = self.create_activity(agreement_id)
        if activity_id is None:
            logging.error("Failed to create activity")
            self.clear_all(subscription_id, agreement_id, allocation_id)
            return
        logging.info(f"Created activity id: {activity_id} for agreement {agreement_id}")

        # launch VM and wait for it to be ready
        if not self.prepare_vm_for_activity(activity_id):
            logging.error(f"Failed to prepare VM for activity {activity_id}")
            self.clear_all(subscription_id, agreement_id, allocation_id)
            return

        # execute activity in a loop till lasting time is over
        start_time = time.time()
        while time.time() - start_time < self.lasting:
            try:
                result = self.execute_activity(activity_id, "echo $((2+9))")
                logging.info(f"Activity {activity_id} result: {result}")
            except Exception as e:
                logging.error(f"Failed to execute activity {activity_id}: {e}")
                break
            debit_notes = self.get_debit_notes(agreement_id=agreement_id, after_timestamp=get_formatted_timestamp(shift=-self.lasting))
            if debit_notes:
                logging.info(f"Debit notes: {debit_notes}")
                for debit_note in debit_notes:
                    if self.accept_debit_note(debit_note["debitNoteId"], debit_note["totalAmountDue"], allocation_id):
                        logging.info(f"Accepted debit note {debit_note['debitNoteId']}")
                    else:
                        logging.error(f"Failed to accept debit note {debit_note['debitNoteId']}")
                        break
            time.sleep(0.5)

        # clear all
        self.clear_all(subscription_id, agreement_id, allocation_id)
