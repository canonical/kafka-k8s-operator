#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from subprocess import PIPE, check_output

import pytest
import requests
from jubilant_adapters import JujuFixture, gather

from literals import DEPENDENCIES, REL_NAME, SECURITY_PROTOCOL_PORTS

from .helpers import (
    APP_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_external_access_non_tls,
    check_logs,
    count_lines_with,
    get_address,
    netcat,
    run_client_properties,
)

logger = logging.getLogger(__name__)


def test_build_and_deploy(juju: JujuFixture, kafka_charm):
    gather(
        juju.ext.model.deploy(
            ZK_NAME,
            channel="3/edge",
            application_name=ZK_NAME,
            num_units=3,
            trust=True,
        ),
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
    )
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[ZK_NAME].units) == 3)
    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[ZK_NAME], timeout=1000, idle_period=30, raise_on_error=False, status="active"
        )

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME], timeout=1000, idle_period=30, status="active"
        )


def test_consistency_between_workload_and_metadata(juju: JujuFixture):
    application = juju.status().apps[APP_NAME]
    assert application.version == DEPENDENCIES["kafka_service"]["version"]


def test_remove_zk_relation_relate(juju: JujuFixture):
    check_output(
        f"JUJU_MODEL={juju.ext.model_full_name} juju remove-relation {APP_NAME} {ZK_NAME}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], idle_period=40, timeout=3600, raise_on_error=False
    )

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)

    with juju.ext.fast_forward(fast_interval="90s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME],
            status="active",
            idle_period=30,
            timeout=1000,
            raise_on_error=False,
        )


def test_listeners(juju: JujuFixture, app_charm):
    address = get_address(juju=juju)
    assert netcat(
        address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].internal
    )  # Internal listener
    # Client listener should not be enable if there is no relations
    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # Add relation with dummy app
    gather(
        juju.ext.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active", timeout=2000
        )

    # check that client listener is active
    assert netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)

    # remove relation and check that client listener is not active
    juju.ext.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, status="active", timeout=600)

    assert not netcat(address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client)


def test_client_properties_makes_admin_connection(juju: JujuFixture):
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active", timeout=800
        )

    result = run_client_properties(juju=juju)
    assert result
    assert len(result.strip().split("\n")) == 3

    juju.ext.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:{REL_NAME}", f"{DUMMY_NAME}:{REL_NAME_ADMIN}"
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME], idle_period=30, status="active", timeout=600)


def test_logs_write_to_storage(juju: JujuFixture):
    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME], idle_period=30, status="active", timeout=800
        )

    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    action.wait()

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30, status="active"
    )

    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )


def test_external_listeners_bootstrap(juju: JujuFixture):
    check_external_access_non_tls(juju, f"{APP_NAME}/0")


def test_exporter_endpoints(juju: JujuFixture):
    unit_address = get_address(juju=juju)
    jmx_exporter_url = f"http://{unit_address}:9101/metrics"
    jmx_resp = requests.get(jmx_exporter_url)

    assert jmx_resp.ok


@pytest.mark.skip(reason="No feature yet, needs newer image")
def test_log_level_change(juju: JujuFixture):
    for unit in juju.ext.model.applications[APP_NAME].units:
        total_lines = count_lines_with(
            juju,
            unit.name,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines == 0

    juju.ext.model.applications[APP_NAME].set_config({"log_level": "DEBUG"})
    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=30)

    for unit in juju.ext.model.applications[APP_NAME].units:
        total_lines = count_lines_with(
            juju,
            unit.name,
            "/var/log/kafka/server.log",
            "DEBUG",
        )
        assert total_lines > 0

    # cleanup
    juju.ext.model.applications[APP_NAME].set_config({"log_level": "INFO"})
    juju.ext.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000, idle_period=30)
