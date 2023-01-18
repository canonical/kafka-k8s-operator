#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import re
from pathlib import Path
from subprocess import PIPE, check_output
from typing import Any, Dict, List, Set, Tuple

import yaml
from pytest_operator.plugin import OpsTest

from auth import Acl, KafkaAuth
from tests.integration.client import KafkaClient

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
ZK_NAME = "zookeeper-k8s"


def load_acls(model_full_name: str, zookeeper_uri: str) -> Set[Acl]:
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config=/data/kafka/config/kafka-jaas.cfg ./opt/kafka/bin/kafka-acls.sh --authorizer-properties zookeeper.connect={zookeeper_uri} --list"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return KafkaAuth._parse_acls(acls=result)


def load_super_users(model_full_name: str) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat /data/kafka/config/server.properties'",
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
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config=/data/kafka/config/kafka-jaas.cfg ./opt/kafka/bin/kafka-configs.sh --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert "SCRAM-SHA-512" in result


def get_user(model_full_name: str, username: str, zookeeper_uri: str) -> str:
    """Get information related to a user stored on zookeeper."""
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config=/data/kafka/config/kafka-jaas.cfg ./opt/kafka/bin/kafka-configs.sh --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}"
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


async def set_password(ops_test: OpsTest, username="sync", password=None, num_unit=0) -> str:
    """Use the charm action to start a password rotation."""
    params = {"username": username}
    if password:
        params["password"] = password

    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "set-password", **params
    )
    password = await action.wait()
    return password.results


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


def check_tls(ip: str, port: int) -> None:
    result = check_output(
        f"echo | openssl s_client -connect {ip}:{port}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    # FIXME: The server cannot be validated, we would need to try to connect using the CA
    # from self-signed certificates. This is indication enough that the server is sending a
    # self-signed key.
    assert "CN = kafka" in result


def get_provider_data(
    unit_name: str, model_full_name: str, endpoint: str = "kafka-client"
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
    return provider_relation_data


# def check_logs(model_full_name: str, kafka_unit_name: str, topic: str) -> None:
#     """Produces messages from HN to chosen Kafka topic.

#     Args:
#         model_full_name: the full name of the model
#         kafka_unit_name: the kafka unit to checks logs on
#         topic: the desired topic to produce to

#     Raises:
#         KeyError: if missing relation data
#         AssertionError: if logs aren't found for desired topic
#     """
#     logs = check_output(
#         f"JUJU_MODEL={model_full_name} juju ssh --container kafka {kafka_unit_name} 'find /var/lib/juju/storage/log-data'",
#         stderr=PIPE,
#         shell=True,
#         universal_newlines=True,
#     ).splitlines()

#     logger.debug(f"{logs=}")

#     passed = False
#     for log in logs:
#         if topic and "index" in log:
#             passed = True
#             break

#     assert passed, "logs not found"


def produce_and_check_logs(
    model_full_name: str, kafka_unit_name: str, provider_unit_name: str, topic: str
) -> None:
    """Produces messages to chosen Kafka topic.
    Args:
        model_full_name: the full name of the model
        kafka_unit_name: the kafka unit to checks logs on
        proider_unit_name: the app to grab credentials from
        topic: the desired topic to produce to
    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    relation_data = get_provider_data(
        unit_name=provider_unit_name,
        model_full_name=model_full_name,
        endpoint="kafka-client-admin"
    )
    topic = topic
    username = relation_data.get("username", None)
    password = relation_data.get("password", None)
    servers = relation_data.get("endpoints", "").split(",")
    security_protocol = "SASL_PLAINTEXT"

    if not (username and password and servers):
        raise KeyError("missing relation data from app charm")

    client = KafkaClient(
        servers=servers,
        username=username,
        password=password,
        topic=topic,
        consumer_group_prefix=None,
        security_protocol=security_protocol,
    )

    client.create_topic()
    client.run_producer()

    logs = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {kafka_unit_name} 'find /var/snap/kafka/common/log-data'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    logger.debug(f"{logs=}")

    passed = False
    for log in logs:
        if topic and "index" in log:
            passed = True
            break

    assert passed, "logs not found"
