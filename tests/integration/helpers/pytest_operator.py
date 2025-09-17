#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import re
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from subprocess import PIPE, CalledProcessError, check_output
from typing import Any, List, Literal, Optional, Set

import yaml
from charms.kafka.client import KafkaClient
from charms.zookeeper.v0.client import QuorumLeaderNotFoundError, ZooKeeperManager
from kafka.admin import NewTopic
from kazoo.exceptions import AuthFailedError, NoNodeError
from pytest_operator.plugin import OpsTest
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

from core.models import JSON
from literals import (
    BALANCER_WEBSERVER_USER,
    BROKER,
    CONTROLLER_USER,
    INTERNAL_USERS,
    JMX_CC_PORT,
    KRAFT_NODE_ID_OFFSET,
    PEER,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
    KRaftUnitStatus,
)
from managers.auth import Acl, AuthManager

from . import get_k8s_host_from_unit

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
CONTROLLER_NAME = "controller"
ZK_NAME = "zookeeper-k8s"
DUMMY_NAME = "app"
REL_NAME_ADMIN = "kafka-client-admin"
REL_NAME_PRODUCER = "kafka-client-producer"
AUTH_SECRET_CONFIG_KEY = "system-users"
TEST_DEFAULT_MESSAGES = 15
TEST_SECRET_NAME = "auth"
STORAGE = "data"
TLS_NAME = "self-signed-certificates"
MANUAL_TLS_NAME = "manual-tls-certificates"
CERTS_NAME = "tls-certificates-operator"
TLS_REQUIRER = "tls-certificates-requirer"
NON_REL_USERS = set(INTERNAL_USERS + [CONTROLLER_USER])
MTLS_NAME = "mtls"
DUMMY_NAME = "app"


KRaftMode = Literal["single", "multi"]


async def deploy_cluster(
    ops_test: OpsTest,
    charm: Path,
    kraft_mode: KRaftMode,
    series: str = "noble",
    config_broker: dict = {},
    config_controller: dict = {},
    num_broker: int = 1,
    num_controller: int = 1,
    storage_broker: dict = {},
    app_name_broker: str = str(APP_NAME),
    app_name_controller: str = CONTROLLER_NAME,
):
    """Deploys an Apache Kafka cluster using the Charmed Apache Kafka operator in KRaft mode."""
    logger.info(f"Deploying Kafka cluster in '{kraft_mode}' mode")

    _config = {"auto-balance": False} if num_broker < 3 else {}

    await ops_test.model.deploy(
        charm,
        application_name=app_name_broker,
        num_units=num_broker,
        series=series,
        storage=storage_broker,
        config={
            "roles": "broker,controller" if kraft_mode == "single" else "broker",
            "profile": "testing",
        }
        | _config
        | config_broker,
        resources={"kafka-image": KAFKA_CONTAINER},
        trust=True,
    )

    if kraft_mode == "multi":
        await ops_test.model.deploy(
            charm,
            application_name=app_name_controller,
            num_units=num_controller,
            series=series,
            config={
                "roles": "controller",
                "profile": "testing",
            }
            | _config
            | config_controller,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
        )

    status = "active" if kraft_mode == "single" else "blocked"
    apps = [app_name_broker] if kraft_mode == "single" else [app_name_broker, app_name_controller]
    await ops_test.model.wait_for_idle(
        apps=apps,
        idle_period=30,
        timeout=1800,
        raise_on_error=False,
        status=status,
    )

    if kraft_mode == "multi":
        await ops_test.model.add_relation(
            f"{app_name_broker}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
            f"{app_name_controller}:{PEER_CLUSTER_RELATION}",
        )

    await ops_test.model.wait_for_idle(
        apps=apps,
        idle_period=30,
        timeout=1800,
        raise_on_error=False,
        status="active",
    )


def load_acls(model_full_name: str | None) -> Set[Acl]:
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-acls.sh --command-config {BROKER.paths['CONF']}/client.properties --bootstrap-server {bootstrap_server} --list"

    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return AuthManager._parse_acls(acls=result)


