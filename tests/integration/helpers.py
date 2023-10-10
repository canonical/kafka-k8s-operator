#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import re
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from pytest_operator.plugin import OpsTest

from auth import Acl, KafkaAuth
from literals import (
    BINARIES_PATH,
    CONF_PATH,
    DATA_PATH,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    STORAGE,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
KAFKA_SERIES = "jammy"
ZK_NAME = "zookeeper-k8s"
ZK_SERIES = "jammy"
DATA_INTEGRATOR_NAME = "data-integrator"
TLS_SERIES = "jammy"
DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"
TEST_DEFAULT_MESSAGES = 15


def load_acls(model_full_name: str, zookeeper_uri: str) -> Set[Acl]:
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={CONF_PATH}/kafka-jaas.cfg {BINARIES_PATH}/bin/kafka-acls.sh --authorizer-properties zookeeper.connect={zookeeper_uri} --list"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return KafkaAuth._parse_acls(acls=result)


def load_super_users(model_full_name: str) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {CONF_PATH}/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    properties = result.splitlines()

    for prop in properties:
        if "super.users" in prop:
            return prop.split("=")[1].split(";")

    return []


def check_user(model_full_name: str, username: str, zookeeper_uri: str) -> None:
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={CONF_PATH}/kafka-jaas.cfg {BINARIES_PATH}/bin/kafka-configs.sh --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert "SCRAM-SHA-512" in result


def get_user(model_full_name: str, username: str, zookeeper_uri: str) -> str:
    """Get information related to a user stored on zookeeper."""
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={CONF_PATH}/kafka-jaas.cfg {BINARIES_PATH}/bin/kafka-configs.sh --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return result


def show_unit(unit_name: str, model_full_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)


def get_zookeeper_connection(unit_name: str, model_full_name: str) -> Tuple[List[str], str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)

    relations_info = result[unit_name]["relation-info"]

    usernames = []
    zookeeper_uri = ""
    for info in relations_info:
        if info["endpoint"] == "cluster":
            for key in info["application-data"].keys():
                if re.match(r"(relation\-[\d]+)", key):
                    usernames.append(key)
        if info["endpoint"] == "zookeeper":
            zookeeper_uri = info["application-data"]["uris"]

    if zookeeper_uri and usernames:
        return usernames, zookeeper_uri
    else:
        raise Exception("config not found")


async def get_address(ops_test: OpsTest, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]
    return address


def get_unit_address_map(ops_test: OpsTest, app_name: str = APP_NAME) -> dict[str, str]:
    """Returns map on unit name and host.

    Args:
        ops_test: OpsTest
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`

    Returns:
        Dict of key unit name, value unit address
    """
    ips = subprocess.check_output(
        f"JUJU_MODEL={ops_test.model.info.name} juju status {app_name} --format json | jq '.applications | .\"{app_name}\" | .units | .. .address? // empty' | xargs | tr -d '\"'",
        shell=True,
        universal_newlines=True,
    ).split()
    hosts = subprocess.check_output(
        f'JUJU_MODEL={ops_test.model.info.name} juju status {app_name} --format json | jq \'.applications | ."{app_name}" | .units | keys | join(" ")\' | tr -d \'"\'',
        shell=True,
        universal_newlines=True,
    ).split()

    return dict(zip(hosts, ips))


def get_bootstrap_servers(ops_test: OpsTest, app_name: str = APP_NAME, port: int = 9092) -> str:
    """Gets all Kafka server addresses for a given application.

    Args:
        ops_test: OpsTest
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`
        port: the desired Kafka port.
            Defaults to `9092`

    Returns:
        List of Kafka server addresses and ports
    """
    return ",".join(f"{host}:{port}" for host in get_unit_address_map(ops_test, app_name).values())


def get_k8s_host_from_unit(unit_name: str, app_name: str = APP_NAME) -> str:
    """Builds K8s host address for a given unit.

    Args:
        unit_name: name of the Juju unit
        app_name: the Juju application the Kafka server belongs to
            Defaults to `kafka-k8s`

    Returns:
        String of k8s host address
    """
    broker_id = unit_name.split("/")[1]

    return f"{app_name}-{broker_id}.{app_name}-endpoints"


async def set_password(ops_test: OpsTest, username="sync", password=None, num_unit=0) -> str:
    """Use the charm action to start a password rotation."""
    params = {"username": username}
    if password:
        params["password"] = password

    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "set-password", **params
    )
    password = await action.wait()
    logger.info(f"password: {password}")
    return password.results


