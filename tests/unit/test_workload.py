#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import datetime
import inspect
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.workload import WorkloadBase
from literals import SUBSTRATE
from workload import KafkaWorkload

if SUBSTRATE == "vm":
    from charms.operator_libs_linux.v2.snap import SnapError

pytestmark = [
    pytest.mark.broker,
]


@pytest.fixture()
def fake_workload(tmp_path_factory, monkeypatch) -> WorkloadBase:
    monkeypatch.undo()
    workload = KafkaWorkload(MagicMock())
    workload.paths.conf_path = tmp_path_factory.mktemp("workload")
    return workload


def test_last_restart_parses_correctly(patched_exec, monkeypatch):
    monkeypatch.undo()
    patched_exec.return_value = inspect.cleandoc(
        """
        Service  Startup  Current  Since
        kafka    enabled  active   2025-08-08T08:22:37Z
    """
    )

    assert (
        KafkaWorkload(MagicMock()).last_restart
        == datetime.datetime(2025, 8, 8, 8, 22, 37, tzinfo=datetime.timezone.utc).timestamp()
    )

    patched_exec.return_value = inspect.cleandoc(
        """
    Service   Startup   Current   Since
    kafka     enabled   active    2025-08-15T11:05:51Z
    promtail  disabled  inactive  -"""
    )

    assert (
        KafkaWorkload(MagicMock()).last_restart
        == datetime.datetime(2025, 8, 15, 11, 5, 51, tzinfo=datetime.timezone.utc).timestamp()
    )


@pytest.mark.skip(reason="workload tests not needed for K8s")
def test_run_bin_command_args(patched_exec):
    """Checks KAFKA_OPTS env-var and zk-tls flag present in all snap commands."""
    KafkaWorkload(MagicMock()).run_bin_command(
        bin_keyword="configs", bin_args=["--list"], opts=["-Djava"]
    )

    assert "charmed-kafka.configs" in patched_exec.call_args.args[0].split()
    assert "-Djava" == patched_exec.call_args.args[0].split()[0]
    assert "--list" == patched_exec.call_args.args[0].split()[-1]


@pytest.mark.skip(reason="workload tests not needed for K8s")
def test_get_service_pid_raises(monkeypatch):
    """Checks get_service_pid raises if PID cannot be found."""
    monkeypatch.undo()
    with (
        patch(
            "builtins.open",
            new_callable=mock_open,
            read_data="0::/system.slice/snap.charmed-zookeeper.daemon.service",
        ),
        patch("subprocess.check_output", return_value="123"),
        pytest.raises(SnapError),
    ):
        KafkaWorkload(MagicMock()).get_service_pid()


@pytest.mark.skip(reason="workload tests not needed for K8s")
def test_get_service_pid_raises_no_pid(monkeypatch):
    """Checks get_service_pid raises if PID cannot be found."""
    monkeypatch.undo()
    with (
        patch("subprocess.check_output", return_value=""),
        pytest.raises(SnapError),
    ):
        KafkaWorkload(MagicMock()).get_service_pid()
