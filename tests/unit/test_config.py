#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import ops.testing
import pytest
from ops.testing import Harness

from charm import KafkaK8sCharm
from literals import ADMIN_USER, INTER_BROKER_USER, INTERNAL_USERS

ops.testing.SIMULATE_CAN_CONNECT = True


@pytest.fixture(scope="function")
def harness():
    harness = Harness(KafkaK8sCharm)
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def zk_relation_id(harness):
    relation_id = harness.add_relation("zookeeper", "kafka-k8s")
    return relation_id


# def test_all_storages_in_log_dirs(harness):
#     """Checks that the log.dirs property updates with all available storages."""
#     with harness.hooks_disabled():
#         harness.add_storage(storage_name=STORAGE, attach=True)

#     print(f"{harness.charm.kafka_config.log_dirs}")
#     print(f"{harness.charm.kafka_config.log_dirs.split(',')}")
#     print(f"{harness.charm.model.storages[STORAGE]}")
#     print(f"{len(harness.charm.model.storages[STORAGE])}")
#     assert len(harness.charm.kafka_config.log_dirs.split(",")) == len(
#         harness.charm.model.storages[STORAGE]
#     )


def test_log_dirs_in_server_properties(zk_relation_id, harness):
    """Checks that log.dirs are added to server_properties."""
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/1")
    harness.update_relation_data(peer_relation_id, "kafka-k8s/1", {"private-address": "treebeard"})

    found_log_dirs = False
    with (
        patch(
            "config.KafkaConfig.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        for prop in harness.charm.kafka_config.server_properties:
            if "log.dirs" in prop:
                found_log_dirs = True

        assert found_log_dirs


def test_listeners_in_server_properties(zk_relation_id, harness):
    """Checks that listeners are split into INTERNAL and EXTERNAL."""
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    expected_listeners = "listeners=INTERNAL_SASL_PLAINTEXT://:19092"
    expected_advertised_listeners = (
        "advertised.listeners=INTERNAL_SASL_PLAINTEXT://kafka-k8s-0.kafka-k8s-endpoints:19092"
    )

    with (
        patch(
            "config.KafkaConfig.internal_user_credentials",
            new_callable=PropertyMock,
            return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
        )
    ):
        assert expected_listeners in harness.charm.kafka_config.server_properties
        assert expected_advertised_listeners in harness.charm.kafka_config.server_properties


def test_zookeeper_config_succeeds_fails_config(zk_relation_id, harness):
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
        },
    )
    assert harness.charm.kafka_config.zookeeper_config == {}
    assert not harness.charm.kafka_config.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(zk_relation_id, harness):
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert "connect" in harness.charm.kafka_config.zookeeper_config
    assert (
        harness.charm.kafka_config.zookeeper_config["connect"] == "1.1.1.1:2181,2.2.2.2:2181/kafka"
    )
    assert harness.charm.kafka_config.zookeeper_connected


def test_auth_args(harness):
    args = harness.charm.kafka_config.auth_args
    assert "-Djava.security.auth.login.config=/data/kafka/config/kafka-jaas.cfg" in args


def test_extra_args(harness):
    args = harness.charm.kafka_config.extra_args
    assert (
        "-javaagent:/opt/kafka/extra/jmx_prometheus_javaagent.jar=9101:/opt/kafka/default-config/jmx_prometheus.yaml"
        in args
    )


def test_bootstrap_server(harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/1")

    assert len(harness.charm.kafka_config.bootstrap_server) == 2
    for server in harness.charm.kafka_config.bootstrap_server:
        assert "9092" in server


def test_default_replication_properties_less_than_three(harness):
    assert "num.partitions=1" in harness.charm.kafka_config.default_replication_properties
    assert (
        "default.replication.factor=1" in harness.charm.kafka_config.default_replication_properties
    )
    assert "min.insync.replicas=1" in harness.charm.kafka_config.default_replication_properties


def test_default_replication_properties_more_than_three(harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/1")
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/2")
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/3")
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/4")
    harness.add_relation_unit(peer_relation_id, "kafka-k8s/5")

    assert "num.partitions=3" in harness.charm.kafka_config.default_replication_properties
    assert (
        "default.replication.factor=3" in harness.charm.kafka_config.default_replication_properties
    )
    assert "min.insync.replicas=2" in harness.charm.kafka_config.default_replication_properties


def test_auth_properties(zk_relation_id, harness):
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"sync-password": "mellon"}
    )
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    assert "broker.id=0" in harness.charm.kafka_config.auth_properties
    assert (
        f"zookeeper.connect={harness.charm.kafka_config.zookeeper_config['connect']}"
        in harness.charm.kafka_config.auth_properties
    )


def test_super_users(harness):
    """Checks super-users property is updated for new admin clients."""
    peer_relation_id = harness.charm.model.get_relation("cluster").id
    app_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(app_relation_id, "app", {"extra-user-roles": "admin,producer"})
    appii_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        appii_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    assert len(harness.charm.kafka_config.super_users.split(";")) == len(INTERNAL_USERS)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{app_relation_id}": "mellon"}
    )

    assert len(harness.charm.kafka_config.super_users.split(";")) == (len(INTERNAL_USERS) + 1)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{appii_relation_id}": "mellon"}
    )

    assert len(harness.charm.kafka_config.super_users.split(";")) == (len(INTERNAL_USERS) + 2)

    harness.update_relation_data(appii_relation_id, "appii", {"extra-user-roles": "consumer"})

    assert len(harness.charm.kafka_config.super_users.split(";")) == (len(INTERNAL_USERS) + 1)
