#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging

from ops import Container
from ops.pebble import ExecError, Layer
from typing_extensions import override

from core.workload import KafkaPaths, WorkloadBase

logger = logging.getLogger(__name__)


class KafkaWorkload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka container."""

    paths = KafkaPaths()
    CONTAINER_SERVICE = "kafka"

    def __init__(self, container: Container) -> None:
        self.paths = KafkaPaths()
        self.container = container

    @override
    def start(self, layer: Layer) -> None:
        # start kafka service
        self.container.add_layer(self.CONTAINER_SERVICE, layer, combine=True)
        self.container.replan()

    @override
    def stop(self) -> None:
        self.container.stop(self.CONTAINER_SERVICE)

    @override
    def restart(self) -> None:
        self.container.restart(self.CONTAINER_SERVICE)

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
        self, command: str, env: dict[str, str] | None = None, working_dir: str | None = None
    ) -> str:
        try:
            process = self.container.exec(
                command=command.split(), environment=env, working_dir=working_dir
            )
            output, _ = process.wait_output()
            return output
        except ExecError as e:
            logger.error(str(e.stderr))
            raise e

    @override
    def active(self) -> bool:
        if not self.container.can_connect():
            return False

        return self.container.get_service(self.CONTAINER_SERVICE).is_running()

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
        return self.exec(command=command, env=parsed_opts or None)

    # ------- Kafka vm specific -------

    def install(self) -> None:
        """Loads the Kafka snap from LP."""
        raise NotImplementedError
