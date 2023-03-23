#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import io
import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.model import BlockedStatus, WaitingStatus
from ops.testing import Harness
from tenacity.wait import wait_none

from charm import KafkaK8sCharm
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    CONTAINER,
    INTER_BROKER_USER,
    PEER,
    REL_NAME,
    STORAGE,
    ZOOKEEPER_REL_NAME,
)

logger = logging.getLogger(__name__)

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaK8sCharm, meta=METADATA)
    harness.set_can_connect(CONTAINER, True)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()
    with harness.hooks_disabled():
        harness.add_storage(storage_name=STORAGE, attach=True)
    return harness


def test_opts_in_pebble_layer(harness):
    """Checks KAFKA_OPTS is present as an env-var in pebble layer."""
    layer = harness.charm._kafka_layer.to_dict()

    assert layer["services"][CONTAINER].get("environment", {}).get("KAFKA_OPTS")


def test_pebble_ready_waits_until_zookeeper_relation(harness):
    """Checks unit goes to WaitingStatus without ZK relation on install hook."""
    harness.container_pebble_ready(CONTAINER)
    assert isinstance(harness.charm.unit.status, WaitingStatus)


def test_leader_elected_sets_passwords(harness):
    """Checks inter-broker passwords are created on leaderelected hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.set_leader(True)

    assert harness.charm.app_peer_data.get("sync-password", None)


def test_zookeeper_joined_sets_chroot(harness):
    """Checks chroot is added to ZK relation data on ZKrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    harness.set_leader(True)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")

    assert CHARM_KEY in harness.charm.model.relations[ZOOKEEPER_REL_NAME][0].data[
        harness.charm.app
    ].get("chroot", "")


def test_zookeeper_broken_stops_service(harness):
    """Checks service stops and unit blocks on ZKrelationbroken hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)

    with patch("ops.model.Container.stop") as patched_stop:
        harness.remove_relation(zk_rel_id)

        patched_stop.assert_called_once()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_pebble_ready_defers_without_zookeeper(harness):
    """Checks event deferred and not lost without ZK relation on pebble_ready hook."""
    with patch("ops.framework.EventBase.defer") as patched_defer:
        harness.container_pebble_ready(CONTAINER)

        patched_defer.assert_called_once()


def test_pebble_ready_sets_necessary_config(harness):
    """Checks event writes all needed config to unit on pebble_ready hook."""
    harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )

    with (
        patch("config.KafkaConfig.set_zk_jaas_config") as patched_jaas,
        patch("config.KafkaConfig.set_server_properties") as patched_server_properties,
        patch("config.KafkaConfig.set_client_properties") as patched_client_properties,
    ):
        harness.container_pebble_ready(CONTAINER)
        patched_jaas.assert_called_once()
        patched_server_properties.assert_called_once()
        patched_client_properties.assert_called_once()


def test_pebble_ready_sets_auth_and_broker_creds_on_leader(harness):
    """Checks inter-broker user is created on leader on pebble_ready hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("auth.KafkaAuth.add_user") as patched_add_user,
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("charm.broker_active") as patched_broker_active,
    ):
        # verify non-leader does not set creds
        patched_broker_active.retry.wait = wait_none
        harness.container_pebble_ready(CONTAINER)
        patched_add_user.assert_not_called()
        assert not harness.charm.app_peer_data.get("broker-creds", None)

        # verify leader sets creds
        harness.set_leader(True)
        harness.container_pebble_ready(CONTAINER)
        patched_add_user.assert_called()

        for call in patched_add_user.call_args_list:
            assert call.kwargs["username"] in [INTER_BROKER_USER, ADMIN_USER]

        assert harness.charm.app_peer_data.get("broker-creds", None)


def test_pebble_ready_does_not_start_if_not_ready(harness):
    """Checks service does not start before ready on pebble_ready hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "disabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("auth.KafkaAuth.add_user"),
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=False),
        patch("ops.framework.EventBase.defer") as patched_defer,
        patch("ops.model.Container.start") as patched_start,
    ):
        harness.container_pebble_ready(CONTAINER)

        patched_start.assert_not_called()
        patched_defer.assert_called()


def test_pebble_ready_does_not_start_if_not_same_tls_as_zk(harness):
    """Checks service does not start if mismatch Kafka+ZK TLS on pebble_ready hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("auth.KafkaAuth.add_user"),
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("ops.model.Container.start") as patched_start,
    ):
        harness.container_pebble_ready(CONTAINER)

        patched_start.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_pebble_ready_does_not_start_if_leader_has_not_set_creds(harness):
    """Checks service does not start without inter-broker creds on pebble_ready hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("ops.model.Container.start") as patched_start,
    ):
        harness.container_pebble_ready(CONTAINER)

        patched_start.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


def test_config_changed_updates_properties(harness):
    """Checks that new charm/unit config writes config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("config.KafkaConfig.set_client_properties"),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties") as set_props,
    ):
        harness.charm.on.config_changed.emit()

        set_props.assert_called_once()


