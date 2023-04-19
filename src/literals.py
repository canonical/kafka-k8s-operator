#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals used by the Kafka K8s charm."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Literal

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka-k8s"
ZK_NAME = "zookeeper-k8s"
PEER = "cluster"
ZOOKEEPER_REL_NAME = "zookeeper"
CHARM_USERS = ["sync"]
REL_NAME = "kafka-client"
TLS_RELATION = "certificates"
CONTAINER = "kafka"
STORAGE = "data"
JMX_EXPORTER_PORT = 9101

CONF_PATH = "/etc/kafka"
DATA_PATH = "/var/lib/kafka"
LOGS_PATH = "/var/log/kafka"
BINARIES_PATH = "/opt/kafka"
JAVA_HOME = "/usr/lib/jvm/java-17-openjdk-amd64"

INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]

INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]

AuthMechanism = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
Scope = Literal["INTERNAL", "CLIENT"]
DebugLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


@dataclass
class Ports:
    client: int
    internal: int


SECURITY_PROTOCOL_PORTS: Dict[AuthMechanism, Ports] = {
    "SASL_PLAINTEXT": Ports(9092, 19092),
    "SASL_SSL": Ports(9093, 19093),
    "SSL": Ports(9094, 19094),
}


@dataclass
class StatusLevel:
    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    ZK_NOT_RELATED = StatusLevel(BlockedStatus("missing required zookeeper relation"), "ERROR")
    ZK_NOT_CONNECTED = StatusLevel(BlockedStatus("unit not connected to zookeeper"), "ERROR")
    ZK_TLS_MISMATCH = StatusLevel(
        BlockedStatus("tls must be enabled on both kafka and zookeeper"), "ERROR"
    )
    ZK_NO_DATA = StatusLevel(WaitingStatus("zookeeper credentials not created yet"), "INFO")
    ADDED_STORAGE = StatusLevel(
        ActiveStatus("manual partition reassignment may be needed to utilize new storage volumes"),
        "WARNING",
    )
    REMOVED_STORAGE = StatusLevel(
        ActiveStatus(
            "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
        ),
        "ERROR",
    )
    REMOVED_STORAGE_NO_REPL = StatusLevel(
        ActiveStatus("potential data loss due to storage removal without replication"),
        "ERROR",
    )
    NO_BROKER_CREDS = StatusLevel(
        WaitingStatus("internal broker credentials not yet added"), "INFO"
    )
    NO_CERT = StatusLevel(WaitingStatus("unit waiting for signed certificates"), "INFO")
    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("service not running"), "WARNING")
