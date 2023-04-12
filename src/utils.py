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

from literals import BINARIES_PATH, CONF_PATH

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
    extra_args: str,
    zk_tls_config_filepath: Optional[str] = None,
) -> str:
    """Runs kafka bin command with desired args.

    Args:
        container: the container to run on
        bin_keyword: the kafka shell script to run
            e.g `configs`, `topics` etc
        bin_args: the shell command args
        extra_args (optional): the desired `KAFKA_OPTS` env var values for the command
        zk_tls_config_filepath (optional): the path to properties file for ZK TLS

    Returns:
        String of kafka bin command output
    """
    zk_tls_config_file = zk_tls_config_filepath or f"{CONF_PATH}/server.properties"
    environment = {"KAFKA_OPTS": extra_args}
    command = (
        [f"{BINARIES_PATH}/bin/kafka-{bin_keyword}.sh"]
        + bin_args
        + [f"--zk-tls-config-file={zk_tls_config_file}"]
    )

    try:
        process = container.exec(command=command, environment=environment)
        output, _ = process.wait_output()
        logger.debug(f"{output=}")
        return output
    except ExecError as e:
        logger.debug(f"cmd failed:\ncommand={e.command}\nstdout={e.stdout}\nstderr={e.stderr}")
        raise e


def push(container: Container, content: str, path: str) -> None:
    """Wrapper for writing a file and contents to a container.

    Args:
        container: container to push the files into
        content: the text content to write to a file path
        path: the full path of the desired file
    """
    container.push(path, content, make_dirs=True)
