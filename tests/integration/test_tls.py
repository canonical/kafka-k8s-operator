#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from charms.tls_certificates_interface.v1.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    KAFKA_SERIES,
    TLS_SERIES,
    ZK_NAME,
    ZK_SERIES,
    check_application_status,
    check_tls,
    extract_private_key,
    get_address,
    set_tls_private_key,
    show_unit,
)

logger = logging.getLogger(__name__)

TLS_NAME = "tls-certificates-operator"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="beta", config=tls_config, series=TLS_SERIES),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=3, series=ZK_SERIES),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            resources={"kafka-image": KAFKA_CONTAINER},
            series=KAFKA_SERIES,
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, TLS_NAME], timeout=2000)

    assert check_application_status(ops_test=ops_test, app_name=APP_NAME) == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Relate Zookeeper to TLS
    await ops_test.model.add_relation(TLS_NAME, ZK_NAME)
    logger.info("Relate Zookeeper to TLS")

    async with ops_test.fast_forward(fast_interval="30s"):
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME, ZK_NAME], idle_period=20, status="active", timeout=2000
        )

    assert ops_test.model.applications[TLS_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kakfa[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    await ops_test.model.add_relation(ZK_NAME, APP_NAME)
    await ops_test.model.wait_for_idle(apps=[ZK_NAME], idle_period=60, timeout=2000)

    # Unit is on 'blocked' but whole app is on 'waiting'
    assert check_application_status(ops_test=ops_test, app_name=APP_NAME) == "waiting"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    await set_tls_private_key(ops_test)

    # Extract the key
    private_key = extract_private_key(
        show_unit(f"{APP_NAME}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    await ops_test.model.add_relation(APP_NAME, TLS_NAME)
    logger.info("Relate Kafka to TLS")
    async with ops_test.fast_forward(fast_interval="30s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=20, timeout=2000, status="active"
        )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    logger.info("Check for Kafka TLS")
    check_tls(ip=kafka_address, port=19093)

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    await set_tls_private_key(ops_test, key=new_private_key)

    # Extract the key
    private_key_2 = extract_private_key(
        show_unit(f"{APP_NAME}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


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

    # TODO: Add this back once the scaling tests are addressed
    """
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers
    """

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    check_tls(ip=kafka_address, port=19093)
