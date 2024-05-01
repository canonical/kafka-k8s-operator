#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any, Dict, List, Optional, Set

import yaml
from charms.kafka.client import KafkaClient
from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kafka.admin import NewTopic
from kazoo.exceptions import AuthFailedError, NoNodeError
from pytest_operator.plugin import OpsTest

from literals import PATHS, SECURITY_PROTOCOL_PORTS
from managers.auth import Acl, AuthManager

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
KAFKA_SERIES = "jammy"
ZK_NAME = "zookeeper-k8s"
ZK_SERIES = "jammy"
TLS_SERIES = "jammy"
DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"
TEST_DEFAULT_MESSAGES = 15
STORAGE = "data"


def load_acls(model_full_name: str | None, zk_uris: str) -> Set[Acl]:
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={PATHS['CONF']}/zookeeper-jaas.cfg {PATHS['BIN']}/bin/kafka-acls.sh --authorizer-properties zookeeper.connect={zk_uris} --list"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return AuthManager._parse_acls(acls=result)


def load_super_users(model_full_name: str | None) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {PATHS['CONF']}/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    properties = result.splitlines()

    for prop in properties:
        if "super.users" in prop:
            return prop.split("=")[1].split(";")

    return []


def check_user(model_full_name: str | None, username: str) -> None:
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={PATHS['CONF']}/zookeeper-jaas.cfg {PATHS['BIN']}/bin/kafka-configs.sh --bootstrap-server localhost:19092 --describe --entity-type users --entity-name {username} --command-config {PATHS['CONF']}/client.properties"
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert f"SCRAM credential configs for user-principal '{username}' are SCRAM-SHA-512" in result


def get_user(model_full_name: str | None, username: str = "sync") -> str:
    """Get information related to a user stored on zookeeper."""
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {PATHS['CONF']}/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    for line in result:
        if f'required username="{username}"' in line:
            break

    return line


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


async def set_tls_private_key(ops_test: OpsTest, key: Optional[str] = None, num_unit=0):
    """Use the charm action to start a password rotation."""
    params = {"internal-key": key} if key else {}

    action = await ops_test.model.units.get(f"{APP_NAME}/{num_unit}").run_action(
        "set-tls-private-key", **params
    )
    return (await action.wait()).results


