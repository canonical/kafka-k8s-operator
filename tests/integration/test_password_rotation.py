#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    stop_after_attempt,
    wait_fixed,
)

from integration.helpers.pytest_operator import (
    AUTH_SECRET_NAME,
    deploy_cluster,
    get_user,
    set_password,
)
from literals import INTER_BROKER_USER

logger = logging.getLogger(__name__)


def _assert_password_updated(model_full_name: str, old_user: str, expected_password: str):
    try:
        for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(30)):
            with attempt:
                new_user = get_user(
                    username=INTER_BROKER_USER,
                    model_full_name=model_full_name,
                )
                assert old_user != new_user
                assert expected_password in new_user
                return
    except RetryError:
        assert False, "Password update assertion failed after 5 attempts."


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, kraft_mode):
    await deploy_cluster(
        ops_test=ops_test,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose-external": "nodeport"},
        num_broker=3,
        num_controller=3,
    )


async def test_password_rotation(ops_test: OpsTest, kafka_apps):
    """Check that password stored on cluster has changed after a password rotation."""
    initial_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=ops_test.model_full_name,
    )

    await set_password(ops_test, username=INTER_BROKER_USER, password="newpass123")

    await ops_test.model.wait_for_idle(apps=kafka_apps, status="active", idle_period=30)

    _assert_password_updated(
        ops_test.model_full_name, old_user=initial_replication_user, expected_password="newpass123"
    )

    new_replication_user = get_user(
        username=INTER_BROKER_USER,
        model_full_name=ops_test.model_full_name,
    )

    # Update secret
    await ops_test.model.update_secret(
        name=AUTH_SECRET_NAME, data_args=[f"{INTER_BROKER_USER}=updatedpass"]
    )

    await ops_test.model.wait_for_idle(apps=kafka_apps, status="active", idle_period=30)

    _assert_password_updated(
        ops_test.model_full_name, old_user=new_replication_user, expected_password="updatedpass"
    )
