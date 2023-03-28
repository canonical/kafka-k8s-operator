#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import time

import pytest
import requests
from pytest_operator.plugin import OpsTest

from literals import REL_NAME, SECURITY_PROTOCOL_PORTS

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    KAFKA_SERIES,
    ZK_NAME,
    ZK_SERIES,
    check_application_status,
    check_logs,
    check_socket,
    get_address,
    run_client_properties,
)

logger = logging.getLogger(__name__)

DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            ZK_NAME,
            channel="edge",
            application_name=ZK_NAME,
            num_units=3,
            series=ZK_SERIES,
        ),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            series=KAFKA_SERIES,
        ),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], timeout=1000)

    assert check_application_status(ops_test, APP_NAME) == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)

    async with ops_test.fast_forward(fast_interval="30s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], timeout=1000, idle_period=20, status="active"
        )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_listeners(ops_test: OpsTest, app_charm):
    address = await get_address(ops_test=ops_test)
    assert check_socket(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].internal
    )  # Internal listener
    # Client listener should not be enable if there is no relations
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)
    # Add relation with dummy app
    await asyncio.gather(
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME, ZK_NAME])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    # check that client listener is active
    assert check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)
    # remove relation and check that client listerner is not active
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert not check_socket(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client)


@pytest.mark.abort_on_fail
async def test_client_properties_makes_admin_connection(ops_test: OpsTest):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])
    result = await run_client_properties(ops_test=ops_test)
    assert result
    assert len(result.strip().split("\n")) == 3
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME])


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest):
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    time.sleep(10)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME, DUMMY_NAME])

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    await action.wait()
    time.sleep(10)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME].status == "active"

    check_logs(
        model_full_name=ops_test.model_full_name,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )


@pytest.mark.abort_on_fail
async def test_exporter_endpoints(ops_test: OpsTest):

    unit_address = await get_address(ops_test=ops_test)
    jmx_exporter_url = f"http://{unit_address}:9101/metrics"
    jmx_resp = requests.get(jmx_exporter_url)

    assert jmx_resp.ok


@pytest.mark.abort_on_fail
async def test_blocks_without_zookeeper(ops_test: OpsTest):
    async with ops_test.fast_forward(fast_interval="30s"):
        await ops_test.model.applications[ZK_NAME].remove()
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], idle_period=20, raise_on_error=False, timeout=1000
        )

    # Unit is on 'blocked' but whole app is on 'waiting'
    assert check_application_status(ops_test, APP_NAME) == "waiting"
