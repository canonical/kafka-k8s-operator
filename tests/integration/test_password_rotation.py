#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from jubilant_adapters import JujuFixture, gather

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    ZK_NAME,
    get_user,
    set_password,
)

logger = logging.getLogger(__name__)


def test_build_and_deploy(juju: JujuFixture, kafka_charm):
    gather(
        juju.ext.model.deploy(
            ZK_NAME,
            channel="3/edge",
            application_name=ZK_NAME,
            num_units=3,
            trust=True,
        ),
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            resources={"kafka-image": KAFKA_CONTAINER},
            num_units=1,
            trust=True,
            config={"expose_external": "nodeport"},
        ),
    )
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[ZK_NAME].units) == 3)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], timeout=2000, idle_period=30, raise_on_error=False
    )

    assert juju.ext.model.applications[APP_NAME].status == "blocked"
    assert juju.ext.model.applications[ZK_NAME].status == "active"

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], status="active", idle_period=30, timeout=3600
        )


def test_password_rotation(juju: JujuFixture):
    """Check that password stored on ZK has changed after a password rotation."""
    initial_sync_user = get_user(
        username="sync",
        model_full_name=juju.ext.model_full_name,
    )

    result = set_password(juju, username="sync", num_unit=0)
    assert "sync-password" in result.keys()

    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], status="active", idle_period=30)

    new_sync_user = get_user(
        username="sync",
        model_full_name=juju.ext.model_full_name,
    )

    assert initial_sync_user != new_sync_user
