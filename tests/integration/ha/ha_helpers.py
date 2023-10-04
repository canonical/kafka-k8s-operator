#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from subprocess import PIPE, check_output
from typing import Literal, Optional

from pytest_operator.plugin import OpsTest

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers import APP_NAME, get_address, get_kafka_zk_relation_data
from literals import BINARIES_PATH, CONF_PATH, SECURITY_PROTOCOL_PORTS
from utils import get_active_brokers

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


async def get_topic_description(
    ops_test: OpsTest, topic: str, unit_name: Optional[str] = None
) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

    output = check_output(
        f"kubectl exec {unit_name.replace('/', '-')} -c {CONTAINER} -n {ops_test.model.info.name} -- {BINARIES_PATH}/bin/kafka-topics.sh --describe --topic {topic} --bootstrap-server {','.join(bootstrap_servers)} --command-config {CONF_PATH}/client.properties",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


async def get_topic_offsets(
    ops_test: OpsTest, topic: str, unit_name: Optional[str] = None
) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        ops_test: OpsTest utility class
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = []
    for unit in ops_test.model.applications[APP_NAME].units:
        bootstrap_servers.append(
            await get_address(ops_test=ops_test, unit_num=unit.name.split("/")[-1])
            + f":{SECURITY_PROTOCOL_PORTS['SASL_PLAINTEXT'].client}"
        )
    unit_name = unit_name or ops_test.model.applications[APP_NAME].units[0].name

    # example of topic offset output: 'test-topic:0:10'
    result = check_output(
        f"kubectl exec {unit_name.replace('/', '-')} -c {CONTAINER} -n {ops_test.model.info.name} -- {BINARIES_PATH}/bin/kafka-get-offsets.sh --topic {topic} --bootstrap-server {','.join(bootstrap_servers)} --command-config {CONF_PATH}/client.properties",
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
    cmd = f"kubectl exec {unit_name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- pkill --signal {signal} -f {PROCESS}"
    subprocess.check_output(
        cmd,
        stderr=subprocess.PIPE,
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
        subprocess.check_output(
            f"kubectl cp tests/integration/ha/manifests/{policy}_pebble_restart_delay.yaml {unit.name.replace('/', '-')}:{pebble_patch_path} -c {container_name} -n {ops_test.model.info.name}",
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Adding {policy} policy to {container_name} pebble plan...")
        subprocess.check_output(
            f"kubectl exec {unit.name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- /charm/bin/pebble add --combine {service_name} {pebble_patch_path}",
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Replanning {service_name} service...")
        subprocess.check_output(
            f"kubectl exec {unit.name.replace('/', '-')} -c {container_name} -n {ops_test.model.info.name} -- /charm/bin/pebble replan",
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
        )


async def get_unit_machine_name(ops_test: OpsTest, unit_name: str) -> str:
    """Gets current LXD machine name for a given unit name.

    Args:
        ops_test: OpsTest
        unit_name: the Juju unit name to get from

    Returns:
        String of LXD machine name
            e.g juju-123456-0
    """
    _, raw_hostname, _ = await ops_test.juju("ssh", unit_name, "hostname")
    return raw_hostname.strip()


def network_throttle(machine_name: str) -> None:
    """Cut network from a lxc container (without causing the change of the unit IP address).

    Args:
        machine_name: lxc container hostname
    """
    override_command = f"lxc config device override {machine_name} eth0"
    try:
        subprocess.check_call(override_command.split())
    except subprocess.CalledProcessError:
        # Ignore if the interface was already overridden.
        pass
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress=0kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress=1kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config set {machine_name} limits.network.priority=10"
    subprocess.check_call(limit_set_command.split())


def network_release(machine_name: str) -> None:
    """Restore network from a lxc container (without causing the change of the unit IP address).

    Args:
        machine_name: lxc container hostname
    """
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config set {machine_name} limits.network.priority="
    subprocess.check_call(limit_set_command.split())


def network_cut(machine_name: str) -> None:
    """Cut network from a lxc container.

    Args:
        machine_name: lxc container hostname
    """
    # apply a mask (device type `none`)
    cut_network_command = f"lxc config device add {machine_name} eth0 none"
    subprocess.check_call(cut_network_command.split())


def network_restore(machine_name: str) -> None:
    """Restore network from a lxc container.

    Args:
        machine_name: lxc container hostname
    """
    # remove mask from eth0
    restore_network_command = f"lxc config device remove {machine_name} eth0"
    subprocess.check_call(restore_network_command.split())


def is_up(ops_test: OpsTest, broker_id: int) -> bool:
    """Return if node up."""
    unit_name = ops_test.model.applications[APP_NAME].units[0].name
    kafka_zk_relation_data = get_kafka_zk_relation_data(
        unit_name=unit_name, model_full_name=ops_test.model_full_name
    )
    active_brokers = get_active_brokers(zookeeper_config=kafka_zk_relation_data)
    chroot = kafka_zk_relation_data.get("chroot", "")
    return f"{chroot}/brokers/ids/{broker_id}" in active_brokers


def assert_continuous_writes_consistency(result: ContinuousWritesResult):
    """Check results of a stopped ContinuousWrites call against expected results."""
    assert (
        result.count + result.lost_messages - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count} + lost_messages {result.lost_messages}"
