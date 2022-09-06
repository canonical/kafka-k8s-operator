#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import re
from pathlib import Path
from subprocess import PIPE, check_output
from typing import Any, Dict, List, Tuple

import yaml
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
KAFKA_CONTAINER = METADATA["resources"]["kafka-image"]["upstream-source"]
APP_NAME = METADATA["name"]
ZK_NAME = "zookeeper-k8s"


def check_user(model_full_name: str, username: str, zookeeper_uri: str) -> None:
    result = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh kafka-k8s/0 'kafka.configs --zookeeper {zookeeper_uri} --describe --entity-type users --entity-name {username}'",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )

    assert "SCRAM-SHA-512" in result


def get_user(model_full_name: str, username: str, zookeeper_uri: str) -> None:
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
    return zk_relation_data


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
