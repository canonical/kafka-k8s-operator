#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import os
import tempfile

import kafka
import pytest
from charms.tls_certificates_interface.v4.tls_certificates import PrivateKey, generate_private_key
from pytest_operator.plugin import OpsTest

from integration.helpers import sign_manual_certs
from integration.helpers.pytest_operator import (
    APP_NAME,
    DUMMY_NAME,
    MANUAL_TLS_NAME,
    REL_NAME_PRODUCER,
    TLS_NAME,
    TLS_REQUIRER,
    check_socket,
    check_tls,
    create_test_topic,
    delete_pod,
    deploy_cluster,
    extract_private_key,
    get_actual_tls_private_key,
    get_address,
    list_truststore_aliases,
    remove_tls_private_key,
    search_secrets,
    set_tls_private_key,
    update_tls_private_key,
)
from literals import CERTIFICATE_TRANSFER_RELATION, SECURITY_PROTOCOL_PORTS, TLS_RELATION

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deploy_tls(ops_test: OpsTest, kafka_charm, kraft_mode, kafka_apps):
    tls_config = {"ca-common-name": "kafka"}

    await asyncio.gather(
        # FIXME (certs): Unpin the revision once the charm is fixed
        ops_test.model.deploy(
            TLS_NAME, channel="edge", config=tls_config, revision=163, trust=True
        ),
        deploy_cluster(
            ops_test=ops_test,
            charm=kafka_charm,
            kraft_mode=kraft_mode,
            # config_broker={"expose-external": "nodeport"},
        ),
    )
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, TLS_NAME],
        idle_period=30,
        timeout=2000,
        raise_on_error=False,
        status="active",
    )

    assert ops_test.model.applications[APP_NAME].status == "active"
    assert ops_test.model.applications[TLS_NAME].status == "active"


@pytest.mark.abort_on_fail
async def test_kafka_tls(ops_test: OpsTest, app_charm, kafka_apps):
    """Tests TLS on Kafka.

    Relates Zookeper[TLS] with Kafka[Non-TLS]. This leads to a blocked status.
    Afterwards, relate Kafka to TLS operator, which unblocks the application.
    """
    # ensuring at least a few update-status
    await ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", TLS_NAME)
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, TLS_NAME], idle_period=30, timeout=1200, status="active"
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)

    # Client port shouldn't be up before relating to client app.
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )

    await asyncio.gather(
        ops_test.model.deploy(
            app_charm, application_name=DUMMY_NAME, num_units=1, series="jammy", trust=True
        ),
    )
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], timeout=1000, idle_period=30, raise_on_error=False
    )

    # ensuring at least a few update-status
    await ops_test.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_PRODUCER}")
    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(60)

    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, DUMMY_NAME], idle_period=30, status="active"
    )

    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
async def test_set_tls_private_key(ops_test: OpsTest):
    # 1. First test the setting of new PKs on an existing cluster
    old_pks = set()
    secret: dict[str, PrivateKey] = {}
    for unit in ops_test.model.applications[APP_NAME].units:
        old_pks.add(extract_private_key(ops_test, unit.name))
        secret[unit.name.replace("/", "-")] = generate_private_key()

    await set_tls_private_key(ops_test, secret=secret)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME, TLS_NAME], idle_period=30, status="active"
        )

    new_pks = set()
    actual_pks = set()
    for unit in ops_test.model.applications[APP_NAME].units:
        new_pks.add(extract_private_key(ops_test, unit.name))
        actual_pks.add(get_actual_tls_private_key(ops_test, unit.name))

    assert new_pks.isdisjoint(old_pks)  # all pks changed in secret data
    assert new_pks == actual_pks  # all pks actually written to charm

    # 2. Now test the updating a new PK on a single unit
    removed_secret_unit_name, removed_secret_tls_pk = secret.popitem()  # getting random unit
    secret.update({removed_secret_unit_name: generate_private_key()})  # replacing cert

    await update_tls_private_key(ops_test, secret=secret)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME, TLS_NAME], idle_period=30, status="active"
        )

    updated_secret_pk = extract_private_key(
        ops_test, removed_secret_unit_name.replace(f"{APP_NAME}-", f"{APP_NAME}/")
    )
    updated_actual_pk = get_actual_tls_private_key(
        ops_test, removed_secret_unit_name.replace(f"{APP_NAME}-", f"{APP_NAME}/")
    )

    assert updated_secret_pk == updated_actual_pk
    assert updated_secret_pk != removed_secret_tls_pk

    # 3. Now test the removal of the PK secret config entirely
    await remove_tls_private_key(ops_test)

    async with ops_test.fast_forward(fast_interval="60s"):
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME, TLS_NAME], idle_period=30, status="active"
        )

    post_removed_pks = set()
    post_removed_actual_pks = set()
    for unit in ops_test.model.applications[APP_NAME].units:
        post_removed_pks.add(extract_private_key(ops_test, unit.name))
        post_removed_actual_pks.add(get_actual_tls_private_key(ops_test, unit.name))

    assert post_removed_pks == post_removed_actual_pks

    pre_pks = new_pks | actual_pks | {updated_secret_pk, updated_actual_pk}
    post_pks = post_removed_pks | post_removed_actual_pks

    assert post_pks.isdisjoint(pre_pks)  # checking every post-secret-removed pk is brand new


