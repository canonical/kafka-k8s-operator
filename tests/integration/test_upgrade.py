#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from time import sleep

from jubilant_adapters import JujuFixture, gather

from literals import TLS_RELATION

from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    TLS_NAME,
    ZK_NAME,
    check_logs,
)

logger = logging.getLogger(__name__)

CHANNEL = "3/stable"


def test_in_place_upgrade(juju: JujuFixture, kafka_charm):
    """Tests happy path upgrade with TLS."""
    tls_config = {"ca-common-name": "kafka"}

    gather(
        juju.ext.model.deploy(
            ZK_NAME,
            channel=CHANNEL,
            application_name=ZK_NAME,
            num_units=1,
            trust=True,
        ),
        juju.ext.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
            trust=True,
        ),
        juju.ext.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True
        ),
    )

    gather(
        juju.ext.model.add_relation(APP_NAME, ZK_NAME),
        juju.ext.model.add_relation(ZK_NAME, TLS_NAME),
        juju.ext.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME),
    )

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, TLS_NAME],
            idle_period=30,
            timeout=1800,
            status="active",
            raise_on_error=False,
        )

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME], status="active", idle_period=30
    )

    juju.ext.model.applications[APP_NAME].add_units(count=2)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    leader_unit = None
    for unit in juju.ext.model.applications[APP_NAME].units:
        if unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = leader_unit.run_action("pre-upgrade-check")
    action.wait()
    juju.ext.model.wait_for_idle(apps=[APP_NAME], timeout=1000, idle_period=15, status="active")

    logger.info("Upgrading Kafka...")
    juju.ext.model.applications[APP_NAME].refresh(
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(90)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], timeout=1000, idle_period=180, raise_on_error=False
    )

    action = leader_unit.run_action("resume-upgrade")
    action.wait()
    juju.ext.model.wait_for_idle(apps=[APP_NAME], timeout=1000, idle_period=30, status="active")

    # cleanup existing 'current' Kafka, and remove TLS for next test
    juju.ext.model.remove_application(APP_NAME, block_until_done=True)
    juju.ext.model.remove_application(TLS_NAME, block_until_done=True)
    juju.ext.model.wait_for_idle(apps=[ZK_NAME], timeout=1800, idle_period=30, status="active")


def test_in_place_upgrade_consistency(juju: JujuFixture, kafka_charm, app_charm):
    """Tests non-TLS upgrade data consistency during upgrade."""
    gather(
        juju.ext.model.deploy(
            APP_NAME,
            application_name=APP_NAME,
            num_units=1,
            channel=CHANNEL,
            trust=True,
        ),
        juju.ext.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, DUMMY_NAME],
            idle_period=30,
            timeout=1800,
            status="active",
            raise_on_error=False,
        )

    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, DUMMY_NAME], status="active", idle_period=30
    )

    juju.ext.model.applications[APP_NAME].add_units(count=2)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600, idle_period=30, wait_for_exact_units=3
    )

    logger.info("Producing messages before upgrading...")
    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    action.wait()
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    leader_unit = None
    for unit in juju.ext.model.applications[APP_NAME].units:
        if unit.is_leader_from_status():
            leader_unit = unit
    assert leader_unit

    logger.info("Calling pre-upgrade-check...")
    action = leader_unit.run_action("pre-upgrade-check")
    action.wait()
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=15, status="active"
    )

    logger.info("Upgrading Kafka...")
    juju.ext.model.applications[APP_NAME].refresh(
        path=kafka_charm,
        resources={"kafka-image": KAFKA_CONTAINER},
    )

    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(90)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=180, raise_on_error=False
    )

    action = leader_unit.run_action("resume-upgrade")
    action.wait()
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    logger.info("Checking that produced messages can be consumed afterwards...")
    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action("consume")
    action.wait()
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )
