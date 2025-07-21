#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import re
import string
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from subprocess import PIPE, CalledProcessError, check_output
from typing import Literal

import jubilant

from integration.ha.continuous_writes import ContinuousWritesResult
from integration.helpers import (
    APP_NAME,
    get_bootstrap_servers,
    get_k8s_host_from_unit,
    get_unit_address_map,
)
from literals import BROKER, CONTAINER

PROCESS = "kafka.Kafka"
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
    juju: jubilant.Juju,
    topic: str,
) -> TopicDescription:
    """Get the broker with the topic leader.

    Args:
        juju: jubilant.Juju fixture
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = get_bootstrap_servers(f"{juju.model}")

    output = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            output = check_output(
                f"kubectl exec {unit.replace('/', '-')} -c {CONTAINER} -n {juju.model} -- {BROKER.paths['BIN']}/bin/kafka-topics.sh --describe --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {BROKER.paths['CONF']}/client.properties",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
            break
        except CalledProcessError:
            logger.debug(f"Unit {unit} not available, trying next unit...")

    if not output:
        raise Exception("get_topic_description: No units available!")

    leader = int(re.search(r"Leader: (\d+)", output)[1])
    in_sync_replicas = {int(i) for i in re.search(r"Isr: ([\d,]+)", output)[1].split(",")}

    return TopicDescription(leader, in_sync_replicas)


def get_topic_offsets(juju: jubilant.Juju, topic: str) -> list[str]:
    """Get the offsets of a topic on a unit.

    Args:
        juju: jubilant.Juju fixture
        topic: the desired topic to check
        unit_name: unit to run the command on
    """
    bootstrap_servers = get_bootstrap_servers(f"{juju.model}")

    result = ""
    for unit in juju.status().apps[APP_NAME].units:
        try:
            # example of topic offset output: 'test-topic:0:10'
            result = check_output(
                f"kubectl exec {unit.replace('/', '-')} -c {CONTAINER} -n {juju.model} -- {BROKER.paths['BIN']}/bin/kafka-get-offsets.sh --topic {topic} --bootstrap-server {bootstrap_servers} --command-config {BROKER.paths['CONF']}/client.properties",
                stderr=PIPE,
                shell=True,
                universal_newlines=True,
            )
        except CalledProcessError:
            logger.debug(f"Unit {unit} not available, trying next unit...")

    if not result:
        raise Exception("get_topic_offsets: No units available!")

    return re.search(rf"{topic}:(\d+:\d+)", result)[1].split(":")


def send_control_signal(
    juju: jubilant.Juju,
    unit_name: str,
    signal: str,
    container_name: str = CONTAINER,
) -> None:
    f"""Issues given job control signals to a Kafka process on a given Juju unit.

    Args:
        juju: jubilant.Juju fixture
        unit_name: the Juju unit name
        signal: the signal to issue
            e.g `SIGKILL`, `SIGSTOP`, `SIGCONT` etc
        container_name: the container to run command on
            Defaults to '{container_name}'
    """
    cmd = f"kubectl exec {unit_name.replace('/', '-')} -c {container_name} -n {juju.model} -- pkill --signal {signal} -f {PROCESS}"
    check_output(
        cmd,
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def modify_pebble_restart_delay(
    juju: jubilant.Juju,
    policy: Literal["extend", "restore"],
    app_name: str = APP_NAME,
    container_name: str = CONTAINER,
    service_name: str = BROKER.service,
) -> None:
    f"""Modify the pebble restart delay of the underlying process.

    Args:
        juju: jubilant.Juju fixture
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

    for unit in juju.status().apps[app_name].units:
        logger.info(
            f"Copying extend_pebble_restart_delay manifest to {unit} {container_name} container..."
        )
        check_output(
            f"kubectl cp ./tests/integration/ha/manifests/{policy}_pebble_restart_delay.yaml {unit.replace('/', '-')}:{pebble_patch_path} -c {container_name} -n {juju.model}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Adding {policy} policy to {container_name} pebble plan...")
        check_output(
            f"kubectl exec {unit.replace('/', '-')} -c {container_name} -n {juju.model} -- /charm/bin/pebble add --combine {service_name}-{uuid.uuid4().hex} {pebble_patch_path}",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        logger.info(f"Replanning {service_name} service...")
        check_output(
            f"kubectl exec {unit.replace('/', '-')} -c {container_name} -n {juju.model} -- /charm/bin/pebble restart kafka",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )


def deploy_chaos_mesh(namespace: str) -> None:
    """Deploy chaos mesh to the provided namespace.

    Args:
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        " ".join(
            [
                "tests/integration/ha/scripts/deploy_chaos_mesh.sh",
                namespace,
            ]
        ),
        shell=True,
        env=env,
    )


def destroy_chaos_mesh(namespace: str) -> None:
    """Remove chaos mesh from the provided namespace.

    Args:
        namespace: The namespace to deploy chaos mesh to
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        f"tests/integration/ha/scripts/destroy_chaos_mesh.sh {namespace}",
        shell=True,
        env=env,
    )