def load_super_users(model_full_name: str | None) -> List[str]:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {BROKER.paths['CONF']}/server.properties'",
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
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --entity-type users --entity-name {username} --command-config {BROKER.paths['CONF']}/client.properties"
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
        f"JUJU_MODEL={model_full_name} juju ssh --container kafka {APP_NAME}/0 'cat {BROKER.paths['CONF']}/server.properties'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    for line in result:
        if f'required username="{username}"' in line:
            break

    return line


async def set_password(
    ops_test: OpsTest, username: str = "sync", password: str = "testpass"
) -> None:
    """Use the charm `system-users` config option to start a password rotation."""
    custom_auth = {username: password}
    secret_id = await ops_test.model.add_secret(
        name=TEST_SECRET_NAME, data_args=[f"{u}={p}" for u, p in custom_auth.items()]
    )
    # grant access to our app
    await ops_test.model.grant_secret(secret_name=TEST_SECRET_NAME, application=APP_NAME)
    # configure the app to use the secret_id
    await ops_test.model.applications[APP_NAME].set_config({AUTH_SECRET_CONFIG_KEY: secret_id})


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

    return user_secret.get("client-private-key")


def extract_ca(ops_test: OpsTest, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        ops_test,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("ca-cert") or user_secret.get("ca")


def extract_truststore_password(ops_test: OpsTest, unit_name: str) -> str | None:
    user_secret = get_secret_by_label(
        ops_test,
        label=f"cluster.{unit_name.split('/')[0]}.unit",
        owner=unit_name,
    )

    return user_secret.get("truststore-password")


def netcat(host: str, port: int) -> bool:
    try:
        check_output(
            f"nc -zv {host} {port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        return True
    except CalledProcessError as e:
        logger.error(e)
        return False


def check_tls(ip: str, port: int) -> bool:
    try:
        result = check_output(
            f"echo | openssl s_client -connect {ip}:{port}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        return bool(result)
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
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {kafka_unit_name} 'find {BROKER.paths['DATA']}/{STORAGE}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).splitlines()

    passed = False
    for log in logs:
        if topic in log and "index" in log:
            passed = True
            break

    assert logs and passed, "logs not found"


async def run_client_properties(ops_test: OpsTest) -> str:
    """Runs command requiring admin permissions, authenticated with bootstrap-server."""
    bootstrap_server = f'{get_k8s_host_from_unit("kafka-k8s/0")}:19093'
    container_command = f"{BROKER.paths['BIN']}/bin/kafka-configs.sh --bootstrap-server {bootstrap_server} --describe --all --command-config {BROKER.paths['CONF']}/client.properties --entity-type users"

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


async def set_mtls_client_acls(ops_test: OpsTest, bootstrap_server: str) -> str:
    """Adds ACLs for principal `User:client` and `TEST-TOPIC`."""
    container_command = f"KAFKA_OPTS=-Djava.security.auth.login.config={BROKER.paths['CONF']}/zookeeper-jaas.cfg {BROKER.paths['BIN']}/bin/kafka-acls.sh --bootstrap-server {bootstrap_server} --add --allow-principal=User:client --operation READ --operation WRITE --operation CREATE --topic TEST-TOPIC --command-config {BROKER.paths['CONF']}/client.properties"

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{container_command}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return result


async def create_test_topic(ops_test: OpsTest, bootstrap_server: str) -> str:
    """Creates `test` topic and adds ACLs for principal `User:*`."""
    _ = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{BROKER.paths['BIN']}/bin/kafka-topics.sh --bootstrap-server {bootstrap_server} --command-config {BROKER.paths['CONF']}/client.properties -create -topic test'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    result = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka kafka-k8s/0 '{BROKER.paths['BIN']}/bin/kafka-acls.sh --bootstrap-server {bootstrap_server} --add --allow-principal=User:* --operation READ --operation WRITE --operation CREATE --topic test --command-config {BROKER.paths['CONF']}/client.properties'",
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


def search_secrets(ops_test: OpsTest, owner: str, search_key: str) -> str:
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

        secrets_data_raw = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju show-secret --format json --reveal {secret_id}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        secret_data = json.loads(secrets_data_raw)
        if search_key in secret_data[secret_id]["content"]["Data"]:
            return secret_data[secret_id]["content"]["Data"][search_key]

    return ""


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

    return usernames - NON_REL_USERS


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


def get_active_brokers(config: dict[str, str]) -> set[str]:
    """Gets all brokers currently connected to ZooKeeper.

    Args:
        config: the relation data provided by ZooKeeper

    Returns:
        Set of active broker ids
    """
    chroot = config.get("database", config.get("chroot", ""))
    username = config.get("username", "")
    password = config.get("password", "")
    hosts = [host.split(":")[0] for host in config.get("endpoints", "").split(",")]

    zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
    path = f"{chroot}/brokers/ids/"

    try:
        brokers = zk.leader_znodes(path=path)
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


def balancer_is_running(model_full_name: str | None, app_name: str) -> bool:
    check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return True


def balancer_is_secure(ops_test: OpsTest, app_name: str) -> bool:
    model_full_name = ops_test.model_full_name
    err_401 = "Error 401 Unauthorized"
    unauthorized_ok = err_401 in check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    pwd = get_secret_by_label(ops_test=ops_test, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]
    authorized_ok = err_401 not in check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state'"
        f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return all((unauthorized_ok, authorized_ok))


def get_node_port(ops_test: OpsTest, app_name: str, service_name: str):
    namespace = ops_test.model.info.name
    bootstrap_service = check_output(
        f"kubectl describe svc -n {namespace} {app_name}-bootstrap",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    bootstrap_node_port = 0
    for line in bootstrap_service.splitlines():
        logger.error(f"{line}")
        if "NodePort" in line and service_name in line:
            bootstrap_node_port = int(line.split()[-1].split("/")[0])

    return bootstrap_node_port


@retry(
    wait=wait_fixed(20),  # long enough to not overwhelm the API
    stop=stop_after_attempt(180),  # give it 60 minutes to load
    retry=retry_if_result(lambda result: result is False),
    retry_error_callback=lambda _: False,
)
def balancer_is_ready(ops_test: OpsTest, app_name: str) -> bool:
    pwd = get_secret_by_label(ops_test=ops_test, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]

    try:
        monitor_state = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/state?json=True'"
            f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
        monitor_state_json = json.loads(monitor_state).get("MonitorState", {})
        executor_state_json = json.loads(monitor_state).get("ExecutorState", {})
    except (json.JSONDecodeError, CalledProcessError) as e:
        logger.error(e)
        return False

    print(f"{monitor_state_json=}")
    print(f"{executor_state_json=}")

    return all(
        [
            monitor_state_json.get("numMonitoredWindows", 0),
            monitor_state_json.get("numValidPartitions", 0),
            executor_state_json.get("state", "") == "NO_TASK_IN_PROGRESS",
        ]
    )


@retry(
    wait=wait_fixed(20),  # long enough to not overwhelm the API
    stop=stop_after_attempt(6),
    reraise=True,
)
def get_kafka_broker_state(ops_test: OpsTest, app_name: str) -> JSON:
    pwd = get_secret_by_label(ops_test=ops_test, label=f"{PEER}.{app_name}.app", owner=app_name)[
        "balancer-password"
    ]
    broker_state = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:9090/kafkacruisecontrol/kafka_cluster_state?json=True'"
        f" -u {BALANCER_WEBSERVER_USER}:{pwd}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    try:
        broker_state_json = json.loads(broker_state).get("KafkaBrokerState", {})
    except json.JSONDecodeError as e:
        logger.error(e)
        return False

    print(f"{broker_state_json=}")

    return broker_state_json


def check_external_access_non_tls(ops_test: OpsTest, unit_name: str):
    try:
        node_ip = check_output(
            "kubectl get nodes -o wide | awk -v OFS='\t\t' '{print $6}' | sed 1D",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        ).strip()

        # grabbing the helpful client.properties for later
        client_properties = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {unit_name} 'cat /etc/kafka/client.properties'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        ).splitlines()

        bootstrap_node_port = get_node_port(
            ops_test, unit_name.split("/")[0], "sasl-plaintext-scram-bootstrap-port"
        )

    except CalledProcessError as e:
        logger.error(vars(e))
        raise e

    admin_password = ""
    for line in client_properties:
        if match := re.search(r"password\=\"(.*)\"", line):
            admin_password = match.group(1)
            break

    admin_username = "admin"
    bootstrap_server = f"{node_ip}:{bootstrap_node_port}"

    client = KafkaClient(
        servers=[bootstrap_server],
        username=admin_username,
        password=admin_password,
        security_protocol="SASL_PLAINTEXT",
    )

    topic_config = NewTopic(
        name="HOT-TOPIC",
        num_partitions=100,
        replication_factor=1,
    )
    client.create_topic(topic=topic_config)

    internal_bootstrap_server = f"{get_k8s_host_from_unit(unit_name=unit_name)}:19093"
    topics_list = check_output(
        f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {unit_name} '/opt/kafka/bin/kafka-topics.sh --bootstrap-server {internal_bootstrap_server} --command-config /etc/kafka/client.properties --list'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert "HOT-TOPIC" in topics_list


def get_replica_count_by_broker_id(ops_test: OpsTest, app_name: str) -> dict[str, Any]:
    broker_state_json = get_kafka_broker_state(ops_test, app_name)
    return broker_state_json.get("ReplicaCountByBrokerId", {})


def balancer_exporter_is_up(model_full_name: str | None, app_name: str) -> bool:
    check_output(
        f"JUJU_MODEL={model_full_name} juju ssh {app_name}/leader sudo -i 'curl http://localhost:{JMX_CC_PORT}/metrics'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    return True


def get_mtls_nodeport(ops_test: OpsTest):
    ports = check_output(
        f"kubectl get svc -n {ops_test.model.info.name} -o wide | grep bootstrap | awk '{{print $5}}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    ).split(",")

    logger.info(f"{ports=}")

    for port in ports:
        if port.startswith(str(SECURITY_PROTOCOL_PORTS["SSL", "SSL"].external)):
            return port.split(":")[1].split("/")[0]

    raise Exception("could not find mtls nodeport in bootstrap service")


@retry(
    wait=wait_fixed(20),
    stop=stop_after_attempt(6),
    reraise=True,
)
def kraft_quorum_status(
    ops_test: OpsTest, unit_name: str, bootstrap_controller: str, verbose: bool = True
) -> dict[int, KRaftUnitStatus]:
    """Returns a dict mapping of unit ID to KRaft unit status based on `kafka-metadata-quorum.sh` utility's output."""
    try:
        result = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {unit_name} '{BROKER.paths['BIN']}/bin/kafka-metadata-quorum.sh --command-config {BROKER.paths['CONF']}/kraft-client.properties --bootstrap-controller {bootstrap_controller} describe --replication'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError as e:
        logger.error(vars(e))
        raise

    # parse `kafka-metadata-quorum.sh` output
    # NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp
    unit_status: dict[int, str] = {}
    for line in result.split("\n"):
        fields = [c.strip() for c in line.split("\t")]
        try:
            unit_status[int(fields[0])] = KRaftUnitStatus(fields[6])
        except (ValueError, IndexError):
            continue

    if verbose:
        print(unit_status)

    return unit_status


async def list_truststore_aliases(ops_test: OpsTest, unit: str = f"{APP_NAME}/0") -> list[str]:
    truststore_password = extract_truststore_password(ops_test=ops_test, unit_name=unit)

    try:
        result = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju ssh --container kafka {unit} 'keytool -list -keystore /etc/kafka/client-truststore.jks -storepass {truststore_password}'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )
    except CalledProcessError as e:
        logger.error(f"{e.output=}, {e.stdout=}, {e.stderr=}")
        raise e

    trusted_aliases = []
    for line in result.splitlines():
        if "trustedCertEntry" not in line:
            continue

        trusted_aliases.append(line.split(",")[0])

    return trusted_aliases


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def unit_id_to_broker_id(unit_id: int) -> int:
    """Converts unit id to broker id in KRaft mode."""
    return KRAFT_NODE_ID_OFFSET + unit_id


def broker_id_to_unit_id(broker_id: int) -> int:
    """Converts broker id to unit id in KRaft mode."""
    return broker_id - KRAFT_NODE_ID_OFFSET
