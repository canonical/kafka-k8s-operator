#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import time
from collections import defaultdict
from unittest.mock import Mock, PropertyMock, patch

import pytest
from ops import JujuVersion
from ops.testing import Relation
from src.literals import (
    CONTROLLER_USER,
    INTERNAL_USERS,
    PEER_CLUSTER_RELATION,
    SNAP_NAME,
    SUBSTRATE,
)
from tests.unit.helpers import TLSArtifacts, generate_tls_artifacts

from managers.balancer import CruiseControlClient


@pytest.fixture(scope="module")
def zk_data() -> dict[str, str]:
    return {
        "username": "glorfindel",
        "password": "mellon",
        "endpoints": "10.10.10.10",
        "database": "/kafka",
        "chroot": "/kafka",
        "uris": "10.10.10.10:2181",
        "tls": "disabled",
    }


@pytest.fixture(scope="module")
def kraft_data() -> dict[str, str]:
    tls_data = generate_tls_artifacts(sans_ip=["10.10.10.11"])
    return {
        "bootstrap-controller": "10.10.10.10:9097",
        "cluster-uuid": "random-uuid",
        "internal-ca": tls_data.ca,
        "internal-ca-key": tls_data.signing_key,
    }


@pytest.fixture(scope="module")
def peer_cluster_rel() -> Relation:
    return Relation(PEER_CLUSTER_RELATION, "peer_cluster")


@pytest.fixture(scope="module")
def passwords_data() -> dict[str, str]:
    return {f"{user}-password": "mellon" for user in INTERNAL_USERS + [CONTROLLER_USER]}


@pytest.fixture(autouse=True)
def patched_pebble_restart(mocker):
    mocker.patch("ops.model.Container.restart")


@pytest.fixture(autouse=True)
def patched_etc_environment():
    with patch("managers.config.ConfigManager.set_environment") as etc_env:
        yield etc_env


@pytest.fixture(autouse=True)
def patched_workload(monkeypatch: pytest.MonkeyPatch):

    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("charmlibs.pathops.ContainerPath.exists", lambda _: True)
    monkeypatch.setattr("workload.Workload.active", lambda _: True)
    monkeypatch.setattr("workload.Workload.write", lambda _, content, path: None)
    monkeypatch.setattr("workload.Workload.read", lambda _, path: [])
    monkeypatch.setattr("workload.Workload.stop", lambda _: None)
    monkeypatch.setattr("workload.Workload.get_service_pid", lambda _: 1314231)
    monkeypatch.setattr("workload.Workload.last_restart", time.time() - 100.0)
    monkeypatch.setattr("workload.Workload.modify_time", lambda _, file: time.time() - 1000.0)


@pytest.fixture(autouse=True)
def patched_trust(monkeypatch: pytest.MonkeyPatch):
    # patch peer_trusted_certificates here,
    # we have comprehensive unit tests in test_tls_manager
    monkeypatch.setattr("managers.tls.TLSManager.peer_trusted_certificates", {})


@pytest.fixture(autouse=True)
def patched_get_users():
    # patch AuthManager.get_users here, we have unit tests in test_auth
    with patch("managers.auth.AuthManager.get_users", return_value=["admin"]):
        yield


@pytest.fixture(autouse=True)
def random_uuid():
    with patch("managers.controller.ControllerManager.generate_uuid") as gen_uuid:
        gen_uuid.return_value = "some-random-uuid"
        yield


@pytest.fixture(autouse=True)
def patched_sysctl_config():
    if SUBSTRATE == "vm":
        with patch("charm.sysctl.Config.configure") as sysctl_config:
            yield sysctl_config
    else:
        yield


@pytest.fixture(autouse=True)
def patched_exec():
    with patch("workload.KafkaWorkload.exec") as patched_exec:
        yield patched_exec


@pytest.fixture(autouse=True)
def patched_broker_active():
    with patch(
        "managers.controller.ControllerManager.broker_active", return_value=True
    ) as _broker_active:
        yield _broker_active


@pytest.fixture()
def patched_health_machine_configured():
    if SUBSTRATE == "vm":
        with patch(
            "health.KafkaHealth.machine_configured", return_value=True
        ) as machine_configured:
            yield machine_configured
    else:
        yield


@pytest.fixture(autouse=True)
def juju_has_secrets(mocker):
    """Using Juju3 we should always have secrets available."""
    mocker.patch.object(JujuVersion, "has_secrets", new_callable=PropertyMock).return_value = True


@pytest.fixture
def client() -> CruiseControlClient:
    return CruiseControlClient("Beren", "Luthien")


@pytest.fixture(scope="function")
def state() -> dict:
    with open("tests/unit/data/state.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def kafka_cluster_state() -> dict:
    with open("tests/unit/data/kafka_cluster_state.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def proposal() -> dict:
    with open("tests/unit/data/proposal.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(scope="function")
def user_tasks() -> dict:
    with open("tests/unit/data/user_tasks.json") as f:
        content = f.read()

    return json.loads(content)


@pytest.fixture(autouse=True)
def patched_node_ip():
    if SUBSTRATE == "k8s":
        with patch(
            "core.models.KafkaBroker.node_ip",
            new_callable=PropertyMock,
            return_value="10.30.30.10",
        ) as patched_node_ip:
            yield patched_node_ip
    else:
        yield


@pytest.fixture(autouse=True)
def patched_node_port():
    if SUBSTRATE == "k8s":
        with patch(
            "managers.k8s.K8sManager.get_listener_nodeport",
            return_value=20000,
        ) as patched_node_port:
            yield patched_node_port
    else:
        yield


@pytest.fixture(autouse=True)
def patched_snap(monkeypatch):
    cache = Mock()
    snap_mock = Mock()
    snap_mock.services = defaultdict(default_factory=lambda _: {"active": True})
    cache.return_value = {SNAP_NAME: snap_mock}
    with monkeypatch.context() as m:
        m.setattr("charms.operator_libs_linux.v1.snap.SnapCache", cache)
        yield


@pytest.fixture
def tls_artifacts(request: pytest.FixtureRequest) -> TLSArtifacts:
    return generate_tls_artifacts(with_intermediate=bool(request.param))
