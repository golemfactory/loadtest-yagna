import logging
import asyncio
logging.basicConfig(level=logging.INFO)

import os
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from locust import HttpUser, task, events
from gevent import sleep
from yapapi.props.builder import DemandBuilder
from yapapi.payload import vm
from yapapi.rest import Market
from yapapi.strategy import LeastExpensiveLinearPayuMS, DecreaseScoreForUnconfirmedAgreement
from yapapi import props
from decimal import Decimal
import ya_market
from ya_market import ApiClient

# Configuration from environment variables
YAGNA_API_URL = os.getenv('YAGNA_API_URL', 'http://127.0.0.1:7465')
YAGNA_APPKEY = os.getenv('YAGNA_APPKEY')

if not YAGNA_APPKEY:
    raise ValueError("YAGNA_APPKEY environment variable not set")

class YagnaClient:
    def __init__(self, user: HttpUser):
        self.user = user
        self.headers = {
            'Authorization': f'Bearer {YAGNA_APPKEY}',
            'Content-Type': 'application/json'
        }
        self.api_client = None
        self.market_api = None
        self.demand_props = None
        self.demand_constraints = None

    async def init_client(self):
        if self.api_client is None:
            cfg = ya_market.Configuration(host=f"{YAGNA_API_URL}/market-api/v1")
            self.api_client = ApiClient(
                configuration=cfg,
                header_name="authorization",
                header_value=f"Bearer {YAGNA_APPKEY}",
            )
            self.market_api = Market(self.api_client)

    async def close(self):
        if self.api_client:
            await self.api_client.close()

    async def subscribe_to_demand(self):
        await self.init_client()
        logging.info("Subscribing to demand...")
        builder = DemandBuilder()
        package = await vm.repo(
            image_hash="9a3b5d67b0b27746283cb5f287c13eab1beaa12d92a9f536b747c7ae",
            min_mem_gib=0.5,
            min_storage_gib=2.0,
        )
        
        # Add subnet and activity properties
        builder.add(props.NodeInfo(subnet_tag='public'))
        builder.add(props.Activity(expiration=datetime.now(timezone.utc) + timedelta(days=1)))

        await builder.decorate(package)

        strategy = LeastExpensiveLinearPayuMS(
            max_fixed_price=Decimal("1.0"),
            max_price_for={props.com.Counter.CPU: Decimal("0.2"), props.com.Counter.TIME: Decimal("0.1")},
        )
        strategy = DecreaseScoreForUnconfirmedAgreement(strategy, 0.5)
        await strategy.decorate_demand(builder)
        
        try:
            self.demand_props = builder.properties
            self.demand_constraints = builder.constraints
            subscription = await self.market_api.subscribe(self.demand_props, self.demand_constraints)
            logging.info(f"Subscribed to demand with subscriptionId: {subscription.id}")
            return subscription
        except Exception as e:
            logging.error(f"Failed to subscribe to demand: {e}")
            return None

    async def collect_proposals(self, subscription):
        logging.info(f"Collecting proposals for subscription: {subscription.id}")
        start_time = time.time()
        proposals_received = 0
        our_proposal_ids = set()
        while time.time() - start_time < 5:
            try:
                logging.info("Waiting for proposal events...")
                async for proposal in subscription.events():
                    proposals_received += 1
                    logging.info(f"Collected proposal: {proposal.id}, is_draft: {proposal.is_draft}, prev_proposal_id: {proposal._proposal.proposal.prev_proposal_id}")

                    if not proposal.is_draft:
                        if proposal._proposal.proposal.prev_proposal_id in our_proposal_ids:
                            logging.info(f"Provider accepted our proposal. Creating agreement for {proposal.id}")
                            return proposal.id
                        else:
                            # New proposal from a provider, let's respond.
                            logging.info(f"Responding to initial proposal: {proposal.id}")
                            our_proposal_id = await proposal.respond(self.demand_props, self.demand_constraints)
                            our_proposal_ids.add(our_proposal_id)
                            logging.info(f"Responded with our proposal: {our_proposal_id}")
            except asyncio.TimeoutError:
                logging.info("Timeout waiting for proposal, retrying...")
                pass
        logging.error(f"No proposals received within 30 seconds for subscription: {subscription.id}. Total proposals received: {proposals_received}")
        return None

    def create_agreement(self, proposal_id):
        logging.info(f"Creating agreement for proposal: {proposal_id}")
        agreement_payload = {
            "proposalId": proposal_id,
            "validTo": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace('+00:00', 'Z')
        }
        with self.user.client.post("/market-api/v1/agreements", json=agreement_payload, headers=self.headers, name="Create Agreement", catch_response=True) as response:
            if response.status_code == 201:
                agreement_id = response.json()['agreementId']
                logging.info(f"Created agreement: {agreement_id}")
                return agreement_id
            else:
                logging.error(f"Failed to create agreement. Status: {response.status_code}, Body: {response.text}")
                response.failure(f"Failed to create agreement. Status: {response.status_code}, Body: {response.text}")
                return None

    def confirm_agreement(self, agreement_id):
        logging.info(f"Confirming agreement: {agreement_id}")
        with self.user.client.post(f"/market-api/v1/agreements/{agreement_id}/confirm", headers=self.headers, name="Confirm Agreement", catch_response=True) as response:
            if response.status_code == 204:
                logging.info(f"Agreement confirmed: {agreement_id}")
                return True
            else:
                logging.error(f"Failed to confirm agreement. Status: {response.status_code}")
                response.failure(f"Failed to confirm agreement. Status: {response.status_code}")
                return False

    def wait_for_approval(self, agreement_id):
        logging.info(f"Waiting for agreement approval: {agreement_id}")
        start_time = time.time()
        while time.time() - start_time < 15:
            with self.user.client.get(f"/market-api/v1/agreements/{agreement_id}", headers=self.headers, name="Get Agreement", catch_response=True) as response:
                if response.status_code == 200 and response.json().get('state') == 'Approved':
                    logging.info(f"Agreement approved: {agreement_id}")
                    return True
            sleep(1)
        logging.error(f"Agreement not approved within timeout: {agreement_id}")
        return False

    def create_activity(self, agreement_id):
        logging.info(f"Creating activity for agreement: {agreement_id}")
        activity_payload = {"agreementId": agreement_id}
        with self.user.client.post("/activity-api/v1/activities", json=activity_payload, headers=self.headers, name="Create Activity", catch_response=True) as response:
            if response.status_code == 201:
                activity_id = response.json()['activityId']
                logging.info(f"Created activity: {activity_id}")
                return activity_id
            else:
                logging.error(f"Failed to create activity. Status: {response.status_code}, Body: {response.text}")
                response.failure(f"Failed to create activity. Status: {response.status_code}, Body: {response.text}")
                return None

    def exec_script(self, activity_id):
        logging.info(f"Executing script for activity: {activity_id}")
        script_payload = {
            "exeScript": {
                "text": json.dumps([{"run": {"path": "/bin/sh", "args": ["-c", "echo $((2+9))"]}}])
            }
        }
        with self.user.client.post(f"/activity-api/v1/activities/{activity_id}/exec", json=script_payload, headers=self.headers, name="Exec Script", catch_response=True) as response:
            if response.status_code == 202:
                batch_id = response.headers.get('Location').split('/')[-1]
                logging.info(f"Script executed with batch_id: {batch_id}")
                return batch_id
            else:
                logging.error(f"Failed to execute script. Status: {response.status_code}, Body: {response.text}")
                response.failure(f"Failed to execute script. Status: {response.status_code}, Body: {response.text}")
                return None

    def get_exec_results(self, activity_id, batch_id):
        logging.info(f"Getting results for batch: {batch_id}")
        while self.user.environment.runner.state in ["running", "spawning"]:
            logging.info("Polling for results...")
            with self.user.client.get(f"/activity-api/v1/activities/{activity_id}/exec/{batch_id}/results", headers=self.headers, name="Get Exec Results", catch_response=True) as response:
                if response.status_code == 200:
                    results = response.json()
                    if results and results[0].get('isBatchFinished'):
                        stdout = results[0]['stdout']
                        logging.info(f"Got result: {stdout}")
                        return stdout
            logging.info("No results yet, sleeping...")
            sleep(1)
        return None

    def terminate_agreement(self, agreement_id):
        self.user.client.post(f"/market-api/v1/agreements/{agreement_id}/terminate", headers=self.headers, name="Terminate Agreement")

    def destroy_activity(self, activity_id):
        self.user.client.delete(f"/activity-api/v1/activities/{activity_id}", headers=self.headers, name="Destroy Activity")


