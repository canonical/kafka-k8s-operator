#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import re

from ops import Container
from ops.pebble import ExecError, Layer
from typing_extensions import override

from core.workload import CharmedKafkaPaths, WorkloadBase
from literals import BALANCER, BROKER, CHARM_KEY

logger = logging.getLogger(__name__)


class Workload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka container."""

    paths: CharmedKafkaPaths
    service: str

    def __init__(self, container: Container) -> None:
        self.container = container

    @override
    def start(self, layer: Layer) -> None:
        self.container.add_layer(CHARM_KEY, layer, combine=True)
        self.container.restart(self.service)

    @override
    def stop(self) -> None:
        self.container.stop(self.service)

    @override
    def restart(self) -> None:
        self.container.restart(self.service)

    @override
    def read(self, path: str) -> list[str]:
        if not self.container.exists(path):
            return []  # FIXME previous return is None
        else:
            with self.container.pull(path) as f:
                content = f.read().split("\n")

        return content

    @override
    def write(self, content: str, path: str) -> None:
        self.container.push(path, content, make_dirs=True)

    @override
    def exec(
        self, command: list[str], env: dict[str, str] | None = None, working_dir: str | None = None
    ) -> str:
        try:
            process = self.container.exec(
                command=command,
                environment=env,
                working_dir=working_dir,
                combine_stderr=True,
            )
            output, _ = process.wait_output()
            return output
        except ExecError as e:
            logger.debug(e)
            raise e

    @override
    def active(self) -> bool:
        if not self.container.can_connect():
            return False

        if self.service not in self.container.get_services():
            return False

        return self.container.get_service(self.service).is_running()

    @override
    def run_bin_command(
        self,
        bin_keyword: str,
        bin_args: list[str],
        opts: list[str] = [],
    ) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional environment strings

        Returns:
            String of kafka bin command output
        """
        parsed_opts = {}
        for opt in opts:
            k, v = opt.split("=", maxsplit=1)
            parsed_opts[k] = v.replace("'", "")

        command = f"{self.paths.binaries_path}/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command.split(), env=parsed_opts or None)

    # ------- Kafka vm specific -------

    def install(self) -> None:
        """Loads the Kafka snap from LP."""
        raise NotImplementedError

    @override
    def get_version(self) -> str:
        if not self.container.can_connect():
            return ""

        try:
            version = re.split(r"[\s\-]", self.run_bin_command("topics", ["--version"]))[0]
        except:  # noqa: E722
            version = ""
        return version


class KafkaWorkload(Workload):
    """Broker specific wrapper."""

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self.paths = CharmedKafkaPaths(BROKER)
        self.service = BROKER.service

    @override
    def get_version(self) -> str:
        if not self.active:
            return ""
        try:
            version = re.split(r"[\s\-]", self.run_bin_command("topics", ["--version"]))[0]
        except:  # noqa: E722
            version = ""
        return version


class BalancerWorkload(Workload):
    """Balancer specific wrapper."""

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self.paths = CharmedKafkaPaths(BALANCER)
        self.service = BALANCER.service

    @override
    def run_bin_command(
        self,
        bin_keyword: str,
        bin_args: list[str],
        opts: list[str] = [],
    ) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional environment strings

        Returns:
            String of kafka bin command output
        """
        parsed_opts = {}
        for opt in opts:
            k, v = opt.split("=", maxsplit=1)
            parsed_opts[k] = v.replace("'", "")

        command = f"{BROKER.paths['BIN']}/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command.split(), env=parsed_opts or None)

    @override
    def get_version(self) -> str:
        raise NotImplementedError
