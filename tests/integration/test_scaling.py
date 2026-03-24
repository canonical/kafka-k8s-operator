#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from time import sleep

from jubilant_adapters import JujuFixture, gather

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    ZK_NAME,
    get_active_brokers,
    get_address,
    get_kafka_zk_relation_data,
)

logger = logging.getLogger(__name__)


def test_kafka_simple_scale_up(juju: JujuFixture, kafka_charm):
    gather(
        juju.ext.model.deploy(
            ZK_NAME, channel="3/edge", application_name=ZK_NAME, num_units=1, trust=True
        ),
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME])
    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], timeout=1000, status="active", idle_period=20
        )

    juju.ext.model.applications[APP_NAME].scale(scale=3)
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[APP_NAME].units) == 3)
    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=40)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        juju=juju,
        unit_name=f"{APP_NAME}/2",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_address = get_address(juju, app_name=ZK_NAME)
    kafka_zk_relation_data["endpoints"] = zookeeper_address

    active_brokers = get_active_brokers(config=kafka_zk_relation_data)

    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers


def test_kafka_simple_scale_down(juju: JujuFixture):
    juju.ext.model.applications[APP_NAME].scale(scale=2)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=30, wait_for_exact_units=2
    )

    # ensuring ZK data gets updated
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(60)

    kafka_zk_relation_data = get_kafka_zk_relation_data(
        juju=juju,
        unit_name=f"{APP_NAME}/1",
        owner=ZK_NAME,
    )

    # can't use *-endpoints address from outside of K8s cluster, need to patch
    zookeeper_address = get_address(juju, app_name=ZK_NAME)
    kafka_zk_relation_data["endpoints"] = zookeeper_address

    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("database", kafka_zk_relation_data.get("chroot", ""))
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" not in active_brokers
