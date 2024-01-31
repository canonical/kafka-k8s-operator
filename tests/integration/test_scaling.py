#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    KAFKA_SERIES,
    ZK_NAME,
    ZK_SERIES,
    get_active_brokers,
    get_kafka_zk_relation_data,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_up(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")

    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME, channel="edge", application_name=ZK_NAME, num_units=1, series=ZK_SERIES
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            series=KAFKA_SERIES,
        ),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward(fast_interval="30s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], timeout=1000, status="active", idle_period=20
        )

    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[APP_NAME].status == "active"

    await ops_test.model.applications[APP_NAME].add_units(count=2)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=40
    )

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers


@pytest.mark.abort_on_fail
async def test_kafka_simple_scale_down(ops_test: OpsTest):
    await ops_test.model.applications[APP_NAME].destroy_units(f"{APP_NAME}/1")
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[APP_NAME].units) == 2)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    time.sleep(30)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" not in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers
