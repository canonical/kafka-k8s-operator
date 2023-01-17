#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Harness
from tests.unit.helpers import DummyExec

from auth import Acl, KafkaAuth
from charm import KafkaK8sCharm
from literals import CHARM_KEY, CONTAINER, PEER, ZOOKEEPER_REL_NAME

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
            "offsets-retention-minutes": 10080,
            "log-retention-hours": 168,
            "auto-create-topics": False,
        }
    )

    harness.begin()
    return harness


def test_acl():
    assert sorted(Acl.__annotations__.keys()) == sorted(
        ["operation", "resource_name", "resource_type", "username"]
    )
    assert Acl.__hash__


def test_parse_acls():
    acls = """
    Current ACLs for resource `ResourcePattern(resourceType=GROUP, name=relation-81-*, patternType=LITERAL)`:
        (principal=User:relation-81, host=*, operation=READ, permissionType=ALLOW)
    Current ACLs for resource `ResourcePattern(resourceType=TOPIC, name=test-topic, patternType=LITERAL)`:
        (principal=User:relation-81, host=*, operation=WRITE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=CREATE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=DESCRIBE, permissionType=ALLOW)
        (principal=User:relation-81, host=*, operation=READ, permissionType=ALLOW)
    """

    parsed_acls = KafkaAuth._parse_acls(acls=acls)

    assert len(parsed_acls) == 5
    assert type(list(parsed_acls)[0]) == Acl


def test_generate_producer_acls():
    generated_acls = KafkaAuth._generate_producer_acls(topic="theonering", username="frodo")
    assert len(generated_acls) == 3

    operations = set()
    resource_types = set()
    for acl in generated_acls:
        operations.add(acl.operation)
        resource_types.add(acl.resource_type)

    assert sorted(operations) == sorted({"CREATE", "WRITE", "DESCRIBE"})
    assert resource_types == {"TOPIC"}


def test_generate_consumer_acls():
    generated_acls = KafkaAuth._generate_consumer_acls(topic="theonering", username="frodo")
    assert len(generated_acls) == 3

    operations = set()
    resource_types = set()
    for acl in generated_acls:
        operations.add(acl.operation)
        resource_types.add(acl.resource_type)

        if acl.resource_type == "GROUP":
            assert acl.operation == "READ"

    assert sorted(operations) == sorted({"READ", "DESCRIBE"})
    assert sorted(resource_types) == sorted({"TOPIC", "GROUP"})


def test_get_acls_tls_adds_zk_tls_flag(harness):
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
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})
    auth = KafkaAuth(
        harness.charm,
        opts=["mordor"],
        zookeeper="server.1:gandalf.the.grey",
        container=harness.charm.container,
    )

    with patch("ops.model.Container.exec", return_value=DummyExec()) as patched_exec:
        auth._get_acls_from_cluster()

        found = False
        logger.info(patched_exec.call_args.kwargs)
        for arg in patched_exec.call_args.kwargs.get("command", []):
            if "--zk-tls-config-file" in arg:
                found = True

        assert found, "--zk-tls-config-file flag not found"


def test_add_user_adds_zk_tls_flag(harness):
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
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})
    auth = KafkaAuth(
        harness.charm,
        opts=["mordor"],
        zookeeper="server.1:gandalf.the.grey",
        container=harness.charm.container,
    )

    with patch("ops.model.Container.exec", return_value=DummyExec()) as patched_exec:
        auth.add_user("samwise", "gamgee")

        found = False
        for arg in patched_exec.call_args.kwargs.get("command", []):
            if "--zk-tls-config-file" in arg:
                found = True

        assert found, "--zk-tls-config-file flag not found"


def test_delete_user_adds_zk_tls_flag(harness):
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
    harness.update_relation_data(peer_rel_id, CHARM_KEY, {"tls": "enabled"})
    auth = KafkaAuth(
        harness.charm,
        opts=["mordor"],
        zookeeper="server.1:gandalf.the.grey",
        container=harness.charm.container,
    )

    with patch("ops.model.Container.exec", return_value=DummyExec()) as patched_exec:
        auth.delete_user("samwise")

        found = False
        for arg in patched_exec.call_args.kwargs.get("command", []):
            if "--zk-tls-config-file" in arg:
                found = True

        assert found, "--zk-tls-config-file flag not found"
