#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
from pathlib import Path
from unittest.mock import Mock, PropertyMock, mock_open, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    CONTAINER,
    DEPENDENCIES,
    INTER_BROKER_USER,
    INTERNAL_USERS,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    OAUTH_REL_NAME,
    PEER,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SUBSTRATE,
    ZK,
)
from managers.config import ConfigManager

pytestmark = pytest.mark.broker

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
CONFIG = str(yaml.safe_load(Path(BASE_DIR + "/config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path(BASE_DIR + "/actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path(BASE_DIR + "/metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA, actions=ACTIONS, config=CONFIG)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    return harness


def test_all_storages_in_log_dirs(harness: Harness[KafkaCharm]):
    """Checks that the log.dirs property updates with all available storages."""
    storage_metadata = harness.charm.meta.storages["data"]
    min_storages = storage_metadata.multiple_range[0] if storage_metadata.multiple_range else 1
    with harness.hooks_disabled():
        harness.add_storage(storage_name="data", count=min_storages, attach=True)

    assert len(harness.charm.state.log_dirs.split(",")) == len(
        harness.charm.model.storages["data"]
    )


def test_internal_credentials_only_return_when_all_present(harness: Harness[KafkaCharm]):
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.update_relation_data(
        peer_rel_id, CHARM_KEY, {f"{INTERNAL_USERS[0]}-password": "mellon"}
    )

    assert not harness.charm.state.cluster.internal_user_credentials

    for user in INTERNAL_USERS:
        harness.update_relation_data(peer_rel_id, CHARM_KEY, {f"{user}-password": "mellon"})

    assert harness.charm.state.cluster.internal_user_credentials
    assert len(harness.charm.state.cluster.internal_user_credentials) == len(INTERNAL_USERS)


def test_log_dirs_in_server_properties(harness: Harness[KafkaCharm]):
    """Checks that log.dirs are added to server_properties."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    found_log_dirs = False
    with patch(
        "core.models.KafkaCluster.internal_user_credentials",
        new_callable=PropertyMock,
        return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
    ):
        for prop in harness.charm.broker.config_manager.server_properties:
            if "log.dirs" in prop:
                found_log_dirs = True

        assert found_log_dirs


def test_listeners_in_server_properties(harness: Harness[KafkaCharm], monkeypatch):
    """Checks that listeners are split into INTERNAL, CLIENT and EXTERNAL."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )
    harness.add_relation(REL_NAME, "app")

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    sasl_pm = "SASL_PLAINTEXT_SCRAM_SHA_512"

    expected_listeners = [
        f"INTERNAL_{sasl_pm}://0.0.0.0:19092",
        f"CLIENT_{sasl_pm}://0.0.0.0:9092",
        f"EXTERNAL_{sasl_pm}://0.0.0.0:29092",
    ]
    expected_advertised_listeners = [
        f"INTERNAL_{sasl_pm}://{host}:19092",
        f"CLIENT_{sasl_pm}://{host}:9092",
        f"EXTERNAL_{sasl_pm}://1234:20000",  # values for nodeip:nodeport in conftest
    ]

    with patch(
        "core.models.KafkaCluster.internal_user_credentials",
        new_callable=PropertyMock,
        return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
    ):
        # Harness doesn't reinitialize KafkaCharm when calling update_config, which means that
        # self.config is not passed again to ConfigManager
        monkeypatch.setattr(
            harness.charm.broker.config_manager.config, "expose_external", Mock(return_value=True)
        )

        listeners = [
            prop
            for prop in harness.charm.broker.config_manager.server_properties
            if prop.startswith("listeners=")
        ][0]
        advertised_listeners = [
            prop
            for prop in harness.charm.broker.config_manager.server_properties
            if prop.startswith("advertised.listeners=")
        ][0]

    for listener in expected_listeners:
        assert listener in listeners

    for listener in expected_advertised_listeners:
        assert listener in advertised_listeners


def test_oauth_client_listeners_in_server_properties(harness: Harness[KafkaCharm]):
    """Checks that oauth client listeners are properly set when a relating through oauth."""
    harness.add_relation(ZK, CHARM_KEY)
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )

    oauth_relation_id = harness.add_relation(OAUTH_REL_NAME, "hydra")
    harness.update_relation_data(
        oauth_relation_id,
        "hydra",
        {
            "issuer_url": "issuer",
            "jwks_endpoint": "jwks",
            "authorization_endpoint": "authz",
            "token_endpoint": "token",
            "introspection_endpoint": "introspection",
            "userinfo_endpoint": "userinfo",
            "scope": "scope",
            "jwt_access_token": "False",
        },
    )

    # let's add a scram client just for fun
    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    internal_protocol, internal_port = "INTERNAL_SASL_PLAINTEXT_SCRAM_SHA_512", "19092"
    scram_client_protocol, scram_client_port = "CLIENT_SASL_PLAINTEXT_SCRAM_SHA_512", "9092"
    oauth_client_protocol, oauth_client_port = "CLIENT_SASL_PLAINTEXT_OAUTHBEARER", "9095"

    expected_listeners = (
        f"listeners={internal_protocol}://0.0.0.0:{internal_port},"
        f"{scram_client_protocol}://0.0.0.0:{scram_client_port},"
        f"{oauth_client_protocol}://0.0.0.0:{oauth_client_port}"
    )
    expected_advertised_listeners = (
        f"advertised.listeners={internal_protocol}://{host}:{internal_port},"
        f"{scram_client_protocol}://{host}:{scram_client_port},"
        f"{oauth_client_protocol}://{host}:{oauth_client_port}"
    )
    assert expected_listeners in harness.charm.broker.config_manager.server_properties
    assert expected_advertised_listeners in harness.charm.broker.config_manager.server_properties


def test_ssl_listeners_in_server_properties(harness: Harness[KafkaCharm]):
    """Checks that listeners are added after TLS relation are created."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    # Simulate data-integrator relation
    client_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(client_relation_id, "app", {"extra-user-roles": "admin,producer"})
    client_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        client_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "enabled",
        },
    )
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id,
        f"{CHARM_KEY}/0",
        {"private-address": "treebeard", "certificate": "keepitsecret"},
    )

    harness.update_relation_data(
        peer_relation_id, CHARM_KEY, {"tls": "enabled", "mtls": "enabled"}
    )

    host = "treebeard" if SUBSTRATE == "vm" else "kafka-k8s-0.kafka-k8s-endpoints"
    sasl_pm = "SASL_SSL_SCRAM_SHA_512"
    ssl_pm = "SSL_SSL"
    expected_listeners = f"listeners=INTERNAL_{sasl_pm}://0.0.0.0:19093,CLIENT_{sasl_pm}://0.0.0.0:9093,CLIENT_{ssl_pm}://0.0.0.0:9094"
    expected_advertised_listeners = f"advertised.listeners=INTERNAL_{sasl_pm}://{host}:19093,CLIENT_{sasl_pm}://{host}:9093,CLIENT_{ssl_pm}://{host}:9094"

    with patch(
        "core.models.KafkaCluster.internal_user_credentials",
        new_callable=PropertyMock,
        return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
    ):
        assert expected_listeners in harness.charm.broker.config_manager.server_properties
        assert (
            expected_advertised_listeners in harness.charm.broker.config_manager.server_properties
        )


def test_zookeeper_config_succeeds_fails_config(harness: Harness[KafkaCharm]):
    """Checks that no ZK config is returned if missing field."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert not harness.charm.state.zookeeper.zookeeper_connected


def test_zookeeper_config_succeeds_valid_config(harness: Harness[KafkaCharm]):
    """Checks that ZK config is returned if all fields."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert harness.charm.state.zookeeper.connect == "1.1.1.1:2181,2.2.2.2:2181/kafka"
    assert harness.charm.state.zookeeper.zookeeper_connected


def test_kafka_opts(harness: Harness[KafkaCharm]):
    """Checks necessary args for KAFKA_OPTS."""
    args = harness.charm.broker.config_manager.kafka_opts
    assert "-Djava.security.auth.login.config" in args
    assert "KAFKA_OPTS" in args


@pytest.mark.parametrize(
    "profile,expected",
    [("production", JVM_MEM_MAX_GB), ("testing", JVM_MEM_MIN_GB)],
)
def test_heap_opts(harness: Harness[KafkaCharm], profile, expected):
    """Checks necessary args for KAFKA_HEAP_OPTS."""
    # Harness doesn't reinitialize KafkaCharm when calling update_config, which means that
    # self.config is not passed again to ConfigManager
    harness.update_config({"profile": profile})
    conf_manager = ConfigManager(
        harness.charm.state, harness.charm.workload, harness.charm.config, "1"
    )
    args = conf_manager.heap_opts

    assert f"Xms{expected}G" in args
    assert f"Xmx{expected}G" in args
    assert "KAFKA_HEAP_OPTS" in args


def test_kafka_jmx_opts(harness: Harness[KafkaCharm]):
    """Checks necessary args for KAFKA_JMX_OPTS."""
    args = harness.charm.broker.config_manager.kafka_jmx_opts
    assert "-javaagent:" in args
    assert args.split(":")[1].split("=")[-1] == str(JMX_EXPORTER_PORT)
    assert "KAFKA_JMX_OPTS" in args


def test_cc_jmx_opts(harness: Harness[KafkaCharm]):
    """Checks necessary args for CC_JMX_OPTS."""
    args = harness.charm.broker.config_manager.cc_jmx_opts
    assert "-javaagent:" in args
    assert args.split(":")[1].split("=")[-1] == str(JMX_CC_PORT)
    assert "CC_JMX_OPTS" in args


def test_set_environment(harness: Harness[KafkaCharm]):
    """Checks all necessary env-vars are written to /etc/environment."""
    with (
        patch("workload.KafkaWorkload.write") as patched_write,
        patch("builtins.open", mock_open()),
        patch("shutil.chown"),
    ):
        harness.charm.broker.config_manager.set_environment()

        for call in patched_write.call_args_list:
            assert "KAFKA_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_LOG4J_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_JMX_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_HEAP_OPTS" in call.kwargs.get("content", "")
            assert "KAFKA_JVM_PERFORMANCE_OPTS" in call.kwargs.get("content", "")
            assert "/etc/environment" == call.kwargs.get("path", "")


def test_bootstrap_server(harness: Harness[KafkaCharm]):
    """Checks the bootstrap-server property setting."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.update_relation_data(
        peer_relation_id, f"{CHARM_KEY}/0", {"private-address": "treebeard"}
    )
    harness.update_relation_data(peer_relation_id, f"{CHARM_KEY}/1", {"private-address": "shelob"})

    assert len(harness.charm.state.bootstrap_server.split(",")) == 2
    for server in harness.charm.state.bootstrap_server.split(","):
        assert "9092" in server


def test_default_replication_properties_less_than_three(harness: Harness[KafkaCharm]):
    """Checks replication property defaults updates with units < 3."""
    assert "num.partitions=1" in harness.charm.broker.config_manager.default_replication_properties
    assert (
        "default.replication.factor=1"
        in harness.charm.broker.config_manager.default_replication_properties
    )
    assert (
        "min.insync.replicas=1"
        in harness.charm.broker.config_manager.default_replication_properties
    )


def test_default_replication_properties_more_than_three(harness: Harness[KafkaCharm]):
    """Checks replication property defaults updates with units > 3."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/1")
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/2")
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/3")
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/4")
    harness.add_relation_unit(peer_relation_id, f"{CHARM_KEY}/5")

    assert "num.partitions=3" in harness.charm.broker.config_manager.default_replication_properties
    assert (
        "default.replication.factor=3"
        in harness.charm.broker.config_manager.default_replication_properties
    )
    assert (
        "min.insync.replicas=2"
        in harness.charm.broker.config_manager.default_replication_properties
    )


def test_ssl_principal_mapping_rules(harness: Harness[KafkaCharm]):
    """Check that a change in ssl_principal_mapping_rules is reflected in server_properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    with patch(
        "core.models.KafkaCluster.internal_user_credentials",
        new_callable=PropertyMock,
        return_value={INTER_BROKER_USER: "fangorn", ADMIN_USER: "forest"},
    ):
        # Harness doesn't reinitialize KafkaCharm when calling update_config, which means that
        # self.config is not passed again to ConfigManager
        harness._update_config({"ssl_principal_mapping_rules": "RULE:^(erebor)$/$1,DEFAULT"})
        conf_manager = ConfigManager(
            harness.charm.state, harness.charm.workload, harness.charm.config, "1"
        )

        assert (
            "ssl.principal.mapping.rules=RULE:^(erebor)$/$1,DEFAULT"
            in conf_manager.server_properties
        )


def test_auth_properties(harness: Harness[KafkaCharm]):
    """Checks necessary auth properties are present."""
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {"sync_password": "mellon"}
    )
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    assert "broker.id=0" in harness.charm.broker.config_manager.auth_properties
    assert (
        f"zookeeper.connect={harness.charm.state.zookeeper.connect}"
        in harness.charm.broker.config_manager.auth_properties
    )


def test_rack_properties(harness: Harness[KafkaCharm]):
    """Checks that rack properties are added to server properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )

    with patch(
        "managers.config.ConfigManager.rack_properties",
        new_callable=PropertyMock,
        return_value=["broker.rack=gondor-west"],
    ):
        assert "broker.rack=gondor-west" in harness.charm.broker.config_manager.server_properties


def test_inter_broker_protocol_version(harness: Harness[KafkaCharm]):
    """Checks that rack properties are added to server properties."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_relation_id = harness.add_relation(ZK, CHARM_KEY)
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "database": "/kafka",
            "chroot": "/kafka",
            "username": "moria",
            "password": "mellon",
            "endpoints": "1.1.1.1,2.2.2.2",
            "uris": "1.1.1.1:2181/kafka,2.2.2.2:2181/kafka",
            "tls": "disabled",
        },
    )
    assert len(DEPENDENCIES["kafka_service"]["version"].split(".")) == 3

    assert (
        "inter.broker.protocol.version=3.6"
        in harness.charm.broker.config_manager.server_properties
    )


