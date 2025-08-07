#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from subprocess import PIPE, check_output

import pytest
import requests
from pytest_operator.plugin import OpsTest

from integration.helpers.pytest_operator import (
    APP_NAME,
    DUMMY_NAME,
    REL_NAME_ADMIN,
    check_external_access_non_tls,
    check_logs,
    count_lines_with,
    deploy_cluster,
    get_address,
    netcat,
    run_client_properties,
)
from literals import (
    DEPENDENCIES,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, kafka_charm, kraft_mode, controller_app):
    await deploy_cluster(
        ops_test=ops_test,
        charm=kafka_charm,
        kraft_mode=kraft_mode,
        config_broker={"expose_external": "nodeport"},
    )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[controller_app].status == "active"


@pytest.mark.abort_on_fail
async def test_consistency_between_workload_and_metadata(ops_test: OpsTest):
    application = ops_test.model.applications[APP_NAME]
    assert application.data.get("workload-version", "") == DEPENDENCIES["kafka_service"]["version"]


@pytest.mark.abort_on_fail
async def test_remove_controller_relation_relate(ops_test: OpsTest, kraft_mode, controller_app):
    if kraft_mode == "single":
        logger.info(f"Skipping because we're using {kraft_mode} mode.")
        return

    check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju remove-relation {APP_NAME} {controller_app}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, controller_app], idle_period=40, timeout=3600, raise_on_error=False
    )

    await ops_test.model.add_relation(
        f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
        f"{controller_app}:{PEER_CLUSTER_RELATION}",
    )

    async with ops_test.fast_forward(fast_interval="90s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, controller_app],
            status="active",
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )


@pytest.mark.abort_on_fail
async def test_listeners(ops_test: OpsTest, app_charm, kafka_apps):
    address = await get_address(ops_test=ops_test)
    assert netcat(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
    )  # Internal listener
    # Client listener should not be enable if there is no relations
    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # Add relation with dummy app
    await asyncio.gather(
        ops_test.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME], idle_period=30, status="active", timeout=2000
        )

    # check that client listener is active
    assert netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, idle_period=60, status="active", timeout=600
    )

    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)


@pytest.mark.abort_on_fail
async def test_client_properties_makes_admin_connection(ops_test: OpsTest, kafka_apps, kraft_mode):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME], idle_period=30, status="active", timeout=800
        )

    result = await run_client_properties(ops_test=ops_test)
    assert result
    # single mode: admin, sync, relation-# => 3
    # multi mode: admin, relation-# => 2
    assert len(result.strip().split("\n")) == 2 + int(kraft_mode == "single")

    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, idle_period=60, status="active", timeout=600
    )


@pytest.mark.abort_on_fail
async def test_logs_write_to_storage(ops_test: OpsTest, kafka_apps):
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME], idle_period=30, status="active", timeout=800
        )

    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    await action.wait()

    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    check_logs(
        ops_test=ops_test,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )


@pytest.mark.abort_on_fail
async def test_external_listeners_bootstrap(ops_test: OpsTest):
    check_external_access_non_tls(ops_test, f"{APP_NAME}/0")


@pytest.mark.abort_on_fail
async def test_exporter_endpoints(ops_test: OpsTest):
    unit_address = await get_address(ops_test=ops_test)
    jmx_exporter_url = f"http://{unit_address}:9101/metrics"
    jmx_resp = requests.get(jmx_exporter_url)

    assert jmx_resp.ok


@pytest.mark.abort_on_fail
@pytest.mark.skip(reason="No feature yet, needs newer image")
async def test_log_level_change(ops_test: OpsTest):
    for unit in ops_test.model.applications[APP_NAME].units:
        total_lines = count_lines_with(
            ops_test,
            unit.name,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines == 0

    await ops_test.model.applications[APP_NAME].set_config({"log_level": "DEBUG"})
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=30
    )

    for unit in ops_test.model.applications[APP_NAME].units:
        total_lines = count_lines_with(
            ops_test,
            unit.name,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines > 0

    # cleanup
    await ops_test.model.applications[APP_NAME].set_config({"log_level": "INFO"})
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000, idle_period=30
    )
