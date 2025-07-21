from datetime import datetime, timedelta
import math
import logging
import time

from locust import FastHttpUser, task, between

from utils import prepare_demand
from model import Profile, ProposalEvent, Proposal, Demand

class YagnaRequestor(FastHttpUser):
    wait_time = between(5, 10)
    token = "40e9a21742374c44aac956920a3882c7" 
    lasting = 30 * 60  # 30 minutes

    def scan_for_proposals(self, subscription_id: str, state: str) -> list[ProposalEvent]:
        proposals: list[ProposalEvent] = []
        while True:
            response = self.client.get(f"/market-api/v1/demands/{subscription_id}/events?timeout={5 if state == 'Initial' else 10}", headers={
                "Authorization": f"Bearer {self.token}"
            }, name="/market-api/v1/demands/{subscription_id}/events")
            if response.status_code != 200:
                logging.warning(f"Failed to scan for proposals: {response.content}, status code: {response.status_code}")
                continue
            last_proposals = response.json()
            logging.debug(f"Found {len(last_proposals)} proposals")
            if last_proposals:
                proposals.extend([ProposalEvent(**p) for p in last_proposals])
            else:
                break
        proposals = [p for p in proposals if p.event_type == "ProposalEvent" and p.proposal.state == state]
        logging.debug(f"Found {len(proposals)} proposals: {proposals}")
        
        return proposals

    def send_counter_offers(self, subscription_id: str, demand: Demand, proposals: list[ProposalEvent]):
        for proposal in proposals:
            response = self.client.post(f"/market-api/v1/demands/{subscription_id}/proposals/{proposal.proposal.proposal_id}", headers={
                "Authorization": f"Bearer {self.token}"}, json={
                    "properties": demand.properties,
                    "constraints": demand.constraints,
                }, name="/market-api/v1/demands/{subscription_id}/proposals/{proposal_id}")

            if not response.ok:
                logging.error(f"Failed to send counter offer for proposal {proposal.proposal.proposal_id}: {response.content}")
                continue

    def send_demand(self, demand: Demand):
        logging.info(demand.model_dump(mode="json"))
        response = self.client.post("/market-api/v1/demands", json=demand.model_dump(mode="json"), headers={
            "Authorization": f"Bearer {self.token}"
        })
        logging.debug(response.request.body if response.request else "No request body")

        print(response.json())
        if not response.ok:
            logging.error(f"Failed to send demand: {response.content}, status code: {response.status_code}")
            raise Exception(f"Failed to send demand: {response.content}, status code: {response.status_code}")
        
        subscription_id: str = str(response.json())
        return subscription_id

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

                logging.info(f"Agreement approved for proposal {proposal.proposal.proposal_id}")

                return agreement_id

    def create_activity(self, agreement_id: str):
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

    def read_activity_state(self, activity_id: str):
        response = self.client.get(f"/activity-api/v1/activity/{activity_id}/state", headers={
            "Authorization": f"Bearer {self.token}"
        }, name="/activity-api/v1/activity/{activity_id}/state")
        if not response.ok:
            logging.error(f"Failed to get activity {activity_id} state: {response.content}")
            return None
        return response.json()["state"]

    def execute_activity(self, activity_id: str, script: str):
        # first deploy VM
        response = self.client.post(f"/activity-api/v1/activity/{activity_id}/exec", headers={
            "Authorization": f"Bearer {self.token}",
        }, 
        json={"text": '[{"deploy":{}},{"start":{}}]'},
        name="/activity-api/v1/activity/{activity_id}/exec")
        if not response.ok:
            logging.error(f"Failed to execute activity {activity_id}: {response.content}")
            return None

        batch_id = str(response.json())
        logging.info(f"Batch id: {batch_id}")

        state = [None, None]
        while state and state[0] != "Ready":
            # read state of activity
            state = self.read_activity_state(activity_id)
            logging.info(f"Activity {activity_id} state: {state}")
            time.sleep(1)
            # TODO check timeout

        # then run script
        response = self.client.post(f"/activity-api/v1/activity/{activity_id}/exec", headers={
            "Authorization": f"Bearer {self.token}",
        }, 
        json={"text": '[{"run":{"entry_point":"/bin/sh","args":["-c","echo \\"Part #0 computed on provider testnet-golembase-3-HEL with CPU:\\" && cat /proc/cpuinfo | grep \'model name\'"],"capture":{"stdout":{"atEnd":{"format":"string"}},"stderr":{"atEnd":{"format":"string"}}}}}]'}, 
        name="/activity-api/v1/activity/{activity_id}/exec")
        if not response.ok:
            logging.error(f"Failed to execute activity {activity_id}: {response.content}")
            return None
        logging.info(f"Activity {activity_id} executed - {response.content}")
        batch_id = str(response.json())
        logging.info(f"Batch id: {batch_id}")

        while True:
            # read batch output
            output = self.read_batch_output(activity_id, batch_id)
            logging.info(f"Batch output: {output}")

            # read state of activity
            state = self.read_activity_state(activity_id)
            logging.info(f"Activity {activity_id} state: {state}")
            time.sleep(1)
        
        return str(response.content)

    @task
    def run_test_flow(self):
        # get profile
        response = self.client.get("/me", headers={
            "Authorization": f"Bearer {self.token}"
        })
        logging.debug(response.json())
        profile = Profile(**response.json())

        # prepare demand
        expiration = math.floor((datetime.now() + timedelta(seconds=self.lasting)).timestamp() * 1000)
        demand = prepare_demand(
            sender_address=profile.identity,
            expiration=expiration,
            subnet="public",
            payment_platform="erc20-polygon-glm"
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
            return
        logging.info(f"Agreement id: {agreement_id}")

        # create activity
        activity_id: str | None = self.create_activity(agreement_id)
        if activity_id is None:
            logging.error("Failed to create activity")
            return
        logging.info(f"Activity id: {activity_id}")

        # execute activity
        self.execute_activity(activity_id, "")
