import logging
from functools import lru_cache
import requests
import time
from datetime import datetime, timezone, timedelta

from model import Demand

@lru_cache(maxsize=100)
def calculate_task_package(image_tag: str):
    # 'https://registry.golem.network/v1/image/info?count=true&tag=golem/alpine:latest'
    # TODO calculate it asking golem registry
    logging.debug(f"Calculating task package for {image_tag}")
    response = requests.get(f"https://registry.golem.network/v1/image/info?count=true&tag={image_tag}")
    if response.status_code != 200:
        logging.error(f"Failed to get task package for {image_tag}: {response.status_code}")
        return None
    data = response.json()
    logging.info(f"Task package for {image_tag}: {data}")
    return f"hash:sha3:{data['sha3']}:{data['http']}"

def prepare_demand(sender_address, expiration, subnet, payment_platform, image_tag: str = 'golem/alpine:latest'):
    return Demand(properties={
            "golem.com.payment.debit-notes.accept-timeout?": 120,
            "golem.node.debug.subnet": subnet,
            "golem.com.payment.chosen-platform": payment_platform,
            f"golem.com.payment.platform.{payment_platform}.address": sender_address,
            "golem.srv.comp.expiration": expiration,
            "golem.srv.caps.multi-activity": True,
            "golem.srv.comp.vm.package_format": "gvmkit-squash",
            "golem.com.payment.protocol.version": "3",
            "golem.srv.comp.task_package": calculate_task_package(image_tag)
        },
        constraints=f"(&(golem.com.pricing.model=linear)\n\t(golem.node.debug.subnet={subnet})\n\t(golem.runtime.name=vm)\n\t(golem.inf.mem.gib>=0.5)\n\t(golem.inf.storage.gib>=2)\n\t(golem.inf.cpu.cores>=1)\n\t(golem.inf.cpu.threads>=1)\n\t(golem.com.payment.platform.{payment_platform}.address=*)\n\t(golem.com.payment.protocol.version>1))"
    )

def get_formatted_timestamp(*, timestamp: float | None = None, shift: float | None = None):
    t= datetime.now(tz=timezone.utc) if timestamp is None else datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if shift is not None:
        t = t + timedelta(seconds=shift)
    return t.isoformat(timespec='milliseconds').replace("+00:00", "Z")

def calculate_budget(max_start_price: float, max_cpu_per_hour_price: float, max_env_per_hour_price: float, lasting: float):
    lasting_hours = lasting / 3600
    return max_start_price + max_cpu_per_hour_price * lasting_hours + max_env_per_hour_price * lasting_hours