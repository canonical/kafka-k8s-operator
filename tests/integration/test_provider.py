#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import PosixPath
from typing import Set

import pytest
from pytest_operator.plugin import OpsTest

from literals import TLS_RELATION

from .helpers import (
    APP_NAME,
    REL_NAME_ADMIN,
    check_user,
    deploy_cluster,
    get_client_usernames,
    get_node_port,
    get_provider_data,
    load_acls,
    load_super_users,
    netcat,
)

logger = logging.getLogger(__name__)

DUMMY_NAME_1 = "app"
DUMMY_NAME_2 = "appii"
TLS_NAME = "self-signed-certificates"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_charms_relate_active(
    ops_test: OpsTest,
    kafka_charm,
    app_charm: PosixPath,
    usernames: Set[str],
    kraft_mode,
    kafka_apps,
):
    """Test deploy and relate operations."""
    await asyncio.gather(
        deploy_cluster(
            ops_test=ops_test,
            charm=kafka_charm,
            kraft_mode=kraft_mode,
            config_broker={"expose_external": "nodeport"},
            num_controller=3,
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME_1, num_units=1, trust=True),
    )
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME_1],
            idle_period=30,
            status="active",
            timeout=2000,
            raise_on_error=False,
        )

    usernames.update(get_client_usernames(ops_test))

    for username in usernames:
        check_user(
            username=username,
            model_full_name=ops_test.model_full_name,
        )

    for acl in load_acls(model_full_name=ops_test.model_full_name):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"
        if acl.resource_type == "GROUP":
            assert acl.resource_name == "test-prefix"


@pytest.mark.abort_on_fail
async def test_deploy_multiple_charms_same_topic_relate_active(
    ops_test: OpsTest, app_charm: PosixPath, usernames: Set[str], kafka_apps
):
    """Test relation with multiple applications."""
    await ops_test.model.deploy(app_charm, application_name=DUMMY_NAME_2, num_units=1, trust=True)
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME_2}:{REL_NAME_CONSUMER}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME_1], idle_period=30, status="active"
        )

    usernames.update(get_client_usernames(ops_test))
    for username in usernames:
        check_user(
            username=username,
            model_full_name=ops_test.model_full_name,
        )

    for acl in load_acls(model_full_name=ops_test.model_full_name):
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"


@pytest.mark.abort_on_fail
async def test_remove_application_removes_user_and_acls(
    ops_test: OpsTest, usernames: Set[str], kafka_apps
):
    """Test the correct removal of user and permission after relation removal."""
    await ops_test.model.remove_application(DUMMY_NAME_1, block_until_done=True)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(apps=kafka_apps, idle_period=30, status="active")

    # checks that old users are removed from active cluster ACLs

    acls = load_acls(model_full_name=ops_test.model_full_name)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    assert acl_usernames != usernames

    # checks that past usernames no longer exist
    with pytest.raises(AssertionError):
        for username in usernames:
            check_user(
                username=username,
                model_full_name=ops_test.model_full_name,
            )


@pytest.mark.abort_on_fail
async def test_deploy_producer_same_topic(
    ops_test: OpsTest, app_charm: PosixPath, usernames: Set[str], kafka_apps
):
    """Test the correct deployment and relation with role producer."""
    await asyncio.gather(
        ops_test.model.deploy(
            app_charm,
            application_name=DUMMY_NAME_1,
            num_units=1,
            series="jammy",
            trust=True,
        )
    )
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_PRODUCER}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME_1], idle_period=30, status="active"
        )

    acls = load_acls(model_full_name=ops_test.model_full_name)
    acl_usernames = set()
    for acl in acls:
        acl_usernames.add(acl.username)

    usernames.update(get_client_usernames(ops_test))

    for acl in acls:
        assert acl.username in usernames
        assert acl.operation in ["READ", "DESCRIBE", "CREATE", "WRITE"]
        assert acl.resource_type in ["GROUP", "TOPIC"]
        if acl.resource_type == "TOPIC":
            assert acl.resource_name == "test-topic"

    # remove application
    await ops_test.model.remove_application(DUMMY_NAME_1, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=kafka_apps, idle_period=30, status="active")


@pytest.mark.abort_on_fail
async def test_admin_added_to_super_users(ops_test: OpsTest, kafka_apps):
    """Test relation with admin privileges."""
    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 3  # controller, sync, admin

    app_charm = await ops_test.build_charm("tests/integration/app-charm")

    await asyncio.gather(
        ops_test.model.deploy(
            app_charm,
            application_name=DUMMY_NAME_1,
            num_units=1,
            series="jammy",
            trust=True,
        )
    )
    await ops_test.model.wait_for_idle(apps=[*kafka_apps, DUMMY_NAME_1])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_ADMIN}")
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME_1], status="active", idle_period=30
    )

    # check the correct addition of super-users
    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 4


@pytest.mark.abort_on_fail
async def test_admin_removed_from_super_users(ops_test: OpsTest, kafka_apps):
    """Test that removal of the relation with admin privileges."""
    await ops_test.model.remove_application(DUMMY_NAME_1, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=kafka_apps, status="active", idle_period=30)
    assert ops_test.model.applications[APP_NAME].status == "active"

    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME_2], status="active", idle_period=30
    )
    assert ops_test.model.applications[APP_NAME].status == "active"

    super_users = load_super_users(model_full_name=ops_test.model_full_name)
    assert len(super_users) == 3

    # adding cleanup to save memory
    await ops_test.model.remove_application(DUMMY_NAME_2, block_until_done=True)


@pytest.mark.abort_on_fail
async def test_connection_updated_on_tls_enabled(
    ops_test: OpsTest, app_charm: PosixPath, kafka_apps
):
    """Test relation when TLS is enabled."""
    # adding new app unit to validate
    await ops_test.model.deploy(app_charm, application_name=DUMMY_NAME_1, num_units=1, trust=True)
    await ops_test.model.wait_for_idle(apps=[DUMMY_NAME_1])
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME_1}:{REL_NAME_CONSUMER}")
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME_1], status="active", idle_period=30
    )

    # deploying tls
    tls_config = {"ca-common-name": "kafka"}
    # FIXME (certs): Unpin the revision once the charm is fixed
    await ops_test.model.deploy(
        TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True
    )
    await ops_test.model.wait_for_idle(
        apps=[TLS_NAME], idle_period=30, timeout=1800, status="active"
    )

    # relating tls with kafka
    await ops_test.model.add_relation(TLS_NAME, f"{APP_NAME}:{TLS_RELATION}")
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, TLS_NAME, DUMMY_NAME_1],
        timeout=1800,
        idle_period=60,
        status="active",
    )

    # ensure at least one update-status run
    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(60)

    # Check that related application has updated information
    provider_data = get_provider_data(
        ops_test=ops_test,
        unit_name=f"{DUMMY_NAME_1}/0",
        relation_interface="kafka-client-consumer",
        owner=APP_NAME,
    )

    tls_bootstrap_port = str(get_node_port(ops_test, APP_NAME, "sasl-ssl-scram-bootstrap-port"))

    assert provider_data["tls"] == "enabled"
    assert tls_bootstrap_port in provider_data["endpoints"]
    assert "test-prefix" in provider_data["consumer-group-prefix"]
    assert "test-topic" in provider_data["topic"]
    assert len(provider_data["endpoints"].split(",")) == 1  # aka single bootstrap service returned

    provided_host, provided_port = provider_data["endpoints"].split(":")

    assert netcat(provided_host, int(provided_port))
