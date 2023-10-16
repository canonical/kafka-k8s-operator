#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from subprocess import PIPE, check_output
from typing import Literal, Optional

from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers import (
    APP_NAME,
    get_bootstrap_servers,
    get_k8s_host_from_unit,
    get_unit_address_map,
)
from literals import BINARIES_PATH, CONF_PATH

PROCESS = "kafka.Kafka"
CONTAINER = "kafka"
SERVICE = "kafka"


logger = logging.getLogger(__name__)


@dataclass
class TopicDescription:
    leader: int
    in_sync_replicas: set


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


def get_topic_description(
    ops_test: OpsTest, topic: str, unit_name: Optional[str] = None
) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = get_bootstrap_servers(ops_test)
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

    output = check_output(
        f"microk8s.kubectl exec {unit_name.replace('/', '-')} -c {CONTAINER} -n {ops_test.model.info.name} -- {BINARIES_PATH}/bin/kafka-topics.sh --describe --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {CONF_PATH}/client.properties",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


def get_topic_offsets(ops_test: OpsTest, topic: str, unit_name: Optional[str] = None) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = get_bootstrap_servers(ops_test)
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

    # example of topic offset output: 'test-topic:0:10'
    result = check_output(
        f"microk8s.kubectl exec {unit_name.replace('/', '-')} -c {CONTAINER} -n {ops_test.model.info.name} -- {BINARIES_PATH}/bin/kafka-get-offsets.sh --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {CONF_PATH}/client.properties",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


async def send_control_signal(
    ops_test: OpsTest,
    unit_name: str,
    signal: str,
    container_name: str = CONTAINER,
) -> None:
    f"""Issues given job control signals to a Kafka process on a given Juju unit.

    Args:
        ops_test: OpsTest
        unit_name: the Juju unit name
        signal: the signal to issue
            e.g `SIGKILL`, `SIGSTOP`, `SIGCONT` etc
        container_name: the container to run command on
            Defaults to '{container_name}'
    """
    cmd = f"microk8s.kubectl exec {unit_name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- pkill --signal {signal} -f {PROCESS}"
    check_output(
        cmd,
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def modify_pebble_restart_delay(
    ops_test: OpsTest,
    policy: Literal["extend", "restore"],
    app_name: str = APP_NAME,
    container_name: str = CONTAINER,
    service_name: str = SERVICE,
) -> None:
    f"""Modify the pebble restart delay of the underlying process.

    Args:
        ops_test: OpsTest
        policy: the pebble restart delay policy to apply
            Either 'extend' or 'restore'
        app_name: the Kafka Juju application
        container_name: the container to run command on
            Defaults to '{container_name}'
        service_name: the service running in the container
            Defaults to '{service_name}'
    """
    now = datetime.now().isoformat()
    pebble_patch_path = f"/tmp/pebble_plan_{now}.yaml"

    for unit in ops_test.model.applications[app_name].units:
        logger.info(
            f"Copying extend_pebble_restart_delay manifest to {unit.name} {container_name} container..."
        )
        check_output(
            f"microk8s.kubectl cp ./tests/integration/ha/manifests/{policy}_pebble_restart_delay.yaml {unit.name.replace('/', '-')}:{pebble_patch_path} -c {container_name} -n {ops_test.model.info.name}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Adding {policy} policy to {container_name} pebble plan...")
        check_output(
            f"microk8s.kubectl exec {unit.name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- /charm/bin/pebble add --combine {service_name} {pebble_patch_path}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Replanning {service_name} service...")
        check_output(
            f"microk8s.kubectl exec {unit.name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- /charm/bin/pebble replan",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )


def add_k8s_hosts(ops_test=OpsTest):
    """Adds a the pod dns hostnames to the local /etc/hosts file."""
    address_map = get_unit_address_map(ops_test=ops_test)
    dns_pod_map = [
        f"{pod_ip} {get_k8s_host_from_unit(unit_name)}"
        for unit_name, pod_ip in address_map.items()
    ]

    for item in dns_pod_map:
        cmd = f"echo {item} | sudo tee -a /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Added {item} to /etc/hosts")


def remove_k8s_hosts(ops_test: OpsTest):
    """Removes the dns hostnames from /etc/hosts file."""
    address_map = get_unit_address_map(ops_test=ops_test)

    for unit_name in address_map.keys():
        cmd = f"sudo sed -i -e '/.*{get_k8s_host_from_unit(unit_name)}$/d' /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Removed {unit_name} from /etc/hosts")


def assert_continuous_writes_consistency(result: ContinuousWritesResult):
    """Check results of a stopped ContinuousWrites call against expected results."""
    assert (
        result.count - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count}"