async def set_tls_private_key(ops_test: OpsTest, key: Optional[str] = None, num_unit=0):
    """Use the charm action to start a password rotation."""
    params = {"internal-key": key} if key else {}

    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "set-tls-private-key", **params
    )
    return (await action.wait()).results


def extract_private_key(data: dict, unit: int = 0) -> Optional[str]:
    list_keys = [
        element["local-unit"]["data"]["private-key"]
        for element in data[f"{APP_NAME}/{unit}"]["relation-info"]
        if element["endpoint"] == "cluster"
    ]
    return list_keys[0] if len(list_keys) else None


def check_application_status(ops_test: OpsTest, app_name: str) -> str:
    """Return the application status for an app name."""
    # FIXME: This is needed because: https://github.com/juju/python-libjuju/issues/740
    model_name = ops_test.model.info.name
    proc = check_output(f"juju status --model={model_name}".split())
    proc = proc.decode("utf-8")

    statuses = {"active", "maintenance", "waiting", "blocked"}
    for line in proc.splitlines():
        parts = line.split()
        # first line with app name will have application status
        if parts and parts[0] == app_name:
            # NOTE: intersects possible statuses with the list of values:
            # this is done because sometimes version number exists and
            # sometimes it doesn't on juju status output
            find_status = list(statuses & set(parts))
            if find_status:
                return find_status[0]


def get_kafka_zk_relation_data(unit_name: str, model_full_name: str) -> Dict[str, str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)
    relations_info = result[unit_name]["relation-info"]

    zk_relation_data = {}
    for info in relations_info:
        if info["endpoint"] == "zookeeper":
            zk_relation_data["chroot"] = info["application-data"]["chroot"]
            zk_relation_data["endpoints"] = info["application-data"]["endpoints"]
            zk_relation_data["password"] = info["application-data"]["password"]
            zk_relation_data["uris"] = info["application-data"]["uris"]
            zk_relation_data["username"] = info["application-data"]["username"]
            zk_relation_data["tls"] = info["application-data"]["tls"]
    return zk_relation_data


def check_tls(ip: str, port: int) -> bool:
    try:
        result = check_output(
            f"echo | openssl s_client -connect {ip}:{port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        # FIXME: The server cannot be validated, we would need to try to connect using the CA
        # from self-signed certificates. This is indication enough that the server is sending a
        # self-signed key.
        return "CN = kafka" in result
    except CalledProcessError as e:
        logger.error(f"command '{e.cmd}' return with error (code {e.returncode}): {e.output}")
        return False


def get_provider_data(
    unit_name: str, model_full_name: str, endpoint: str = REL_NAME
) -> Dict[str, str]:
    result = show_unit(unit_name=unit_name, model_full_name=model_full_name)
    relations_info = result[unit_name]["relation-info"]

    provider_relation_data = {}
    for info in relations_info:
        if info["endpoint"] == endpoint:
            provider_relation_data["username"] = info["application-data"]["username"]
            provider_relation_data["password"] = info["application-data"]["password"]
            provider_relation_data["endpoints"] = info["application-data"]["endpoints"]
            provider_relation_data["zookeeper-uris"] = info["application-data"]["zookeeper-uris"]
            provider_relation_data["tls"] = info["application-data"]["tls"]
            if "consumer-group-prefix" in info["application-data"]:
                provider_relation_data["consumer-group-prefix"] = info["application-data"][
                    "consumer-group-prefix"
                ]
            provider_relation_data["topic"] = info["application-data"]["topic"]
    return provider_relation_data


def check_logs(model_full_name: str, kafka_unit_name: str, topic: str) -> None:
    """Produces messages from HN to chosen Kafka topic.

    Args:
        model_full_name: the full name of the model
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to produce to

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    logs = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {kafka_unit_name} 'find {DATA_PATH}/{STORAGE}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    passed = False
    for log in logs:
        if topic and "index" in log:
            passed = True
            break

    assert logs and passed, "logs not found"


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


async def run_client_properties(ops_test: OpsTest) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = (
        await get_address(ops_test=ops_test)
        + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
    )

    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={CONF_PATH}/kafka-jaas.cfg {BINARIES_PATH}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --all --command-config {CONF_PATH}/client.properties --entity-type users"

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result
