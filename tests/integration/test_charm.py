#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

APP_NAME = "kafka"
ZK = "zookeeper-k8s"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    kafka_charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy("zookeeper-k8s", channel="edge", application_name=ZK, num_units=1),
        ops_test.model.deploy(kafka_charm, application_name=APP_NAME, num_units=1),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK])
    assert ops_test.model.applications[APP_NAME].status == "waiting"
    assert ops_test.model.applications[ZK].status == "active"

    await ops_test.model.add_relation(APP_NAME, ZK)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK])
    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[ZK].status == "active"


@pytest.mark.abort_on_fail
async def test_blocks_without_zookeeper(ops_test: OpsTest):
    await asyncio.gather(ops_test.model.applications[ZK].remove())
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert ops_test.model.applications[ZK].status == "blocked"
