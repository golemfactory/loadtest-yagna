from model import Demand

def calculate_task_package(image_tag: str):
    # 'https://registry.golem.network/v1/image/info?count=true&tag=golem/alpine:latest'
    # TODO calculate it asking golem registry
    return f"hash:sha3:64c5a5548cea45177ba89dcc13bea00bd7e8d6db5bbf81872fa462f3:http://registry.golem.network/download/54200484f0115776b5ed339a30811bc621479ccc4169181aeabca4ad8cb07ab2"

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