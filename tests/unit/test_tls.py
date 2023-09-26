#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaK8sCharm
from literals import CHARM_KEY, PEER, ZOOKEEPER_REL_NAME

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))


@pytest.fixture
def harness():
    harness = Harness(KafkaK8sCharm, meta=METADATA)
    harness.add_relation("restart", CHARM_KEY)
    harness._update_config(
        {
            "log_retention_ms": "-1",
            "compression_type": "producer",
        }
    )
    harness.begin()

    # Relate to ZK with tls enabled
    zk_relation_id = harness.add_relation(ZOOKEEPER_REL_NAME, ZOOKEEPER_REL_NAME)
    harness.add_relation_unit(zk_relation_id, "zookeeper/0")
    harness.update_relation_data(
        zk_relation_id,
        harness.charm.app.name,
        {
            "username": "relation-1",
            "password": "mellon",
            "endpoints": "123.123.123",
            "chroot": "/kafka",
            "uris": "123.123.123/kafka",
            "tls": "enabled",
        },
    )

    return harness


def test_extra_sans_config(harness: Harness):
    # Create peer relation
    peer_relation_id = harness.add_relation(PEER, CHARM_KEY)
    harness.update_relation_data(
        peer_relation_id,
        "kafka-k8s/0",
        {"private-address": "treebeard", "tls": "enabled"},
    )

    harness.update_config({"certificate_extra_sans": ""})
    assert harness.charm.tls._extra_sans == []

    harness.update_config({"certificate_extra_sans": "worker{unit}.com"})
    assert harness.charm.tls._extra_sans == ["worker0.com"]

    harness.update_config({"certificate_extra_sans": "worker{unit}.com,{unit}.example"})
    assert harness.charm.tls._extra_sans == ["worker0.com", "0.example"]
