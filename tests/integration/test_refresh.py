#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
import pytest

from integration.helpers import (
    APP_NAME,
    CONTROLLER_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    TLS_NAME,
    KRaftMode,
)
from integration.helpers.jubilant import all_active_idle, check_logs, deploy_cluster
from literals import TLS_RELATION

logger = logging.getLogger(__name__)

CHANNEL = "3/stable"


@pytest.mark.abort_on_fail
def test_in_place_refresh(juju: jubilant.Juju, kafka_charm, kraft_mode: KRaftMode):
    """Tests happy path refresh with TLS in KRaft mode."""
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]
    tls_config = {"ca-common-name": "kafka"}

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=1,
        num_controller=1,
    )

    juju.deploy(TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    if kraft_mode == "multi":
        juju.integrate(f"{CONTROLLER_NAME}:{TLS_RELATION}", TLS_NAME)
    juju.integrate(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, TLS_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.add_unit(APP_NAME, num_units=2)
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME) and len(status.apps[APP_NAME].units) == 3,
        delay=3,
        successes=10,
        timeout=600,
    )

    leader_unit = None
    for unit_name, unit in juju.status().apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check...")
    juju.run(leader_unit, "pre-refresh-check")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Upgrading Kafka...")
    juju.refresh(
        APP_NAME,
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    juju.run(leader_unit, "resume-refresh")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    # cleanup existing 'current' Kafka, and remove TLS for next test
    juju.remove_application(APP_NAME, destroy_storage=True, force=True)
    juju.remove_application(TLS_NAME, destroy_storage=True, force=True)
    if kraft_mode == "multi":
        juju.remove_application(CONTROLLER_NAME, destroy_storage=True, force=True)

    # Wait for model to be empty
    juju.wait(
        lambda status: len(status.apps) == 0,
        delay=3,
        successes=5,
        timeout=600,
    )


@pytest.mark.skip(reason="Test controller node instead")
def test_in_place_refresh_consistency(
    juju: jubilant.Juju, kafka_charm, app_charm, kraft_mode: KRaftMode
):
    """Tests non-TLS refresh data consistency during refresh in KRaft mode."""
    kafka_apps = [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]

    deploy_cluster(
        juju=juju,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        num_broker=1,
        num_controller=1,
    )

    juju.deploy(app_charm, app=DUMMY_NAME, trust=True)

    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.integrate(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.wait(
        lambda status: all_active_idle(status, *kafka_apps, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1800,
    )

    juju.add_unit(APP_NAME, num_units=2)
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME) and len(status.apps[APP_NAME].units) == 3,
        delay=3,
        successes=10,
        timeout=600,
    )

    logger.info("Producing messages before upgrading...")
    juju.run(f"{DUMMY_NAME}/0", "produce")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    leader_unit = None
    for unit_name, unit in juju.status().apps[APP_NAME].units.items():
        if unit.leader:
            leader_unit = unit_name
            break
    assert leader_unit

    logger.info("Calling pre-refresh-check...")
    juju.run(leader_unit, "pre-refresh-check")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Upgrading Kafka...")
    juju.refresh(
        APP_NAME,
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    juju.run(leader_unit, "resume-refresh")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )

    logger.info("Checking that produced messages can be consumed afterwards...")
    juju.run(f"{DUMMY_NAME}/0", "consume")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, DUMMY_NAME),
        delay=3,
        successes=10,
        timeout=1000,
    )
