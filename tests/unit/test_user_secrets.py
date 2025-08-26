#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops.testing import Container, Context, PeerRelation, Secret, State
from src.charm import KafkaCharm
from src.literals import CONTAINER, INTERNAL_USERS, PEER, SUBSTRATE

logger = logging.getLogger(__name__)
AUTH_CONFIG_KEY = "system-users"
CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state(kraft_data: dict[str, str], passwords_data: dict[str, str]):
    config = {"roles": "broker,controller"}
    peer_rel = PeerRelation(PEER, PEER, local_app_data=kraft_data | passwords_data)

    if SUBSTRATE == "k8s":
        state = State(
            leader=True,
            containers=[Container(name=CONTAINER, can_connect=True)],
            config=config,
            relations=[peer_rel],
        )

    else:
        state = State(leader=True, config=config, relations=[peer_rel])

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


@pytest.mark.parametrize("secret_provided", [True, False])
@pytest.mark.parametrize("user", INTERNAL_USERS + ["foo", "relation-7"])
def test_set_credentials(
    ctx: Context,
    base_state: State,
    secret_provided: bool,
    user: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tests setting username/passwords through secrets."""
    caplog.set_level(logging.ERROR)
    auth_secret = Secret(
        label="auth_secret",
        tracked_content={user: "newpass"},
    )
    state_in = dataclasses.replace(
        base_state,
        secrets=[auth_secret],
        config=base_state.config | ({AUTH_CONFIG_KEY: auth_secret.id} if secret_provided else {}),
    )

    with (
        ctx(ctx.on.secret_changed(auth_secret), state_in) as mgr,
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock(return_value=True)
        ),
    ):
        charm: KafkaCharm = cast(KafkaCharm, mgr.charm)
        previous_password = charm.state.cluster.internal_user_credentials.get(user)
        _ = mgr.run()

    if secret_provided and user not in INTERNAL_USERS:
        log_record = caplog.records[-1]
        assert "can't set password for non-internal user(s)" in log_record.msg.lower()
        assert log_record.levelname == "ERROR"
        return

    assert previous_password != "newpass"
    new_password = charm.state.cluster.internal_user_credentials.get(user)

    if secret_provided:
        assert new_password != previous_password
        assert new_password == "newpass"
    else:
        assert new_password == previous_password


def test_secret_removed_preserves_credentials(
    ctx: Context,
    base_state: State,
) -> None:
    """Tests removing users through secrets."""
    auth_secret = Secret(
        label="auth_secret",
        tracked_content={"admin": "newpass"},
    )
    state_in = dataclasses.replace(
        base_state,
        secrets=[auth_secret],
        config=base_state.config | {AUTH_CONFIG_KEY: auth_secret.id},
    )

    with (
        ctx(ctx.on.secret_changed(auth_secret), state_in) as mgr,
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock(return_value=True)
        ),
    ):
        charm: KafkaCharm = cast(KafkaCharm, mgr.charm)
        previous_password = charm.state.cluster.internal_user_credentials.get("admin")
        _ = mgr.run()

    state_interim = dataclasses.replace(
        state_in,
        config=base_state.config,
    )

    with (
        ctx(ctx.on.config_changed(), state_interim) as mgr,
        patch(
            "events.broker.BrokerOperator.healthy", new_callable=PropertyMock(return_value=True)
        ),
    ):
        charm: KafkaCharm = cast(KafkaCharm, mgr.charm)
        new_password = charm.state.cluster.internal_user_credentials.get("admin")
        _ = mgr.run()

    # since no secret is defined, we expect only admin user to remain
    assert previous_password == new_password
    assert len(charm.state.cluster.internal_user_credentials) == 2
    for user in INTERNAL_USERS:
        assert charm.state.cluster.internal_user_credentials[user]
