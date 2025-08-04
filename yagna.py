import os
from datetime import datetime, timezone
import logging
import time

import dotenv
from locust import FastHttpUser

from model import ProposalEvent, Demand, Profile
from utils import get_formatted_timestamp
from metrics import Metrics

dotenv.load_dotenv()

class YagnaHttpUser(FastHttpUser):
    abstract = True
    token = os.getenv("YAGNA_TOKEN")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = Metrics()  # Create Metrics instance

    def get_profile(self):
        with self.rest("GET", "/me", headers={
            "Authorization": f"Bearer {self.token}"
        }) as response:
            logging.debug(response.json())
            profile = Profile(**response.json())
            return profile
    
    def scan_for_proposals(self, subscription_id: str, state: str) -> list[ProposalEvent]:
        proposals: list[ProposalEvent] = []
        while True:
            with self.rest("GET", f"/market-api/v1/demands/{subscription_id}/events?timeout={5 if state == 'Initial' else 20}", headers={
                "Authorization": f"Bearer {self.token}"
            }, name="/market-api/v1/demands/{subscription_id}/events" + f"({state})") as response:
                if response.status_code != 200:
                    logging.warning(f"Failed to scan for proposals: {response.content}, status code: {response.status_code}")
                    time.sleep(1)
                    continue
                last_proposals = response.json()
            logging.debug(f"Found {len(last_proposals)} proposals")
            logging.debug(f"Proposals: {last_proposals}")
            if last_proposals:
                proposals.extend([ProposalEvent(**p) for p in last_proposals])
            else:
                break
        proposals = [p for p in proposals if p.event_type == "ProposalEvent" and p.proposal.state == state]
        logging.info(f"Filtered {len(proposals)}")
        
        return proposals

    def send_counter_offers(self, subscription_id: str, demand: Demand, proposals: list[ProposalEvent]):
        for proposal in proposals:
            with self.rest("POST", f"/market-api/v1/demands/{subscription_id}/proposals/{proposal.proposal.proposal_id}", headers={
                "Authorization": f"Bearer {self.token}"}, json={
                    "properties": demand.properties,
                    "constraints": demand.constraints,
                }, name="/market-api/v1/demands/{subscription_id}/proposals/{proposal_id}") as response:
                if not response.ok:
                    logging.error(f"Failed to send counter offer for proposal {proposal.proposal.proposal_id}: {response.content}")
                    continue

    def send_demand(self, demand: Demand):
        logging.info(demand.model_dump(mode="json"))
        with self.rest("POST", "/market-api/v1/demands", json=demand.model_dump(mode="json"), headers={
            "Authorization": f"Bearer {self.token}"
        }) as response:
            logging.debug(response.request.body if response.request else "No request body")

            print(response.js)
            if not response.ok:
                logging.error(f"Failed to send demand: {response.content}, status code: {response.status_code}")
                raise Exception(f"Failed to send demand: {response.content}, status code: {response.status_code}")
            
            subscription_id: str = str(response.js)
            self.metrics.record_demand_sent()
            
            return subscription_id

    def delete_demand(self, subscription_id: str | None = None):
        if not subscription_id:
            return False
        response = self.client.delete(f"/market-api/v1/demands/{subscription_id}", headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/market-api/v1/demands/{subscription_id}")
        if not response.ok:
            logging.error(f"Failed to delete demand {subscription_id}: {response.content}")
            return False
        logging.info(f"Demand {subscription_id} deleted")
        return True

    def arrange_agreement(self, proposals: list[ProposalEvent], expiration: int):
        for proposal in proposals:
            # send agreement
            agreement = {
                "proposalId": proposal.proposal.proposal_id,
                "validTo": datetime.fromtimestamp(expiration / 1000).isoformat(timespec='milliseconds') + 'Z'
            }
            logging.debug(agreement)
            response = self.client.post(f"/market-api/v1/agreements", headers={
                "Authorization": f"Bearer {self.token}"}, json=agreement)
            
            if not response.ok:
                logging.error(f"Failed to send agreement for proposal {proposal.proposal.proposal_id}: {response.content}")
                continue
            else:
                # if agreement is accepted, get it for debugging, confirm and return agreement id
                agreement_id = str(response.json())
                logging.info(f"Agreement created for proposal {proposal.proposal.proposal_id} - {agreement_id}")
                response = self.client.get(f"/market-api/v1/agreements/{agreement_id}", headers={
                    "Authorization": f"Bearer {self.token}"
                }, name="/market-api/v1/agreements/{agreement_id}")
                logging.info(response.json())

                # confirm agreement
                response = self.client.post(f"/market-api/v1/agreements/{agreement_id}/confirm", headers={
                    "Authorization": f"Bearer {self.token}"
                }, name="/market-api/v1/agreements/{agreement_id}/confirm")
                if not response.ok:
                    logging.error(f"Failed to confirm agreement {agreement_id}")
                    continue

                # get agreement events
                logging.info(f"Agreement confirmed for proposal {proposal.proposal.proposal_id}. Waiting for approval on provider side.")

                response = self.client.post(f"/market-api/v1/agreements/{agreement_id}/wait?timeout=30", headers={
                    "Authorization": f"Bearer {self.token}"
                }, name="/market-api/v1/agreements/{agreement_id}/wait")
                if not response.ok:
                    logging.error(f"Failed to wait for agreement {agreement_id}")
                    continue

                logging.info(f"Agreement approved for proposal {proposal.proposal.proposal_id}, provider: {proposal.proposal.provider_id}, agreement: {agreement_id}")

                return agreement_id

    def terminate_agreement(self, agreement_id: str | None = None):
        if not agreement_id:
            return False
        response = self.client.post(f"/market-api/v1/agreements/{agreement_id}/terminate", headers={
            "Authorization": f"Bearer {self.token}"
        }, json={"message": "Finished task"}, name="/market-api/v1/agreements/{agreement_id}/terminate")
        if not response.ok:
            logging.error(f"Failed to terminate agreement {agreement_id}: {response.content}")
            return False
        logging.info(f"Agreement {agreement_id} terminated")
        return True

    def create_activity(self, agreement_id: str | None = None):
        if not agreement_id:
            return None
        response = self.client.post(f"/activity-api/v1/activity?timeout=10", headers={
            "Authorization": f"Bearer {self.token}",
        }, json={"agreementId": agreement_id})
        if not response.ok:
            logging.error(f"Failed to create activity for agreement {agreement_id}: {response.json()}")
            return None
        return response.json()["activityId"]

    def read_batch_output(self, activity_id: str, batch_id: str):
        response = self.client.get(f"/activity-api/v1/activity/{activity_id}/exec/{batch_id}", headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/activity-api/v1/activity/{activity_id}/exec/{batch_id}")
        if not response.ok:
            logging.error(f"Failed to get batch {batch_id}: {response.content}")
            return None
        return response.json()

    def _read_activity_state(self, activity_id: str):
        response = self.client.get(f"/activity-api/v1/activity/{activity_id}/state", headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/activity-api/v1/activity/{activity_id}/state")
        if not response.ok:
            logging.error(f"Failed to get activity {activity_id} state: {response.content}")
            return None
        return response.json()["state"]

    def prepare_vm_for_activity(self, activity_id: str, timeout: int = 30):
        start_time = time.time()
        with self.rest("POST", f"/activity-api/v1/activity/{activity_id}/exec", headers={
            "Authorization": f"Bearer {self.token}",
        }, 
        json={"text": '[{"deploy":{}},{"start":{}}]'},
        name="/activity-api/v1/activity/{activity_id}/exec") as response:
            if not response.ok:
                logging.error(f"Failed to prepare VM for activity {activity_id}: {response.content}")
                return False
            
            batch_id = str(response.json())
            logging.info(f"Batch id: {batch_id}")

            state = [None, None]
            while state and state[0] != "Ready":
                # read state of activity
                state = self._read_activity_state(activity_id)
                logging.info(f"Activity {activity_id} state: {state}")
                time.sleep(1)
                if time.time() - start_time > timeout:
                    logging.error(f"Timeout while preparing VM for activity {activity_id}")
                    return False
            
            return True

    def execute_activity(self, activity_id: str, script: str, timeout: int = 30):
        start_time = time.time()
        # then run script
        with self.rest("POST", f"/activity-api/v1/activity/{activity_id}/exec", headers={
            "Authorization": f"Bearer {self.token}",
        }, 
        json={"text": '[{"run":{"entry_point":"/bin/sh","args":["-c","' + script + '"],"capture":{"stdout":{"atEnd":{"format":"string"}},"stderr":{"atEnd":{"format":"string"}}}}}]'}, 
        name="/activity-api/v1/activity/{activity_id}/exec") as response:
            if not response.ok:
                logging.error(f"Failed to execute activity {activity_id}: {response.content}")
                raise Exception(f"Failed to execute activity {activity_id}: {response.content}")
            logging.info(f"Activity {activity_id} executed - {response.content}")
            batch_id = str(response.js)
            logging.info(f"Batch id: {batch_id}")

        while True:
            # read batch output
            output = self.read_batch_output(activity_id, batch_id)
            logging.info(f"Batch output: {output}")

            # read state of activity
            state = self._read_activity_state(activity_id)
            logging.info(f"Activity {activity_id} state: {state}")
            if state:
                if state[0] == "Terminated":
                    raise Exception(f"Activity {activity_id} terminated")
                if state[0] == "Ready" and output and output[0]["isBatchFinished"]:
                    break
                break
            time.sleep(1)
            if timeout and time.time() - start_time > timeout:
                logging.error(f"Timeout while executing activity {activity_id}")
                raise Exception(f"Timeout while executing activity {activity_id}")
        
        if output and output[0]["result"] == "Ok":
            return output[0]["stdout"]
        
        raise Exception(f"Failed to execute activity: {output}")

    def get_debit_notes(self, *, after_timestamp: str | None = None, agreement_id: str | None = None, status: str | None = "RECEIVED"):
        logging.info(f"Getting debit notes after {after_timestamp}")
        with self.rest("GET", "/payment-api/v1/debitNotes" + (f"?afterTimestamp={after_timestamp}" if after_timestamp else ""), headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/payment-api/v1/debitNotes") as response:
            if not response.ok:
                logging.error(f"Failed to get debit notes: {response.content}")
                return None
            logging.info(f"Debit notes: {len(response.js)}")
            logging.debug(response.js)

            result = [d for d in response.js if d["status"] == status]
            if agreement_id:
                return [d for d in result if d["agreementId"] == agreement_id]
            else:
                return result

    def accept_debit_note(self, debit_note_id: str, amount_accepted: str, allocation_id: str):
        response = self.client.post(f"/payment-api/v1/debitNotes/{debit_note_id}/accept", headers={
            "Authorization": f"Bearer {self.token}"
        }, json={"totalAmountAccepted": amount_accepted, "allocationId": allocation_id}, 
        name="/payment-api/v1/debitNotes/{debit_note_id}/accept")
        if not response.ok:
            logging.error(f"Failed to accept debit note {debit_note_id}: {response.content}")
            return False
        return True

    def create_allocation(self, amount: float, payment_platform: str, address: str, timeout: float = 10 * 60):
        with self.rest("POST", "/payment-api/v1/allocations", headers={
            "Authorization": f"Bearer {self.token}"
        }, json={
            "totalAmount": amount,
            "paymentPlatform": payment_platform,
            "address": address,
            "timestamp": get_formatted_timestamp(),
            "timeout": get_formatted_timestamp(shift=timeout),
            "makeDeposit": False,
            "remainingAmount": "",
            "spentAmount": "",
            "allocationId": "",
            "deposit": None,
        }, name="/payment-api/v1/allocations") as response:
            if not response.ok:
                logging.error(f"Failed to create allocation: {response.content}")
                return None
            logging.info(f"Allocation created: {response.js}")
            return response.js["allocationId"]
        
    def clear_allocation(self, allocation_id: str | None = None):
        if not allocation_id:
            return False
        response = self.client.delete(f"/payment-api/v1/allocations/{allocation_id}", headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/payment-api/v1/allocations/{allocation_id}")
        if not response.ok:
            logging.error(f"Failed to clear allocation {allocation_id}: {response.content}")
            return False
        logging.info(f"Allocation {allocation_id} cleared")
        return True

    def clear_all(self, subscription_id: str | None = None, agreement_id: str | None = None, allocation_id: str | None = None):
        self.delete_demand(subscription_id)
        self.terminate_agreement(agreement_id)
        self.clear_allocation(allocation_id)