def test_super_users(harness: Harness[KafkaCharm]):
    """Checks super-users property is updated for new admin clients."""
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    app_relation_id = harness.add_relation("kafka-client", "app")
    harness.update_relation_data(app_relation_id, "app", {"extra-user-roles": "admin,producer"})
    appii_relation_id = harness.add_relation("kafka-client", "appii")
    harness.update_relation_data(
        appii_relation_id, "appii", {"extra-user-roles": "admin,consumer"}
    )

    assert len(harness.charm.state.super_users.split(";")) == len(INTERNAL_USERS)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{app_relation_id}": "mellon"}
    )

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 1)

    harness.update_relation_data(
        peer_relation_id, harness.charm.app.name, {f"relation-{appii_relation_id}": "mellon"}
    )

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 2)

    harness.update_relation_data(appii_relation_id, "appii", {"extra-user-roles": "consumer"})

    assert len(harness.charm.state.super_users.split(";")) == (len(INTERNAL_USERS) + 1)


def test_cruise_control_reporter_only_with_balancer(harness: Harness[KafkaCharm]):
    reporters_config_value = "metric.reporters=com.linkedin.kafka.cruisecontrol.metricsreporter.CruiseControlMetricsReporter"
    # Default roles value does not include balancer
    assert reporters_config_value not in harness.charm.broker.config_manager.server_properties

    # FIXME: change peer_cluster_relation to peer_cluster_orchestrator_relations after the center-of-star
    #  change is effective
    with harness.hooks_disabled():
        harness.add_relation(PEER_CLUSTER_RELATION, "balancer")

    assert reporters_config_value in harness.charm.broker.config_manager.server_properties