def isolate_instance_from_cluster(juju: jubilant.Juju, unit_name: str) -> None:
    """Apply a NetworkChaos file to use chaos-mesh to simulate a network cut.

    Args:
        juju: jubilant.Juju fixture
        unit_name: the Juju unit running the ZooKeeper process
    """
    with tempfile.NamedTemporaryFile() as temp_file:
        with open(
            "tests/integration/ha/manifests/chaos_network_loss.yaml", "r"
        ) as chaos_network_loss_file:
            template = string.Template(chaos_network_loss_file.read())
            chaos_network_loss = template.substitute(
                namespace=juju.model,
                pod=unit_name.replace("/", "-"),
            )

            temp_file.write(str.encode(chaos_network_loss))
            temp_file.flush()

        env = os.environ
        env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

        check_output(" ".join(["kubectl", "apply", "-f", temp_file.name]), shell=True, env=env)


def remove_instance_isolation(juju: jubilant.Juju) -> None:
    """Delete the NetworkChaos that is isolating the primary unit of the cluster.

    Args:
        juju: jubilant.Juju fixture
    """
    env = os.environ
    env["KUBECONFIG"] = os.path.expanduser("~/.kube/config")

    check_output(
        f"kubectl -n {juju.model} delete --ignore-not-found=true networkchaos network-loss-primary",
        shell=True,
        env=env,
    )


def add_k8s_hosts(juju: jubilant.Juju):
    """Adds a the pod dns hostnames to the local /etc/hosts file."""
    address_map = get_unit_address_map(model=f"{juju.model}")
    dns_pod_map = [
        f"{pod_ip} {get_k8s_host_from_unit(unit_name)}"
        for unit_name, pod_ip in address_map.items()
    ]

    for item in dns_pod_map:
        cmd = f"echo {item} | sudo tee -a /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Added {item} to /etc/hosts")


def remove_k8s_hosts(juju: jubilant.Juju):
    """Removes the dns hostnames from /etc/hosts file."""
    address_map = get_unit_address_map(model=f"{juju.model}")

    for unit_name in address_map.keys():
        cmd = f"sudo sed -i -e '/.*{get_k8s_host_from_unit(unit_name)}$/d' /etc/hosts"
        check_output(cmd, stderr=PIPE, shell=True, universal_newlines=True)
        logger.info(f"Removed {unit_name} from /etc/hosts")


def delete_pod(juju: jubilant.Juju, unit_name: str):
    check_output(
        f"kubectl delete pod {unit_name.replace('/', '-')} -n {juju.model}",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )


def assert_continuous_writes_consistency(result: ContinuousWritesResult):
    """Check results of a stopped ContinuousWrites call against expected results."""
    assert (
        result.count - 1 == result.last_expected_message
    ), f"Last expected message {result.last_expected_message} doesn't match count {result.count}"
