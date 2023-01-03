#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
from helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    ZK_NAME,
    check_application_status,
    produce_and_check_logs,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel="edge",
            application_name=ZK_NAME,
            num_units=3,
            series="focal",
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            series="jammy",
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], timeout=1000)

    assert check_application_status(ops_test, APP_NAME) == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest):
    app_charm = await ops_test.build_charm("tests/integration/app-charm")
    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000)
    await ops_test.model.add_relation(APP_NAME, DUMMY_NAME)
    time.sleep(10)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    # run action to enable producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("make-admin")
    await action.wait()
    time.sleep(10)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    logger.info("producing logs")
    produce_and_check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        provider_unit_name=f"{DUMMY_NAME}/0",
        topic="hot-topic",
    )


@pytest.mark.abort_on_fail
async def test_blocks_without_zookeeper(ops_test: OpsTest):
    async with ops_test.fast_forward():
        await ops_test.model.applications[ZK_NAME].remove()
        await ops_test.model.wait_for_idle(apps=[APP_NAME], raise_on_error=False, timeout=1000)

    # Unit is on 'blocked' but whole app is on 'waiting'
    assert check_application_status(ops_test, APP_NAME) == "waiting"