def test_start_does_not_start_if_leader_has_not_set_creds(harness):
    """Checks snap service does not start without inter-broker creds on start hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_rel_id, "zookeeper/0")
    harness.update_relation_data(
        zk_rel_id,
        ZOOKEEPER_REL_NAME,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})

    with (
        patch("config.KafkaConfig.set_zk_jaas_config"),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("ops.model.Container.start") as patched_start,
    ):
        harness.charm.on.start.emit()

        patched_start.assert_not_called()
        assert isinstance(harness.charm.unit.status, BlockedStatus)


# def test_start_blocks_if_service_failed_silently(harness):
#     """Checks unit is not ActiveStatus if snap service start failed silently on start hook."""
#     peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
#     zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
#     harness.add_relation_unit(zk_rel_id, "zookeeper/0")
#     harness.set_leader(True)
#     harness.update_relation_data(
#         zk_rel_id,
#         ZOOKEEPER_REL_NAME,
#         {
#             "username": "relation-1",
#             "password": "mellon",
#             "endpoints": "123.123.123",
#             "chroot": "/kafka",
#             "uris": "123.123.123/kafka",
#             "tls": "disabled",
#         },
#     )
#     harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})
#     harness.set_leader(True)

#     with (
#         patch("auth.KafkaAuth.add_user"),
#         patch("config.KafkaConfig.set_zk_jaas_config"),
#         patch("config.KafkaConfig.set_server_properties"),
#         patch("config.KafkaConfig.set_client_properties"),
#         patch("ops.model.Container.start") as patched_start,
#         patch("charm.broker_active", return_value=False) as patched_broker_active,
#         patch("config.KafkaConfig.internal_user_credentials", return_value="orthanc"),
#         patch("config.KafkaConfig.zookeeper_connected", return_value=True),
#     ):
#         patched_broker_active.retry.wait = wait_none
#         harness.charm.on.start.emit()

#         patched_start.assert_called_once()
#         assert isinstance(harness.charm.unit.status, BlockedStatus)


# def test_storage_add_remove_triggers_restart(harness):
#     """Checks if unit restarts during storage events."""
#     peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
#     zk_rel_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
#     harness.add_relation_unit(zk_rel_id, "zookeeper/0")
#     harness.update_relation_data(
#         zk_rel_id,
#         ZOOKEEPER_REL_NAME,
#         {
#             "username": "relation-1",
#             "password": "mellon",
#             "endpoints": "123.123.123",
#             "chroot": "/kafka",
#             "uris": "123.123.123/kafka",
#             "tls": "disabled",
#         },
#     )
#     harness.update_relation_data(peer_rel_id, CHARM_KEY, {"sync-password": "mellon"})
#     harness.set_leader(True)

#     with (
#         patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
#         patch(
#             "ops.model.Container.pull", return_value=["log.dirs=/var/snap/charmed-kafka/common/logs/0"]
#         ),
#         patch("config.KafkaConfig.set_server_properties"),
#         patch("config.KafkaConfig.set_client_properties"),
#         patch("charm.broker_active", return_value=True),

#         patch("snap.KafkaSnap.disable_enable") as patched_disable_enable,
#     ):
#         harness.add_storage(storage_name="log-data", count=2)
#         harness.attach_storage(storage_id="log-data/1")
#         patched_disable_enable.assert_called_once()
#         assert not isinstance(harness.charm.unit.status, BlockedStatus)

#         patched_disable_enable.reset_mock()

#         harness.remove_storage(storage_id="log-data/1")
#         patched_disable_enable.assert_called_once()


def test_config_changed_updates_server_properties(harness):
    """Checks that new charm/unit config writes server config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties") as set_server_properties,
        patch("config.KafkaConfig.set_client_properties"),
    ):
        harness.charm.on.config_changed.emit()

        set_server_properties.assert_called_once()


def test_config_changed_updates_client_properties(harness):
    """Checks that new charm/unit config writes client config to unit on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")

    with (
        patch(
            "config.KafkaConfig.client_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["sauron=bad"],
        ),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties") as set_client_properties,
    ):
        harness.charm.on.config_changed.emit()

        set_client_properties.assert_called_once()


def test_config_changed_updates_client_data(harness):
    """Checks that provided relation data updates on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.add_relation(REL_NAME, "app")

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=white"],
        ),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=white")),
        patch("provider.KafkaProvider.update_connection_info") as patched_update_connection_info,
    ):
        harness.set_leader(True)
        harness.charm.on.config_changed.emit()

        patched_update_connection_info.assert_called_once()


def test_config_changed_restarts(harness):
    """Checks units rolling-restat on config changed hook."""
    peer_rel_id = harness.add_relation(PEER, CHARM_KEY)
    harness.add_relation_unit(peer_rel_id, f"{CHARM_KEY}/0")
    harness.update_relation_data(peer_rel_id, harness.charm.unit.name, {"state": "started"})

    with (
        patch(
            "config.KafkaConfig.server_properties",
            new_callable=PropertyMock,
            return_value=["gandalf=grey"],
        ),
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=white")),
        patch("utils.push", return_value=None),
        patch("ops.model.Container.restart") as patched_restart,
        patch("charm.broker_active", return_value=True),
    ):
        harness.set_leader(True)
        with harness.hooks_disabled():
            harness.container_pebble_ready(CONTAINER)
        harness.charm.on.config_changed.emit()

        patched_restart.assert_called_once()