class YagnaUser(HttpUser):
    host = YAGNA_API_URL
    min_wait = 5000
    max_wait = 15000

    def on_start(self):
        logging.info("YagnaUser on_start")
        self.yagna_client = YagnaClient(self)

    def on_stop(self):
        logging.info("YagnaUser on_stop")
        if self.yagna_client:
            asyncio.run(self.yagna_client.close())

    @task
    def nanotask_workflow_sync(self):
        asyncio.run(self.nanotask_workflow())

    async def nanotask_workflow(self):
        await self.yagna_client.init_client()
        logging.info("Starting nanotask_workflow...")
        agreement_id = None
        activity_id = None
        subscription = None

        try:
            subscription = await self.yagna_client.subscribe_to_demand()
            if not subscription:
                return

            proposal_id = await self.yagna_client.collect_proposals(subscription)
            if not proposal_id:
                return

            agreement_id = self.yagna_client.create_agreement(proposal_id)
            if not agreement_id:
                return

            if not self.yagna_client.confirm_agreement(agreement_id) or not self.yagna_client.wait_for_approval(agreement_id):
                return

            activity_id = self.yagna_client.create_activity(agreement_id)
            if not activity_id:
                return

            batch_id = self.yagna_client.exec_script(activity_id)
            if not batch_id:
                return

            result = self.yagna_client.get_exec_results(activity_id, batch_id)

            if result and result.strip() == "11":
                events.request.fire(request_type="YAGNA", name="nanotask", response_time=1, response_length=len(result), exception=None, context={})
            else:
                events.request.fire(request_type="YAGNA", name="nanotask", response_time=1, response_length=0, exception=f"Incorrect result: {result}", context={})

        finally:
            if activity_id:
                self.yagna_client.destroy_activity(activity_id)
            if agreement_id:
                self.yagna_client.terminate_agreement(agreement_id)
            if subscription:
                await subscription.delete()
            logging.info("Finished nanotask_workflow.")
