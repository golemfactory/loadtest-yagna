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
from yapapi.rest.activity import ActivityService
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
        self.activity_api = None
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
            self.activity_api = ActivityService(self.api_client)

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
        builder.add(props.Activity(expiration=datetime.now(timezone.utc) + timedelta(minutes=20)))
 
        builder.add_properties(
            {
                "golem.com.payment.chosen-platform": "erc20-holesky-glm",
                "golem.com.scheme.payu.payment-timeout-sec": 1800,
                "golem.payment.address": "0x1234567890123456789012345678901234567890",
            }
        )
 
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

                    if proposal.is_draft:
                        if proposal._proposal.proposal.prev_proposal_id in our_proposal_ids:
                            logging.info(f"Provider accepted our proposal. Creating agreement for {proposal.id}")
                            return proposal
                    else:
                        # New proposal from a provider, let's respond.
                        logging.info(f"Responding to initial proposal: {proposal.id}")
                        our_proposal_id = await proposal.respond(self.demand_props, self.demand_constraints)
                        our_proposal_ids.add(our_proposal_id)
                        logging.info(f"Responded with our proposal: {our_proposal_id}")
            except asyncio.TimeoutError:
                logging.info("Timeout waiting for proposal, retrying...")
                pass
        logging.error(f"No proposals received within 5 seconds for subscription: {subscription.id}. Total proposals received: {proposals_received}")
        return None

    async def create_agreement(self, proposal):
        logging.info(f"Creating agreement for proposal: {proposal.id}")
        try:
            agreement = await proposal.create_agreement()
            logging.info(f"Created agreement: {agreement.id}")
            return agreement
        except Exception as e:
            logging.error(f"Failed to create agreement: {e}")
            return None

    async def confirm_agreement(self, agreement):
        logging.info(f"Confirming agreement: {agreement.id}")
        try:
            result = await agreement.confirm()
            if result:
                logging.info(f"Agreement confirmed: {agreement.id}")
            else:
                logging.error(f"Failed to confirm agreement: {agreement.id}")
            return result
        except Exception as e:
            logging.error(f"Failed to confirm agreement {agreement.id}: {e}")
            return False


    async def create_activity(self, agreement):
        logging.info(f"Creating activity for agreement: {agreement.id}")
        try:
            activity = await self.activity_api.new_activity(agreement.id)
            logging.info(f"Created activity: {activity.id}")
            return activity
        except Exception as e:
            logging.error(f"Failed to create activity for agreement {agreement.id}: {e}")
            return None

    def exec_script(self):
        logging.info("Executing script")
        return [{"run": {"path": "/bin/sh", "args": ["-c", "echo $((2+9))"]}}]

    async def terminate_agreement(self, agreement):
        logging.info(f"Terminating agreement: {agreement.id}")
        try:
            await agreement.terminate()
            logging.info(f"Terminated agreement: {agreement.id}")
        except Exception as e:
            logging.error(f"Failed to terminate agreement {agreement.id}: {e}")

    async def destroy_activity(self, activity):
        logging.info(f"Destroying activity: {activity.id}")
        try:
            await activity.destroy()
            logging.info(f"Destroyed activity: {activity.id}")
        except Exception as e:
            logging.error(f"Failed to destroy activity {activity.id}: {e}")


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
        agreement = None
        activity = None
        subscription = None

        try:
            subscription = await self.yagna_client.subscribe_to_demand()
            if not subscription:
                return

            proposal = await self.yagna_client.collect_proposals(subscription)
            if not proposal:
                return

            agreement = await self.yagna_client.create_agreement(proposal)
            if not agreement:
                return

            if not await self.yagna_client.confirm_agreement(agreement):
                return

            activity = await self.yagna_client.create_activity(agreement)
            if not activity:
                return

            batch = await activity.send(self.yagna_client.exec_script())
            result = ""
            async for _, event_data in batch:
                if "output" in event_data:
                    result += event_data["output"]

            if result and result.strip() == "11":
                events.request.fire(request_type="YAGNA", name="nanotask", response_time=1, response_length=len(result), exception=None, context={})
            else:
                events.request.fire(request_type="YAGNA", name="nanotask", response_time=1, response_length=0, exception=f"Incorrect result: {result}", context={})

        finally:
            if activity:
                await self.yagna_client.destroy_activity(activity)
            if agreement:
                await self.yagna_client.terminate_agreement(agreement)
            if subscription:
                await subscription.delete()
            logging.info("Finished nanotask_workflow.")