@pytest.mark.abort_on_fail
async def test_mtls(ops_test: OpsTest, kafka_apps):
    # creating the signed external cert on the unit
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action("create-certificate")
    response = await action.wait()

    async with ops_test.fast_forward(fast_interval="120s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, DUMMY_NAME], idle_period=30, status="active"
        )

    num_messages = 10
    # running mtls producer
    action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "run-mtls-producer",
        **{"num-messages": num_messages},
    )

    response = await action.wait()

    assert response.results.get("success", None) == "TRUE"

    offsets_action = await ops_test.model.units.get(f"{DUMMY_NAME}/0").run_action(
        "get-offsets",
    )

    response = await offsets_action.wait()

    topic_name, min_offset, max_offset = response.results["output"].strip().split(":")

    assert topic_name == "test-topic"
    assert min_offset == "0"
    assert max_offset == str(num_messages)


@pytest.mark.abort_on_fail
async def test_certificate_transfer(ops_test: OpsTest, kafka_apps):
    """Tests truststore live reload functionality using kafka-python client."""
    requirer = "other-req/0"
    test_msg = {"test": 123456}
    await ops_test.juju("config", APP_NAME, "expose-external=nodeport")

    await ops_test.model.deploy(
        TLS_NAME,
        channel="1/stable",
        application_name="other-ca",
    )
    await ops_test.model.deploy(
        TLS_REQUIRER, channel="stable", application_name="other-req", revision=102
    )

    await ops_test.model.add_relation("other-ca", "other-req")

    await ops_test.model.wait_for_idle(
        apps=["other-ca", "other-req"], idle_period=60, timeout=2000, status="active"
    )

    # retrieve required certificates and private key from secrets
    local_store = {
        "private_key": search_secrets(ops_test=ops_test, owner=requirer, search_key="private-key"),
        "cert": search_secrets(ops_test=ops_test, owner=requirer, search_key="certificate"),
        "ca_cert": search_secrets(ops_test=ops_test, owner=requirer, search_key="ca-certificate"),
        "broker_ca": search_secrets(
            ops_test=ops_test, owner=f"{APP_NAME}/0", search_key="client-ca-cert"
        ),
    }

    # Transfer other-ca's CA certificate via the client-cas relation
    # We don't expect a broker restart here because of truststore live reload
    await ops_test.model.add_relation(
        f"{APP_NAME}:{CERTIFICATE_TRANSFER_RELATION}", "other-ca:send-ca-cert"
    )

    address = await get_address(ops_test, app_name=APP_NAME, unit_num=0)
    sasl_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    sasl_bootstrap_server = f"{address}:{sasl_port}"
    ssl_port = SECURITY_PROTOCOL_PORTS["SSL", "SSL"].external
    ssl_bootstrap_server = f"{address}:{ssl_port}"

    # create `test` topic and set ACLs
    await create_test_topic(ops_test, bootstrap_server=sasl_bootstrap_server)

    # Wait for eventual broker restart, which opens client ports.
    async with ops_test.fast_forward(fast_interval="60s"):
        while not check_socket(address, ssl_port):
            await asyncio.sleep(30)

    # quickly test the producer and consumer side authentication & authorization
    tmp_dir = tempfile.TemporaryDirectory()
    tmp_paths = {}
    for key, content in local_store.items():
        tmp_paths[key] = os.path.join(tmp_dir.name, key)
        with open(tmp_paths[key], "w", encoding="utf-8") as f:
            f.write(content)

    client_config = {
        "bootstrap_servers": ssl_bootstrap_server,
        "security_protocol": "SSL",
        "api_version": (2, 6),
        "ssl_cafile": tmp_paths["broker_ca"],
        "ssl_certfile": tmp_paths["cert"],
        "ssl_keyfile": tmp_paths["private_key"],
        "ssl_check_hostname": False,
    }

    producer = kafka.KafkaProducer(
        **client_config,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    producer.send("test", test_msg)

    consumer = kafka.KafkaConsumer("test", **client_config, auto_offset_reset="earliest")

    msg = next(consumer)

    assert json.loads(msg.value) == test_msg

    # cleanup
    await ops_test.model.remove_application("other-ca", block_until_done=True)
    await ops_test.model.remove_application("other-req", block_until_done=True)
    tmp_dir.cleanup()


@pytest.mark.abort_on_fail
async def test_kafka_tls_scaling(ops_test: OpsTest, kafka_apps):
    """Scale the application while using TLS to check that new units will configure correctly."""
    await ops_test.model.applications[APP_NAME].scale(scale=3)
    logger.info("Scaling Kafka to 3 units")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[APP_NAME].units) == 3, timeout=2000
    )

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", idle_period=40, timeout=2000
    )

    async with ops_test.fast_forward(fast_interval="20s"):
        await asyncio.sleep(90)

    # TODO

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=2)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
async def test_mtls_broken(ops_test: OpsTest, kafka_apps):
    # remove relation and check connection again
    remove_relation_cmd = f"remove-relation {APP_NAME} {DUMMY_NAME}"
    await ops_test.juju(*remove_relation_cmd.split(), check=True)
    await ops_test.model.wait_for_idle(
        apps=kafka_apps, status="active", idle_period=40, timeout=2000
    )

    for unit_num in range(len(ops_test.model.applications[APP_NAME].units)):
        kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=unit_num)
        assert not check_tls(
            ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
        )
        assert not check_tls(ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SSL", "SSL"].client)


@pytest.mark.abort_on_fail
async def test_tls_removed(ops_test: OpsTest, kafka_apps):
    await ops_test.model.applications[APP_NAME].remove_relation(
        f"{APP_NAME}:certificates", f"{TLS_NAME}:certificates"
    )

    # ensuring enough update-status
    async with ops_test.fast_forward(fast_interval="60s"):
        await asyncio.sleep(180)

    await ops_test.model.wait_for_idle(
        apps=kafka_apps,
        timeout=3600,
        idle_period=30,
        status="active",
        raise_on_error=False,
    )

    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert not check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].client
    )


