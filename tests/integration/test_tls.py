#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import base64
import logging

import pytest
from charms.tls_certificates_interface.v1.tls_certificates import generate_private_key
from pytest_operator.plugin import OpsTest

from literals import SECURITY_PROTOCOL_PORTS, TLS_RELATION, TRUSTED_CERTIFICATE_RELATION

from .helpers import (
    APP_NAME,
    KAFKA_CONTAINER,
    KAFKA_SERIES,
    REL_NAME_ADMIN,
    TLS_SERIES,
    ZK_NAME,
    ZK_SERIES,
    check_application_status,
    check_tls,
    extract_ca,
    extract_private_key,
    get_address,
    set_mtls_client_acls,
    set_tls_private_key,
    show_unit,
)

logger = logging.getLogger(__name__)

TLS_NAME = "self-signed-certificates"
CERTS_NAME = "tls-certificates-operator"

MTLS_NAME = "mtls"
DUMMY_NAME = "app"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_deploy_tls(ops_test: OpsTest, app_charm):
    kafka_charm = await ops_test.build_charm(".")
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        ops_test.model.deploy(TLS_NAME, channel="edge", config=tls_config, series=TLS_SERIES),
        ops_test.model.deploy(ZK_NAME, channel="edge", num_units=3, series=ZK_SERIES),
        ops_test.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            resources={"kafka-image": KAFKA_CONTAINER},
            series=KAFKA_SERIES,
            config={
                "ssl_principal_mapping_rules": "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L,DEFAULT"
            },
        ),
        ops_test.model.deploy(app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy"),
    )
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[ZK_NAME].units) == 3)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME, TLS_NAME, DUMMY_NAME], timeout=2000
    )

    assert check_application_status(ops_test=ops_test, app_name=APP_NAME) == "waiting"
    assert ops_test.model.applications[ZK_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"

    # Relate Zookeeper to TLS
    await ops_test.model.add_relation(TLS_NAME, ZK_NAME)
    logger.info("Relate Zookeeper to TLS")

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME, ZK_NAME], idle_period=30, status="active", timeout=2000
        )


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # Relate Zookeeper[TLS] to Kafka[Non-TLS]
    await ops_test.model.add_relation(ZK_NAME, APP_NAME)
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(apps=[ZK_NAME], idle_period=30, timeout=2000)

    # Unit is on 'blocked' but whole app is on 'waiting'
    assert check_application_status(ops_test=ops_test, app_name=APP_NAME) == "waiting"

    # Set a custom private key, by running set-tls-private-key action with no parameters,
    # as this will generate a random one
    num_unit = 0
    await set_tls_private_key(ops_test)

    # Extract the key
    private_key = extract_private_key(
        show_unit(f"{APP_NAME}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    logger.info("Relate Kafka to TLS")
    await ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, ZK_NAME, TLS_NAME], idle_period=30, timeout=2000, status="active"
        )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    # Client port shouldn't be up before relating to client app.
    assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME], timeout=3600, idle_period=30, status="active"
        )

    logger.info("Check for Kafka TLS")
    assert check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL"].client)

    # Rotate credentials
    new_private_key = generate_private_key().decode("utf-8")

    await set_tls_private_key(ops_test, key=new_private_key)

    # Extract the key
    private_key_2 = extract_private_key(
        show_unit(f"{APP_NAME}/{num_unit}", model_full_name=ops_test.model_full_name), unit=0
    )

    assert private_key != private_key_2
    assert private_key_2 == new_private_key


# FIXME: Address on its own ticket
@pytest.mark.skip
@pytest.mark.abort_on_fail
async def test_mtls(ops_test: OpsTest):
    # creating the signed external cert on the unit
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("create-certificate")
    response = await action.wait()
    client_certificate = response.results["client-certificate"]
    client_ca = response.results["client-ca"]

    encoded_client_certificate = base64.b64encode(client_certificate.encode("utf-8")).decode(
        "utf-8"
    )
    encoded_client_ca = base64.b64encode(client_ca.encode("utf-8")).decode("utf-8")

    # deploying mtls operator with certs
    tls_config = {
        "generate-self-signed-certificates": "false",
        "certificate": encoded_client_certificate,
        "ca-certificate": encoded_client_ca,
    }
    await ops_test.model.deploy(
        CERTS_NAME, channel="stable", config=tls_config, series="jammy", application_name=MTLS_NAME
    )
    await ops_test.model.wait_for_idle(apps=[MTLS_NAME], timeout=1000, idle_period=15)
    async with ops_test.fast_forward():
        await ops_test.model.add_relation(
            f"{APP_NAME}:{TRUSTED_CERTIFICATE_RELATION}", f"{MTLS_NAME}:{TLS_RELATION}"
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, MTLS_NAME], idle_period=60, timeout=2000, status="active"
        )

    # getting kafka ca and address
    broker_ca = extract_ca(show_unit(f"{APP_NAME}/0", model_full_name=ops_test.model_full_name))
    address = await get_address(ops_test, app_name=APP_NAME)
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL"].client
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
    ssl_bootstrap_server = f"{address}:{ssl_port}"
    sasl_bootstrap_server = f"{address}:{sasl_port}"

    # setting ACLs using normal sasl port
    await set_mtls_client_acls(ops_test, bootstrap_server=sasl_bootstrap_server)

    num_messages = 10

    # running mtls producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{
            "bootstrap-server": ssl_bootstrap_server,
            "broker-ca": base64.b64encode(broker_ca.encode("utf-8")).decode("utf-8"),
            "num-messages": num_messages,
        },
    )

    response = await action.wait()

    assert response.results.get("success", None) == "TRUE"

    offsets_action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
        **{
            "bootstrap-server": ssl_bootstrap_server,
        },
    )

    response = await offsets_action.wait()

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "TEST-TOPIC"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


async def test_kafka_tls_scaling(ops_test: OpsTest):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[APP_NAME].scale(scale=3)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=2000
    )
    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        idle_period=40,
        timeout=2000,
    )

    # TODO: Add this back once the scaling tests are addressed
    """
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=f"{APP_NAME}/2", model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    assert f"{chroot}/brokers/ids/0" in active_brokers
    assert f"{chroot}/brokers/ids/1" in active_brokers
    assert f"{chroot}/brokers/ids/2" in active_brokers
    """

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    assert check_tls(ip=kafka_address, port=19093)
