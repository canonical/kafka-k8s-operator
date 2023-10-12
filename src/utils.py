#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of helper methods for checking active connections between ZK and Kafka."""

import base64
import logging
import re
import secrets
import string
from typing import Dict, List, Optional, Set

from charms.zookeeper.v0.client import ZooKeeperManager
from kazoo.exceptions import AuthFailedError, NoNodeError
from ops.model import Container, Unit
from ops.pebble import ExecError
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from literals import BINARIES_PATH

logger = logging.getLogger(__name__)


@retry(
    # retry to give ZK time to update its broker zNodes before failing
    wait=wait_fixed(5),
    stop=stop_after_attempt(6),
    retry_error_callback=(lambda state: state.outcome.result()),
    retry=retry_if_not_result(lambda result: True if result else False),
)
def broker_active(unit: Unit, zookeeper_config: Dict[str, str]) -> bool:
    """Checks ZooKeeper for client connections, checks for specific broker id.

    Args:
        unit: the `Unit` to check connection of
        zookeeper_config: the relation provided by ZooKeeper

    Returns:
        True if broker id is recognised as active by ZooKeeper. Otherwise False.
    """
    broker_id = unit.name.split("/")[1]
    brokers = get_active_brokers(zookeeper_config=zookeeper_config)
    chroot = zookeeper_config.get("chroot", "")
    return f"{chroot}/brokers/ids/{broker_id}" in brokers


def get_active_brokers(zookeeper_config: Dict[str, str]) -> Set[str]:
    """Gets all brokers currently connected to ZooKeeper.

    Args:
        zookeeper_config: the relation data provided by ZooKeeper

    Returns:
        Set of active broker ids
    """
    chroot = zookeeper_config.get("chroot", "")
    hosts = zookeeper_config.get("endpoints", "").split(",")
    username = zookeeper_config.get("username", "")
    password = zookeeper_config.get("password", "")

    zk = ZooKeeperManager(hosts=hosts, username=username, password=password)
    path = f"{chroot}/brokers/ids/"

    try:
        brokers = zk.leader_znodes(path=path)
    # auth might not be ready with ZK after relation yet
    except (NoNodeError, AuthFailedError) as e:
        logger.debug(str(e))
        return set()

    return brokers


def generate_password() -> str:
    """Creates randomized string for use as app passwords.

    Returns:
        String of 32 randomized letter+digit characters
    """
    return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])


def parse_tls_file(raw_content: str) -> str:
    """Parse TLS files from both plain text or base64 format."""
    if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
        return raw_content
    return base64.b64decode(raw_content).decode("utf-8")


def run_bin_command(
    container: Container,
    bin_keyword: str,
    bin_args: List[str],
    environment: dict[str, str] = None,
) -> str:
    """Runs kafka bin command with desired args.

    Args:
        container: the container to run on
        bin_keyword: the kafka shell script to run
            e.g `configs`, `topics` etc
        bin_args: the shell command args
        environment: any additional environment strings

    Returns:
        String of kafka bin command output
    """
    command = [f"{BINARIES_PATH}/bin/kafka-{bin_keyword}.sh"] + bin_args

    try:
        process = container.exec(command=command, environment=environment)
        output, _ = process.wait_output()
        return output
    except ExecError as e:
        logger.error(str(e.stderr))
        raise e


def safe_pull_file(container: Container, filepath: str) -> Optional[List[str]]:
    """Load file contents from charm workload.

    Args:
        container: Container to pull from
        filepath: the filepath to load data from

    Returns:
        List of file content lines
        None if file does not exist
    """
    if not container.exists(filepath):
        return None
    else:
        with container.pull(filepath) as f:
            content = f.read().split("\n")

    return content


def safe_push_to_file(container: Container, content: str, path: str) -> None:
    """Ensures destination filepath exists before writing.

    Args:
        container: Container to push to
        content: the content to be written to a file
        path: the full destination filepath
    """
    container.push(path, content, make_dirs=True)


def map_env(env: list[str]) -> dict[str, str]:
    """Builds environment map for arbitrary env-var strings.

    Returns:
        Dict of env-var and value
    """
    map_env = {}
    for var in env:
        key = "".join(var.split("=", maxsplit=1)[0])
        value = "".join(var.split("=", maxsplit=1)[1:])
        if key:
            # only check for keys, as we can have an empty value for a variable
            map_env[key] = value

    return map_env


def get_env(container: Container) -> dict[str, str]:
    """Builds map of current basic environment for all processes.

    Returns:
        Dict of env-var and value
    """
    raw_env = safe_pull_file(container, "/etc/environment") or []
    return map_env(env=raw_env)


def update_env(container: Container, env: dict[str, str]) -> None:
    """Updates /etc/environment file."""
    updated_env = get_env(container) | env
    content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
    safe_push_to_file(container=container, content=content, path="/etc/environment")
