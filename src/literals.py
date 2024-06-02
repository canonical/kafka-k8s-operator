#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of globals common to the Kafka K8s Charm."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, StatusBase, WaitingStatus

CHARM_KEY = "kafka-k8s"
CONTAINER = "kafka"
SUBSTRATE = "k8s"

USER = "kafka"
GROUP = "kafka"

# FIXME: these need better names
PEER = "cluster"
ZK = "zookeeper"
REL_NAME = "kafka-client"
OAUTH_REL_NAME = "oauth"

TLS_RELATION = "certificates"
TRUSTED_CERTIFICATE_RELATION = "trusted-certificate"
TRUSTED_CA_RELATION = "trusted-ca"

INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]
SECRETS_APP = [f"{user}-password" for user in INTERNAL_USERS]
SECRETS_UNIT = [
    "ca-cert",
    "csr",
    "certificate",
    "truststore-password",
    "keystore-password",
    "private-key",
]

JMX_EXPORTER_PORT = 9101
METRICS_RULES_DIR = "./src/alert_rules/prometheus"
LOGS_RULES_DIR = "./src/alert_rules/loki"

AuthProtocol = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
AuthMechanism = Literal["SCRAM-SHA-512", "OAUTHBEARER", "SSL"]
Scope = Literal["INTERNAL", "CLIENT"]
DebugLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
DatabagScope = Literal["unit", "app"]
Substrates = Literal["vm", "k8s"]

JVM_MEM_MIN_GB = 1
JVM_MEM_MAX_GB = 6
OS_REQUIREMENTS = {
    "vm.max_map_count": "262144",
    "vm.swappiness": "1",
    "vm.dirty_ratio": "80",
    "vm.dirty_background_ratio": "5",
}

PATHS = {
    "CONF": "/etc/kafka",
    "LOGS": "/var/log/kafka",
    "DATA": "/var/lib/kafka",
    "BIN": "/opt/kafka",
}


@dataclass
class Ports:
    """Types of ports for a Kafka broker."""

    client: int
    internal: int


SECURITY_PROTOCOL_PORTS: dict[tuple[AuthProtocol, AuthMechanism], Ports] = {
    ("SASL_PLAINTEXT", "SCRAM-SHA-512"): Ports(9092, 19092),
    ("SASL_PLAINTEXT", "OAUTHBEARER"): Ports(9095, 19095),
    ("SASL_SSL", "SCRAM-SHA-512"): Ports(9093, 19093),
    ("SASL_SSL", "OAUTHBEARER"): Ports(9096, 19096),
    ("SSL", "SSL"): Ports(9094, 19094),
}


@dataclass
class StatusLevel:
    """Status object helper."""

    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    """Collection of possible statuses for the charm."""

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    SERVICE_NOT_RUNNING = StatusLevel(BlockedStatus("service not running"), "WARNING")
    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    ZK_NOT_RELATED = StatusLevel(BlockedStatus("missing required zookeeper relation"), "DEBUG")
    ZK_NOT_CONNECTED = StatusLevel(BlockedStatus("unit not connected to zookeeper"), "ERROR")
    ZK_TLS_MISMATCH = StatusLevel(
        BlockedStatus("tls must be enabled on both kafka and zookeeper"), "ERROR"
    )
    ZK_NO_DATA = StatusLevel(WaitingStatus("zookeeper credentials not created yet"), "DEBUG")
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
        WaitingStatus("internal broker credentials not yet added"), "DEBUG"
    )
    NO_CERT = StatusLevel(WaitingStatus("unit waiting for signed certificates"), "INFO")


DEPENDENCIES = {
    "kafka_service": {
        "dependencies": {"zookeeper": ">3.6"},
        "name": "kafka",
        "upgrade_supported": "^3",  # zk support removed in 4.0
        "version": "3.6.1",
    },
}