def extract_private_key(ops_test: OpsTest, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        ops_test,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("private-key")


def extract_ca(ops_test: OpsTest, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        ops_test,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("ca-cert") or user_secret.get("ca")


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def check_tls(ip: str, port: int) -> bool:
    try:
        result = check_output(
            f"echo | openssl s_client -connect {ip}:{port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        logger.info(f"{result=}")
        # FIXME: The server cannot be validated, we would need to try to connect using the CA
        # from self-signed certificates. This is indication enough that the server is sending a
        # self-signed key.
        return "CN=kafka" in result.replace(" ", "")
    except CalledProcessError as e:
        logger.error(f"command '{e.cmd}' return with error (code {e.returncode}): {e.output}")
        return False


def consume_and_check(ops_test: OpsTest, provider_unit_name: str, topic: str) -> None:
    """Consumes 15 messages created by `produce_and_check_logs` function.

    Args:
        ops_test: OpsTest
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to consume from
    """
    relation_data = get_provider_data(
        ops_test=ops_test,
        unit_name=provider_unit_name,
        owner=APP_NAME,
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
        security_protocol=security_protocol,
    )

    client.subscribe_to_topic(topic_name=topic)
    messages = [*client.messages()]

    assert len(messages) == TEST_DEFAULT_MESSAGES


def produce_and_check_logs(
    ops_test: OpsTest,
    kafka_unit_name: str,
    provider_unit_name: str,
    topic: str,
    create_topic: bool = True,
    replication_factor: int = 1,
    num_partitions: int = 5,
) -> None:
    """Produces 15 messages from HN to chosen Kafka topic.

    Args:
        ops_test: OpsTest
        kafka_unit_name: the kafka unit to checks logs on
        provider_unit_name: the app to grab credentials from
        topic: the desired topic to produce to
        create_topic: if the topic needs to be created
        replication_factor: replication factor of the created topic
        num_partitions: number of partitions for the topic
    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    relation_data = get_provider_data(
        ops_test=ops_test,
        unit_name=provider_unit_name,
        owner=APP_NAME,
    )
    logger.info(f"{relation_data=}")
    client = KafkaClient(
        servers=relation_data["endpoints"].split(","),
        username=relation_data["username"],
        password=relation_data["password"],
        security_protocol="SASL_PLAINTEXT",
    )

    if create_topic:
        topic_config = NewTopic(
            name=topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
        )
        client.create_topic(topic=topic_config)
    for i in range(TEST_DEFAULT_MESSAGES):
        message = f"Message #{i}"
        client.produce_message(topic_name=topic, message_content=message)

    check_logs(ops_test, kafka_unit_name, topic)


def check_logs(ops_test: OpsTest, kafka_unit_name: str, topic: str) -> None:
    """Produces messages from HN to chosen Kafka topic.

    Args:
        ops_test: OpsTest
        kafka_unit_name: the kafka unit to checks logs on
        topic: the desired topic to produce to

    Raises:
        KeyError: if missing relation data
        AssertionError: if logs aren't found for desired topic
    """
    logs = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {kafka_unit_name} 'find {PATHS['DATA']}/{STORAGE}'",
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


async def run_client_properties(ops_test: OpsTest) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = (
        await get_address(ops_test=ops_test)
        + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
    )

    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={PATHS['CONF']}/zookeeper-jaas.cfg {PATHS['BIN']}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --all --command-config {PATHS['CONF']}/client.properties --entity-type users"

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


async def set_mtls_client_acls(ops_test: OpsTest, bootstrap_server: str) -> str:
    """Adds ACLs for principal `User:client` and `TEST-TOPIC`."""
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={PATHS['CONF']}/zookeeper-jaas.cfg {PATHS['BIN']}/bin/kafka-acls.sh --bootstrap-server {bootstrap_server} --add --allow-principal=User:client --operation READ --operation WRITE --operation CREATE --topic TEST-TOPIC --command-config {PATHS['CONF']}/client.properties"

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


def count_lines_with(ops_test: OpsTest, unit: str, file: str, pattern: str) -> int:
    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {unit} 'grep \"{pattern}\" {file} | wc -l'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return int(result)


def get_secret_by_label(ops_test: OpsTest, label: str, owner: str) -> dict[str, str]:
    secrets_meta_raw = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju list-secrets --format json",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).strip()
    secrets_meta = json.loads(secrets_meta_raw)

    for secret_id in secrets_meta:
        if owner and not secrets_meta[secret_id]["owner"] == owner:
            continue
        if secrets_meta[secret_id]["label"] == label:
            break

    secrets_data_raw = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju show-secret --format json --reveal {secret_id}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    secret_data = json.loads(secrets_data_raw)
    return secret_data[secret_id]["content"]["Data"]


def show_unit(ops_test: OpsTest, unit_name: str) -> Any:
    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju show-unit {unit_name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return yaml.safe_load(result)


def get_client_usernames(ops_test: OpsTest, owner: str = APP_NAME) -> set[str]:
    app_secret = get_secret_by_label(ops_test, label=f"cluster.{owner}.app", owner=owner)

    usernames = set()
    for key in app_secret.keys():
        if "password" in key:
            usernames.add(key.split("-")[0])
        if "relation" in key:
            usernames.add(key)

    return usernames


# FIXME: will need updating after zookeeper_client is implemented in full
def get_kafka_zk_relation_data(
    ops_test: OpsTest, owner: str, unit_name: str, relation_name: str = "zookeeper"
) -> dict[str, str]:
    unit_data = show_unit(ops_test, unit_name)

    kafka_zk_relation_data = {}
    for info in unit_data[unit_name]["relation-info"]:
        if info["endpoint"] == relation_name:
            kafka_zk_relation_data["relation-id"] = info["relation-id"]

            # initially collects all non-secret keys
            kafka_zk_relation_data.update(dict(info["application-data"]))

    user_secret = get_secret_by_label(
        ops_test,
        label=f"{relation_name}.{kafka_zk_relation_data['relation-id']}.user.secret",
        owner=owner,
    )

    tls_secret = get_secret_by_label(
        ops_test,
        label=f"{relation_name}.{kafka_zk_relation_data['relation-id']}.tls.secret",
        owner=owner,
    )

    # overrides to secret keys if found
    return kafka_zk_relation_data | user_secret | tls_secret


def get_provider_data(
    ops_test: OpsTest,
    owner: str,
    unit_name: str,
    relation_name: str = "kafka-client",
    relation_interface: str = "kafka-client-admin",
) -> dict[str, str]:
    unit_data = show_unit(ops_test, unit_name)

    provider_relation_data = {}
    for info in unit_data[unit_name]["relation-info"]:
        if info["endpoint"] == relation_interface:
            provider_relation_data["relation-id"] = info["relation-id"]

            # initially collects all non-secret keys
            provider_relation_data.update(dict(info["application-data"]))

    user_secret = get_secret_by_label(
        ops_test,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.user.secret",
        owner=owner,
    )

    tls_secret = get_secret_by_label(
        ops_test,
        label=f"{relation_name}.{provider_relation_data['relation-id']}.tls.secret",
        owner=owner,
    )

    # overrides to secret keys if found
    return provider_relation_data | user_secret | tls_secret


def get_active_brokers(config: Dict) -> Set[str]:
    """Gets all brokers currently connected to ZooKeeper.

    Args:
        config: the relation data provided by ZooKeeper

    Returns:
        Set of active broker ids
    """
    chroot = config.get("chroot", "")
    hosts = config.get("endpoints", "").split(",")
    username = config.get("username", "")
    password = config.get("password", "")

    zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
    path = f"{chroot}/brokers/ids/"

    try:
        brokers = zk.leader_znodes(path=path)
        logger.info(f"{brokers=}")
    # auth might not be ready with ZK after relation yet
    except (NoNodeError, AuthFailedError, QuorumLeaderNotFoundError) as e:
        logger.warning(str(e))
        return set()

    return brokers


async def get_address(ops_test: OpsTest, app_name=APP_NAME, unit_num=0) -> str:
    """Get the address for a unit."""
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]
    return address


def delete_pod(ops_test: OpsTest, unit_name: str):
    check_output(
        f"kubectl delete pod {unit_name.replace('/', '-')} -n {ops_test.model.info.name}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


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
