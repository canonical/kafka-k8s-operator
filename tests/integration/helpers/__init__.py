# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import socket
import subprocess
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml

from literals import CONTROLLER_USER, INTERNAL_USERS, KRAFT_NODE_ID_OFFSET

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
CONTROLLER_NAME = "controller"
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


class KRaftUnitStatus(Enum):
    LEADER = "Leader"
    FOLLOWER = "Follower"
    OBSERVER = "Observer"


def check_socket(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port)) == 0


def get_unit_address_map(model: str, app_name: str = APP_NAME) -> dict[str, str]:
    """Returns map on unit name and host.

    Args:
        model: juju model name
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`

    Returns:
        Dict of key unit name, value unit address
    """
    ips = subprocess.check_output(
        f"JUJU_MODEL={model} juju status {app_name} --format json | jq '.applications | .\"{app_name}\" | .units | .. .address? // empty' | xargs | tr -d '\"'",
        shell=True,
        universal_newlines=True,
    ).split()
    hosts = subprocess.check_output(
        f'JUJU_MODEL={model} juju status {app_name} --format json | jq \'.applications | ."{app_name}" | .units | keys | join(" ")\' | tr -d \'"\'',
        shell=True,
        universal_newlines=True,
    ).split()

    return dict(zip(hosts, ips))


def get_bootstrap_servers(model: str, app_name: str = APP_NAME, port: int = 9092) -> str:
    """Gets all Kafka server addresses for a given application.

    Args:
        model: juju model name
        app_name: the Juju application to get hosts from
            Defaults to `kafka-k8s`
        port: the desired Kafka port.
            Defaults to `9092`

    Returns:
        List of Kafka server addresses and ports
    """
    return ",".join(f"{host}:{port}" for host in get_unit_address_map(model, app_name).values())


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


def get_unit_host(model: str, unit_name: str, app_name: str = APP_NAME, port: int = 9097) -> str:
    f"""Gets server address for a given unit name.

    Args:
        model: Juju model name
        unit_name: the Juju unit to get host from
        app_name: the Juju application the unit belongs to
            Defaults to {app_name}
        port: the desired port.
            Defaults to `9097`

    Returns:
        String of the server address and port
    """
    return f"{get_unit_address_map(model, app_name)[unit_name]}:{port}"


def unit_id_to_broker_id(unit_id: int) -> int:
    """Converts unit id to broker id in KRaft mode."""
    return KRAFT_NODE_ID_OFFSET + unit_id


def broker_id_to_unit_id(broker_id: int) -> int:
    """Converts broker id to unit id in KRaft mode."""
    return broker_id - KRAFT_NODE_ID_OFFSET
