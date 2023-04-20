#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import io
import logging
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaK8sCharm
from literals import CHARM_KEY, CONTAINER, PEER, REL_NAME

from .helpers import DummyExec

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
    return harness


def test_client_relation_created_defers_if_not_ready(harness):
    """Checks event is deferred if not ready on clientrelationcreated hook."""
    with harness.hooks_disabled():
        harness.add_relation(PEER, CHARM_KEY)

    with (
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=False),
        patch("auth.KafkaAuth.add_user") as patched_add_user,
        patch("ops.framework.EventBase.defer") as patched_defer,
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        # update relation to trigger on_topic_requested event
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        patched_add_user.assert_not_called()
        patched_defer.assert_called()


def test_client_relation_created_adds_user(harness):
    """Checks if new users are added on clientrelationcreated hook."""
    harness.add_relation(PEER, CHARM_KEY)
    with (
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("auth.KafkaAuth.add_user") as patched_add_user,
        patch("ops.model.Container.exec", return_value=DummyExec()),
        patch(
            "config.KafkaConfig.zookeeper_connected", new_callable=PropertyMock, return_value=True
        ),
        patch(
            "config.KafkaConfig.zookeeper_config",
            new_callable=PropertyMock,
            return_value={"connect": "yes"},
        ),
        patch("charm.KafkaK8sCharm.healthy", return_value=True),
        patch("ops.model.Container.restart"),
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        patched_add_user.assert_called_once()

        assert harness.charm.peer_relation.data[harness.charm.app].get(f"relation-{client_rel_id}")


def test_client_relation_broken_removes_user(harness):
    """Checks if users are removed on clientrelationbroken hook."""
    harness.add_relation(PEER, CHARM_KEY)
    with (
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("auth.KafkaAuth.add_user"),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("auth.KafkaAuth.delete_user") as patched_delete_user,
        patch("auth.KafkaAuth.remove_all_user_acls") as patched_remove_acls,
        patch("ops.model.Container.exec", return_value=DummyExec()),
        patch(
            "config.KafkaConfig.zookeeper_connected", new_callable=PropertyMock, return_value=True
        ),
        patch(
            "config.KafkaConfig.zookeeper_config",
            new_callable=PropertyMock,
            return_value={"connect": "yes"},
        ),
        patch("charm.KafkaK8sCharm.healthy", return_value=True),
        patch("ops.model.Container.restart"),
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        harness.update_relation_data(
            client_rel_id,
            "app",
            {"topic": "TOPIC", "extra-user-roles": "consumer,producer"},
        )

        # validating username got added
        assert harness.charm.peer_relation.data[harness.charm.app].get(f"relation-{client_rel_id}")

        harness.remove_relation(client_rel_id)

        # validating username got removed
        assert not harness.charm.peer_relation.data[harness.charm.app].get(
            f"relation-{client_rel_id}"
        )
        patched_remove_acls.assert_called_once()
        patched_delete_user.assert_called_once()


def test_client_relation_joined_sets_necessary_relation_data(harness):
    """Checks if all needed provider relation data is set on clientrelationjoined hook."""
    harness.add_relation(PEER, CHARM_KEY)
    with (
        patch("charm.KafkaK8sCharm.ready_to_start", new_callable=PropertyMock, return_value=True),
        patch("auth.KafkaAuth.add_user"),
        patch("ops.model.Container.pull", return_value=io.StringIO("gandalf=grey")),
        patch("config.KafkaConfig.set_server_properties"),
        patch("config.KafkaConfig.set_client_properties"),
        patch("ops.model.Container.exec", return_value=DummyExec()),
        patch(
            "config.KafkaConfig.zookeeper_connected", new_callable=PropertyMock, return_value=True
        ),
        patch(
            "config.KafkaConfig.zookeeper_config",
            new_callable=PropertyMock,
            return_value={"connect": "yes"},
        ),
        patch("charm.KafkaK8sCharm.healthy", return_value=True),
        patch("ops.model.Container.restart"),
    ):
        harness.set_leader(True)
        client_rel_id = harness.add_relation(REL_NAME, "app")
        client_relation = harness.charm.model.relations[REL_NAME][0]

        harness.update_relation_data(
            client_relation.id, "app", {"topic": "TOPIC", "extra-user-roles": "consumer"}
        )
        harness.add_relation_unit(client_rel_id, "app/0")
        logger.info(f"keys: {client_relation.data[harness.charm.app].keys()}")
        assert sorted(
            [
                "username",
                "password",
                "endpoints",
                "data",
                "zookeeper-uris",
                "consumer-group-prefix",
                "tls",
                "topic",
            ]
        ) == sorted(client_relation.data[harness.charm.app].keys())

        assert client_relation.data[harness.charm.app].get("tls", None) == "disabled"
        assert client_relation.data[harness.charm.app].get("zookeeper-uris", None) == "yes"
        assert (
            client_relation.data[harness.charm.app].get("username", None)
            == f"relation-{client_rel_id}"
        )
        assert (
            client_relation.data[harness.charm.app].get("consumer-group-prefix", None)
            == f"relation-{client_rel_id}-"
        )
