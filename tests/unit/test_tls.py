#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import socket
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from scenario import Container, Context, PeerRelation, Relation, State

from charm import KafkaCharm
from literals import (
    CHARM_KEY,
    CONTAINER,
    PEER,
    SUBSTRATE,
)

pytestmark = pytest.mark.broker


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def charm_configuration():
    """Enable direct mutation on configuration dict."""
    return json.loads(json.dumps(CONFIG))


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


def test_mtls_not_enabled_if_trusted_certificate_added_before_tls_relation(
    ctx: Context, base_state: State
) -> None:
    # Given
    cluster_peer = PeerRelation(PEER, PEER)
    cert_relation = Relation("trusted-certificate", "tls-one")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, cert_relation])

    # When
    state_out = ctx.run(ctx.on.relation_created(cert_relation), state_in)

    # Then
    assert (
        state_out.get_relation(cluster_peer.id).local_app_data.get("mtls", "disabled") != "enabled"
    )


def test_mtls_added(ctx: Context, base_state: State) -> None:
    # Given
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_app_data={"tls": "enabled"},
        local_unit_data={"private-address": "treebeard"},
    )
    cert_relation = Relation("trusted-certificate", "tls-one")
    state_in = dataclasses.replace(base_state, relations=[cluster_peer, cert_relation])

    # Given
    state_out = ctx.run(ctx.on.relation_created(cert_relation), state_in)

    # Then
    assert (
        state_out.get_relation(cluster_peer.id).local_app_data.get("mtls", "disabled") == "enabled"
    )


@pytest.mark.parametrize(
    ["extra_sans", "expected"],
    [
        ("", []),
        ("worker{unit}.com", ["worker0.com"]),
        ("worker{unit}.com,{unit}.example", ["worker0.com", "0.example"]),
    ],
)
def test_extra_sans_config(
    charm_configuration: dict, base_state: State, extra_sans: str, expected: list[str]
) -> None:
    # Given
    charm_configuration["options"]["certificate_extra_sans"]["default"] = extra_sans
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard"},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )

    # When
    with ctx(ctx.on.config_changed(), state_in) as manager:
        charm = cast(KafkaCharm, manager.charm)

        # Then
        assert charm.broker.tls_manager._build_extra_sans() == expected


def test_sans(charm_configuration: dict, base_state: State, patched_node_ip) -> None:
    # Given
    charm_configuration["options"]["certificate_extra_sans"]["default"] = "worker{unit}.com"
    cluster_peer = PeerRelation(
        PEER,
        PEER,
        local_unit_data={"private-address": "treebeard"},
    )
    state_in = dataclasses.replace(base_state, relations=[cluster_peer])
    ctx = Context(
        KafkaCharm, meta=METADATA, config=charm_configuration, actions=ACTIONS, unit_id=0
    )
    sock_dns = socket.getfqdn()

    # When
    if SUBSTRATE == "vm":
        with ctx(ctx.on.config_changed(), state_in) as manager:
            charm = cast(KafkaCharm, manager.charm)
            built_sans = charm.broker.tls_manager.build_sans()

        # Then
        assert built_sans == {
            "sans_ip": ["treebeard"],
            "sans_dns": [f"{CHARM_KEY}/0", sock_dns, "worker0.com"],
        }

    elif SUBSTRATE == "k8s":
        # NOTE previous k8s sans_ip like kafka-k8s-0.kafka-k8s-endpoints or binding pod address
        with (
            patch("ops.model.Model.get_binding"),
            patch(
                "core.models.KafkaBroker.node_ip",
                new_callable=PropertyMock,
                return_value="palantir",
            ),
            ctx(ctx.on.config_changed(), state_in) as manager,
        ):
            charm = cast(KafkaCharm, manager.charm)
            built_sans = charm.broker.tls_manager.build_sans()

        # Then
        assert sorted(built_sans["sans_dns"]) == sorted(
            [
                "kafka-k8s-0",
                "kafka-k8s-0.kafka-k8s-endpoints",
                sock_dns,
                "worker0.com",
            ]
        )
        assert "palantir" in "".join(built_sans["sans_ip"])
