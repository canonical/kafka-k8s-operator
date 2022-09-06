#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    ZK_NAME,
    check_user,
    get_zookeeper_connection,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.mark.abort_on_fail
async def test_deploy_charms_relate_active(ops_test: OpsTest, usernames):
    kafka_charm = await ops_test.build_charm(".")
    app_charm = await ops_test.build_charm("tests/integration/app-charm")

    await asyncio.gather(
        ops_test.model.deploy(
            "zookeeper-k8s", channel="edge", application_name=ZK_NAME, num_units=3
        ),
        ops_test.model.deploy(
<<<<<<< HEAD
            kafka_charm,
=======
            zk_charm,
>>>>>>> 9026d42 (fix integration tests)
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME_1, num_units=1),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1, ZK_NAME])

    await ops_test.model.add_relation(APP_NAME, ZK_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])

    await ops_test.model.add_relation(APP_NAME, DUMMY_NAME_1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_1])

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_1].status == "active"

    # implicitly tests setting of kafka app data
    returned_usernames, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka-k8s/0", model_full_name=ops_test.model_full_name
    )
    usernames.update(returned_usernames)

    for username in usernames:
        check_user(
            username=username,
            zookeeper_uri=zookeeper_uri,
            model_full_name=ops_test.model_full_name,
        )


@pytest.mark.abort_on_fail
async def test_deploy_multiple_charms_relate_active(ops_test: OpsTest, usernames):
    appii_charm = await ops_test.build_charm("tests/integration/app-charm")
    await ops_test.model.deploy(appii_charm, application_name=DUMMY_NAME_2, num_units=1),
    await ops_test.model.wait_for_idle(apps=[DUMMY_NAME_2])
    await ops_test.model.add_relation(APP_NAME, DUMMY_NAME_2)
    await ops_test.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME_2])

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_1].status == "active"
    assert ops_test.model.applications[DUMMY_NAME_2].status == "active"

    returned_usernames, zookeeper_uri = get_zookeeper_connection(
        unit_name="kafka-k8s/0", model_full_name=ops_test.model_full_name
    )
    usernames.update(returned_usernames)

    for username in usernames:
        check_user(
            username=username,
            zookeeper_uri=zookeeper_uri,
            model_full_name=ops_test.model_full_name,
        )


@pytest.mark.abort_on_fail
async def test_remove_application_removes_user(ops_test: OpsTest, usernames):
    await ops_test.model.applications[DUMMY_NAME_1].remove()
    await ops_test.model.applications[DUMMY_NAME_2].remove()
    await ops_test.model.wait_for_idle(apps=[APP_NAME])
    assert ops_test.model.applications[APP_NAME].status == "active"

    # checks that past usernames no longer exist in ZooKeeper
    with pytest.raises(Exception):
        _, _ = get_zookeeper_connection(
            unit_name="kafka-k8s/0", model_full_name=ops_test.model_full_name
        )
