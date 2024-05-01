#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from charms.tls_certificates_interface.v1.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import SECURITY_PROTOCOL_PORTS, TLS_RELATION

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_tls,
    delete_pod,
    extract_private_key,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
    set_tls_private_key,
)

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"

MTLS_NAME = "mtls"
DUMMY_NAME = "app"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest, app_charm):
    kafka_charm = await ops_test.build_charm(".")
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="edge", config=tls_config),
        ops_test.model.deploy(ZK_NAME, channel="3/edge", num_units=3),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            resources={"kafka-image": KAFKA_CONTAINER},
            config={
                "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
            },
        ),
    )
    async with ops_test.fast_forward(fast_interval="20s"):
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[ZK_NAME].units) == 3
        )
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=2000
    )

    assert ops_test.model.applications[APP_NAME].status == "blocked"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    await ops_test.model.add_relation(TLS_NAME, ZK_NAME)

    # Relate Zookeeper to TLS
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME, ZK_NAME], idle_period=30, status="active", timeout=2000
        )


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest, app_charm):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.add_relation(ZK_NAME, APP_NAME)
        await ops_test.model.wait_for_idle(
            apps=[ZK_NAME], idle_period=15, timeout=1000, status="active"
        )

        # Unit is on 'blocked' but whole app is on 'waiting'
        assert ops_test.model.applications[APP_NAME].status == "blocked"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    await set_tls_private_key(ops_test)

    # Extract the key
    private_key = extract_private_key(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    # ensuring at least a few update-status
    await ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)

    # Client port shouldn't be up before relating to client app.
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)

    # ensuring at least a few update-status
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active"
    )

    assert check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    await set_tls_private_key(ops_test, key=new_private_key)

    # ensuring key event actually runs
    async with ops_test.fast_forward(fast_interval="10s"):
        await asyncio.sleep(60)

    # Extract the key
    private_key_2 = extract_private_key(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/{num_unit}",
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


# TODO: Add mTLS tests


async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[APP_NAME].scale(scale=3)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=2000
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=40,
        timeout=2000,
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        ops_test=ops_test,
        unit_name=f"{APP_NAME}/2",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_addresses = [
        await get_address(ops_test, app_name=ZK_NAME, unit_num=unit.name.split("/")[1])
        for unit in ops_test.model.applications[ZK_NAME].units
    ]
    logger.info(f"{zookeeper_addresses}")
    kafka_zk_relation_data["endpoints"] = ",".join(zookeeper_addresses)
    logger.info(f"{kafka_zk_relation_data=}")

    active_brokers = get_active_brokers(config=kafka_zk_relation_data)

    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    assert check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    # remove relation and check connection again
    remove_relation_cmd = f"remove-relation {APP_NAME} {DUMMY_NAME}"
    await ops_test.juju(*remove_relation_cmd.split(), check=True)

    await ops_test.model.wait_for_idle(apps=[APP_NAME], idle_period=30, timeout=1000)
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)


async def test_pod_reschedule_tls(ops_test: OpsTest):
    delete_pod(ops_test, f"{APP_NAME}-0")

    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=90,
        timeout=2000,
    )


async def test_tls_removed(ops_test: OpsTest):
    await ops_test.model.remove_application(TLS_NAME, block_until_done=True)

    # ensuring enough update-status to unblock ZK
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], timeout=3600, idle_period=30, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)
