#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals used by the Kafka K8s charm."""

from dataclasses import dataclass
from typing import Dict, Literal

CHARM_KEY = "kafka-k8s"
ZK_NAME = "zookeeper-k8s"
PEER = "cluster"
ZOOKEEPER_REL_NAME = "zookeeper"
CHARM_USERS = ["sync"]
REL_NAME = "kafka-client"
TLS_RELATION = "certificates"
CONTAINER = "kafka"
STORAGE = "log-data"
DATA_DIR = "/data/kafka"
LOG_DIR = "/logs/kafka"
JMX_EXPORTER_PORT = 9101

INTER_BROKER_USER = "sync"
ADMIN_USER = "admin"

INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]

AuthMechanism = Literal["SASL_PLAINTEXT", "SASL_SSL", "SSL"]
Scope = Literal["INTERNAL", "CLIENT"]


@dataclass
class Ports:
    client: int
    internal: int


SECURITY_PROTOCOL_PORTS: Dict[AuthMechanism, Ports] = {
    "SASL_PLAINTEXT": Ports(9092, 19092),
    "SASL_SSL": Ports(9093, 19093),
    "SSL": Ports(9094, 19094),
}
