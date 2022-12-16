#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import ZK_NAME, check_application_status, check_tls, get_address
from literals import CHARM_KEY
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

TLS_NAME = "tls-certificates-operator"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="beta", config=tls_config, series="focal"),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=3, series="focal"),
        ops_test.model.deploy(
            kafka_charm,
            application_name=CHARM_KEY,
            resources={"kafka-image": "ubuntu/kafka:latest"},
            series="jammy",
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[CHARM_KEY, ZK_NAME, TLS_NAME], timeout=1000)

    assert check_application_status(ops_test=ops_test, app_name=CHARM_KEY) == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Relate Zookeeper to TLS
    await ops_test.model.add_relation(TLS_NAME, ZK_NAME)
    logger.info("Relate Zookeeper to TLS")
    await ops_test.model.wait_for_idle(apps=[TLS_NAME, ZK_NAME], idle_period=40)

    assert ops_test.model.applications[TLS_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kakfa[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    await ops_test.model.add_relation(ZK_NAME, CHARM_KEY)
    await ops_test.model.wait_for_idle(apps=[ZK_NAME], idle_period=60, timeout=1000)

    # Unit is on 'blocked' but whole app is on 'waiting'
    assert check_application_status(ops_test=ops_test, app_name=CHARM_KEY) == "waiting"

    await ops_test.model.add_relation(CHARM_KEY, TLS_NAME)
    logger.info("Relate Kafka to TLS")
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY, ZK_NAME, TLS_NAME], idle_period=60, timeout=1000
    )

    assert ops_test.model.applications[CHARM_KEY].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    kafka_address = await get_address(ops_test=ops_test, app_name=CHARM_KEY)
    logger.info("Check for Kafka TLS")
    check_tls(ip=kafka_address, port=9093)


async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[CHARM_KEY].scale(scale=3)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[CHARM_KEY].units) == 3, timeout=1000
    )
    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[CHARM_KEY],
        status="active",
        idle_period=40,
        timeout=1000,
    )

    # TODO: Add this back once the scaling tests are addressed
    """
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{CHARM_KEY}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers
    """

    kafka_address = await get_address(ops_test=ops_test, app_name=CHARM_KEY, unit_num=2)
    check_tls(ip=kafka_address, port=9093)