@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_pod_reschedule_tls(ops_test: OpsTest, kafka_apps):
    delete_pod(ops_test, f"{APP_NAME}-0")

    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(90)

    await ops_test.model.wait_for_idle(
        apps=kafka_apps,
        status="active",
        idle_period=90,
        timeout=2000,
    )


@pytest.mark.abort_on_fail
async def test_manual_tls_chain(ops_test: OpsTest, kafka_apps):
    await ops_test.model.deploy(MANUAL_TLS_NAME)

    await ops_test.model.add_relation(f"{APP_NAME}:{TLS_RELATION}", MANUAL_TLS_NAME)

    # ensuring enough time for multiple rolling-restart with update-status
    async with ops_test.fast_forward(fast_interval="30s"):
        await asyncio.sleep(180)

    async with ops_test.fast_forward(fast_interval="120s"):
        await ops_test.model.wait_for_idle(
            apps=[*kafka_apps, MANUAL_TLS_NAME], idle_period=30, timeout=1000
        )

    sign_manual_certs(ops_test.model_full_name)

    # verifying brokers + servers can communicate with one-another
    await ops_test.model.wait_for_idle(
        apps=[*kafka_apps, MANUAL_TLS_NAME], idle_period=30, timeout=1000
    )

    # verifying the chain is in there
    trusted_aliases = await list_truststore_aliases(ops_test)

    assert len(trusted_aliases) == 3  # cert, intermediate, rootca

    # verifying TLS is enabled and working
    kafka_address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    assert check_tls(
        ip=kafka_address, port=SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
    )
