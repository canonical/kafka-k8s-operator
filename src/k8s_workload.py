#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import secrets
import string
from typing import Dict, List, override

from ops import Container
from ops.pebble import ExecError, Layer
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from core.literals import PATHS
from core.workload import PathsBase, WorkloadBase

logger = logging.getLogger(__name__)


class KafkaPaths(PathsBase):
    """Object to store common paths for Kafka."""

    def __init__(self):
        conf_path = PATHS["CONF"]
        data_path = PATHS["DATA"]
        binaries_path = PATHS["BIN"]
        logs_path = PATHS["LOGS"]
        super().__init__(conf_path, logs_path, data_path, binaries_path)

    @property
    def java_home(self):
        """Location of Java home."""
        return "/usr/lib/jvm/java-17-openjdk-amd64"

    @property
    def server_properties(self):
        """The main server.properties filepath.

        Contains all the main configuration for the service.
        """
        return f"{self.conf_path}/server.properties"

    @property
    def client_properties(self):
        """The main client.properties filepath.

        Contains all the client configuration for the service.
        """
        return f"{self.conf_path}/client.properties"

    @property
    def zk_jaas(self):
        """The zookeeper-jaas.cfg filepath.

        Contains internal+external user credentials used in SASL auth.
        """
        return f"{self.conf_path}/zookeeper-jaas.cfg"

    @property
    def keystore(self):
        """The Java Keystore containing service private-key and signed certificates."""
        return f"{self.conf_path}/keystore.p12"

    @property
    def truststore(self):
        """The Java Truststore containing trusted CAs + certificates."""
        return f"{self.conf_path}/truststore.jks"

    @property
    def log4j_properties(self):
        """The Log4j properties filepath.

        Contains the Log4j configuration options of the service.
        """
        return f"{self.conf_path}/log4j.properties"

    @property
    def jmx_prometheus_javaagent(self):
        """The JMX exporter JAR filepath.

        Used for scraping and exposing mBeans of a JMX target.
        """
        return f"{self.binaries_path}/jmx_prometheus_javaagent.jar"

    @property
    def jmx_prometheus_config(self):
        """The configuration for the JMX exporter."""
        return f"{self.conf_path}/jmx_prometheus.yaml"


class KafkaWorkload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka container."""

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
    def read(self, path: str) -> List[str]:
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
        self, command: str, env: Dict[str, str] | None = None, working_dir: str | None = None
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

    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry_error_callback=lambda state: state.outcome.result(),  # type: ignore
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    @override
    def active(self) -> bool:
        self.container.get_service(self.CONTAINER_SERVICE).is_running()

    def disable_enable(self) -> None:
        """Disables then enables snap service.

        Necessary for snap services to recognise new storage mounts

        Raises:
            subprocess.CalledProcessError if error occurs
        """
        pass

    def run_bin_command(
        self,
        bin_keyword: str,
        bin_args: List[str],
        opts: Dict[str, str] | None = None,
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
        command = f"{self.paths.binaries_path}/bin/kafka-{bin_keyword}.sh {' '.join(bin_args)}"
        return self.exec(command=command, environment=opts)

    def update_environment(self, env: Dict[str, str]) -> None:
        """Updates /etc/environment file."""
        env.update(
            self.map_env(
                [f"JAVA_HOME='{self.paths.java_home}'", f"LOG_DIR='{self.paths.logs_path}'"]
            )
        )

        updated_env = self.get_env() | env
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content, path="/etc/environment")

    @staticmethod
    def map_env(env: list[str]) -> dict[str, str]:
        """Builds environment map for arbitrary env-var strings.

        Returns:
            Dict of env-var and value
        """
        map_env = {}
        for var in env:
            key = "".join(var.split("=", maxsplit=1)[0])
            value = "".join(var.split("=", maxsplit=1)[1:])
            if key:
                # only check for keys, as we can have an empty value for a variable
                map_env[key] = value

        return map_env

    def get_env(self) -> dict[str, str]:
        """Builds map of current basic environment for all processes.

        Returns:
            Dict of env-var and value
        """
        raw_env = self.read("/etc/environment")
        return self.map_env(env=raw_env)

    @staticmethod
    def generate_password() -> str:
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
