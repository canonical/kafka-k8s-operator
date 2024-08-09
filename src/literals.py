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
STORAGE = "data"

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
PEER_CLUSTER_RELATION = "peer-cluster"
PEER_CLUSTER_ORCHESTRATOR_RELATION = "peer-cluster-orchestrator"
BALANCER_TOPICS = [
    "__CruiseControlMetrics",
    "__KafkaCruiseControlPartitionMetricSamples",
    "__KafkaCruiseControlBrokerMetricSamples",
]
MIN_REPLICAS = 3


INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"
INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]
BALANCER_WEBSERVER_USER = "balancer"
BALANCER_WEBSERVER_PORT = 9090
SECRETS_APP = [f"{user}-password" for user in INTERNAL_USERS + [BALANCER_WEBSERVER_USER]]
SECRETS_UNIT = [
    "ca-cert",
    "csr",
    "certificate",
    "truststore-password",
    "keystore-password",
    "private-key",
]

JMX_EXPORTER_PORT = 9101
JMX_CC_PORT = 9102
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
    "kafka": {
        "CONF": "/etc/kafka",
        "LOGS": "/var/log/kafka",
        "DATA": "/var/lib/kafka",
        "BIN": "/opt/kafka",
    },
    "cruise-control": {
        "CONF": "/etc/cruise-control",
        "LOGS": "/var/log/cruise-control",
        "DATA": "/var/lib/cruise-control",
        "BIN": "/opt/cruise-control",
    },
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
class Role:
    value: str
    service: str
    paths: dict[str, str]
    relation: str
    requested_secrets: list[str] | None = None

    def __eq__(self, value: object, /) -> bool:
        """Provide an easy comparison to the configuration key."""
        return self.value == value


BROKER = Role(
    value="broker",
    service="kafka",
    paths=PATHS["kafka"],
    relation=PEER_CLUSTER_RELATION,
    requested_secrets=[
        "balancer-username",
        "balancer-password",
        "balancer-uris",
    ],
)
BALANCER = Role(
    value="balancer",
    service="balancer",
    paths=PATHS["cruise-control"],
    relation=PEER_CLUSTER_ORCHESTRATOR_RELATION,
    requested_secrets=[
        "broker-username",
        "broker-password",
        "broker-uris",
        "zk-username",
        "zk-password",
        "zk-uris",
    ],
)

DEFAULT_BALANCER_GOALS = [
    "ReplicaCapacity",
    "DiskCapacity",
    "NetworkInboundCapacity",
    "NetworkOutboundCapacity",
    "CpuCapacity",
    "ReplicaDistribution",
    "PotentialNwOut",
    "DiskUsageDistribution",
    "NetworkInboundUsageDistribution",
    "NetworkOutboundUsageDistribution",
    "CpuUsageDistribution",
    "LeaderReplicaDistribution",
    "LeaderBytesInDistribution",
    "TopicReplicaDistribution",
    "PreferredLeaderElection",
]
HARD_BALANCER_GOALS = [
    "ReplicaCapacity",
    "DiskCapacity",
    "NetworkInboundCapacity",
    "NetworkOutboundCapacity",
    "CpuCapacity",
    "ReplicaDistribution",
]


class _RebalanceMode:
    FULL = "full"
    ADD = "add"
    REMOVE = "remove"


RebalanceMode = _RebalanceMode()


@dataclass
class StatusLevel:
    """Status object helper."""

    status: StatusBase
    log_level: DebugLevel


class Status(Enum):
    """Collection of possible statuses for the charm."""

    ACTIVE = StatusLevel(ActiveStatus(), "DEBUG")
    NO_PEER_RELATION = StatusLevel(MaintenanceStatus("no peer relation yet"), "DEBUG")
    NO_PEER_CLUSTER_RELATION = StatusLevel(
        BlockedStatus("missing required peer-cluster relation"), "DEBUG"
    )
    BROKER_NOT_RUNNING = StatusLevel(BlockedStatus("Broker not running"), "WARNING")
    NOT_ALL_RELATED = StatusLevel(MaintenanceStatus("not all units related"), "DEBUG")
    CC_NOT_RUNNING = StatusLevel(BlockedStatus("Cruise Control not running"), "WARNING")
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
    NOT_IMPLEMENTED = StatusLevel(
        BlockedStatus("feature not yet implemented"),
        "WARNING",
    )
    NO_BALANCER_RELATION = StatusLevel(MaintenanceStatus("no balancer relation yet"), "DEBUG")
    NO_BROKER_DATA = StatusLevel(MaintenanceStatus("missing broker data"), "DEBUG")
    NOT_ENOUGH_BROKERS = StatusLevel(
        WaitingStatus(f"waiting for {MIN_REPLICAS} online brokers"), "DEBUG"
    )
    WAITING_FOR_REBALANCE = StatusLevel(
        WaitingStatus("awaiting completion of rebalance task"), "DEBUG"
    )


DEPENDENCIES = {
    "kafka_service": {
        "dependencies": {"zookeeper": ">3.6"},
        "name": "kafka",
        "upgrade_supported": "^3",  # zk support removed in 4.0
        "version": "3.6.1",
    },
}
