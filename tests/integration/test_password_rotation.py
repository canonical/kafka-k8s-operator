#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    deploy_cluster,
    get_user,
    set_password,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, kraft_mode):
    await deploy_cluster(
        ops_test=ops_test,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose_external": "nodeport"},
        num_controller=3,
    )


async def test_password_rotation(ops_test: OpsTest, kafka_apps):
    """Check that password stored on ZK has changed after a password rotation."""
    initial_sync_user = get_user(
        username="sync",
        model_full_name=ops_test.model_full_name,
    )

    result = await set_password(ops_test, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    await ops_test.model.wait_for_idle(apps=kafka_apps, status="active", idle_period=30)

    new_sync_user = get_user(
        username="sync",
        model_full_name=ops_test.model_full_name,
    )

    assert initial_sync_user != new_sync_user
