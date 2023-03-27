#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""
import logging
import os
from typing import Dict, List, Optional

from ops.model import Container, Unit

from literals import (
    ADMIN_USER,
    CONTAINER,
    DATA_DIR,
    INTER_BROKER_USER,
    JMX_EXPORTER_PORT,
    PEER,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    STORAGE,
    ZOOKEEPER_REL_NAME,
    AuthMechanism,
    Scope,
)
from utils import push

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
allow.everyone.if.no.acl.found=false
"""


class Listener:
    """Definition of a listener.

    Args:
        host: string with the host that will be announced
        protocol: auth protocol to be used
        scope: scope of the listener, CLIENT or INTERNAL.
    """

    def __init__(self, host: str, protocol: AuthMechanism, scope: Scope):
        self.protocol: AuthMechanism = protocol
        self.host = host
        self.scope = scope

    @property
    def scope(self) -> Scope:
        """Internal scope validator."""
        return self._scope

    @scope.setter
    def scope(self, value):
        """Internal scope validator."""
        if value not in ["CLIENT", "INTERNAL"]:
            raise ValueError("Only CLIENT and INTERNAL scopes are accepted")

        self._scope = value

    @property
    def port(self) -> int:
        """Port associated with the protocol/scope.

        Defaults to internal port.

        Returns:
            Integer of port number.
        """
        if self.scope == "CLIENT":
            return SECURITY_PROTOCOL_PORTS[self.protocol].client

        return SECURITY_PROTOCOL_PORTS[self.protocol].internal

    @property
    def name(self) -> str:
        """Name of the listener."""
        return f"{self.scope}_{self.protocol}"

    @property
    def protocol_map(self) -> str:
        """Return `name:protocol`."""
        return f"{self.name}:{self.protocol}"

    @property
    def listener(self) -> str:
        """Return `name://:port`."""
        return f"{self.name}://:{self.port}"

    @property
    def advertised_listener(self) -> str:
        """Return `name://host:port`."""
        return f"{self.name}://{self.host}:{self.port}"


class KafkaConfig:
    """Manager for handling Kafka configuration."""

    def __init__(self, charm):
        self.charm = charm
        self.default_config_path = f"{DATA_DIR}/config"
        self.server_properties_filepath = f"{self.default_config_path}/server.properties"
        self.client_properties_filepath = f"{self.default_config_path}/client.properties"
        self.zk_jaas_filepath = f"{self.default_config_path}/kafka-jaas.cfg"
        self.keystore_filepath = f"{self.default_config_path}/keystore.p12"
        self.truststore_filepath = f"{self.default_config_path}/truststore.jks"
        self.jmx_exporter_filepath = "/opt/kafka/extra/jmx_prometheus_javaagent.jar"
        self.jmx_config_filepath = "/opt/kafka/default-config/jmx_prometheus.yaml"

    @property
    def internal_user_credentials(self) -> Dict[str, str]:
        """The charm internal usernames and passwords, e.g `sync` and `admin`.

        Returns:
            Dict of usernames and passwords.
        """
        return {
            user: password
            for user in [INTER_BROKER_USER, ADMIN_USER]
            if (password := self.charm.get_secret(scope="app", key=f"{user}-password"))
        }

    @property
    def container(self) -> Container:
        """Grabs the current Kafka container."""
        return getattr(self.charm, "unit").get_container(CONTAINER)

    @property
    def sync_password(self) -> Optional[str]:
        """Returns charm-set sync_password for server-server auth between brokers."""
        return self.charm.get_secret(scope="app", key="sync-password")

    @property
    def zookeeper_config(self) -> Dict[str, str]:
        """The config from current ZooKeeper relations for data necessary for broker connection.

        Returns:
            Dict of ZooKeeeper:
            `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`.
        """
        zookeeper_config = {}
        # loop through all relations to ZK, attempt to find all needed config
        for relation in self.charm.model.relations[ZOOKEEPER_REL_NAME]:
            zk_keys = ["username", "password", "endpoints", "chroot", "uris", "tls"]
            missing_config = any(
                relation.data[relation.app].get(key, None) is None for key in zk_keys
            )

            # skip if config is missing
            if missing_config:
                continue

            # set if exists
            zookeeper_config.update(relation.data[relation.app])
            break

        if zookeeper_config:
            sorted_uris = sorted(
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
            )
            sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
            zookeeper_config["connect"] = ",".join(sorted_uris)

        return zookeeper_config

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. False otherwise.
        """
        if self.zookeeper_config.get("connect", None):
            return True

        return False

    @property
    def auth_args(self) -> List[str]:
        """The necessary Java config options for SASL/SCRAM auth.

        Returns:
            List of Java config auth options
        """
        return [f"-Djava.security.auth.login.config={self.zk_jaas_filepath}"]

    @property
    def extra_args(self) -> List[str]:
        """Collection of extra Java config arguments.

        Returns:
            String of command argument to be prepended to start-up command
        """
        extra_args = [
            f"-javaagent:{self.jmx_exporter_filepath}={JMX_EXPORTER_PORT}:{self.jmx_config_filepath}"
        ] + self.auth_args

        return extra_args

    @property
    def bootstrap_server(self) -> List[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers.
        """
        units: List[Unit] = list(
            set([self.charm.unit] + list(self.charm.model.get_relation(PEER).units))
        )
        hosts = [self.get_host_from_unit(unit=unit) for unit in units]
        port = (
            SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
            if self.charm.tls.enabled
            else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        )
        return [f"{host}:{port}" for host in hosts]

    @property
    def kafka_command(self) -> str:
        """The run command for starting the Kafka service.

        Returns:
            String of startup command and expected config filepath
        """
        entrypoint = "/opt/kafka/bin/kafka-server-start.sh"
        return f"{entrypoint} {self.server_properties_filepath}"

    @property
    def default_replication_properties(self) -> List[str]:
        """Builds replication-related properties based on the expected app size.

        Returns:
            List of properties to be set
        """
        replication_factor = min([3, self.charm.app.planned_units()])
        min_isr = max([1, replication_factor - 1])

        return [
            f"default.replication.factor={replication_factor}",
            f"num.partitions={replication_factor}",
            f"transaction.state.log.replication.factor={replication_factor}",
            f"offsets.topic.replication.factor={replication_factor}",
            f"min.insync.replicas={min_isr}",
            f"transaction.state.log.min.isr={min_isr}",
        ]

    @property
    def auth_properties(self) -> List[str]:
        """Builds properties necessary for inter-broker authorization through ZooKeeper.

        Returns:
            List of properties to be set
        """
        broker_id = self.charm.unit.name.split("/")[1]
        return [
            f"broker.id={broker_id}",
            f'zookeeper.connect={self.zookeeper_config["connect"]}',
        ]

    @property
    def zookeeper_tls_properties(self) -> List[str]:
        """Builds the properties necessary for SSL connections to ZooKeeper.

        Returns:
            List of properties to be set.
        """
        return [
            "zookeeper.ssl.client.enable=true",
            f"zookeeper.ssl.truststore.location={self.truststore_filepath}",
            f"zookeeper.ssl.truststore.password={self.charm.tls.truststore_password}",
            "zookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty",
            "zookeeper.ssl.endpoint.identification.algorithm=",
        ]

    @property
    def tls_properties(self) -> List[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set.
        """
        return [
            f"ssl.truststore.location={self.truststore_filepath}",
            f"ssl.truststore.password={self.charm.tls.truststore_password}",
            f"ssl.keystore.location={self.keystore_filepath}",
            f"ssl.keystore.password={self.charm.tls.keystore_password}",
            "ssl.client.auth=none",
        ]

    @property
    def scram_properties(self) -> List[str]:
        """Builds the properties for each scram listener.

        Returns:
            list of scram properties to be set.
        """
        scram_properties = [
            f'listener.name.{self.internal_listener.name.lower()}.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{INTER_BROKER_USER}" password="{self.internal_user_credentials[INTER_BROKER_USER]}";'
        ]
        client_scram = [
            auth.name for auth in self.client_listeners if auth.protocol.startswith("SASL_")
        ]
        for name in client_scram:
            scram_properties.append(
                f'listener.name.{name.lower()}.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{INTER_BROKER_USER}" password="{self.internal_user_credentials[INTER_BROKER_USER]}";'
            )

        return scram_properties

    @property
    def security_protocol(self) -> AuthMechanism:
        """Infers current charm security.protocol based on current relations."""
        # FIXME: When we have multiple auth_mechanims/listeners, remove this method
        return "SASL_SSL" if self.charm.tls.enabled else "SASL_PLAINTEXT"

    @property
    def auth_mechanisms(self) -> List[AuthMechanism]:
        """Return a list of enabled auth mechanisms."""
        # TODO: At the moment only one mechanism for extra listeners. Will need to be
        # extended with more depending on configuration settings.
        protocol = self.security_protocol
        return [protocol]

    @property
    def internal_listener(self) -> Listener:
        """Return the internal listener."""
        protocol = self.security_protocol
        return Listener(
            host=self.get_host_from_unit(unit=self.charm.unit), protocol=protocol, scope="INTERNAL"
        )

    @property
    def client_listeners(self) -> List[Listener]:
        """Return a list of extra listeners."""
        # if there is a relation with kafka then add extra listener
        if not self.charm.model.relations.get(REL_NAME, None):
            return []

        return [
            Listener(
                host=self.get_host_from_unit(unit=self.charm.unit), protocol=auth, scope="CLIENT"
            )
            for auth in self.auth_mechanisms
        ]

    @property
    def all_listeners(self) -> List[Listener]:
        """Return a list with all expected listeners."""
        return [self.internal_listener] + self.client_listeners

    @property
    def super_users(self) -> str:
        """Generates all users with super/admin permissions for the cluster from relations.

        Formatting allows passing to the `super.users` property.

        Returns:
            Semicolon delimited string of current super users.
        """
        super_users = [INTER_BROKER_USER, ADMIN_USER]
        for relation in self.charm.model.relations[REL_NAME]:
            extra_user_roles = relation.data[relation.app].get("extra-user-roles", "")
            password = (
                self.charm.model.get_relation(PEER)
                .data[self.charm.app]
                .get(f"relation-{relation.id}", None)
            )
            # if passwords are set for client admins, they're good to load
            if "admin" in extra_user_roles and password is not None:
                super_users.append(f"relation-{relation.id}")

        super_users_arg = [f"User:{user}" for user in super_users]

        return ";".join(super_users_arg)

    @property
    def log_dirs(self) -> str:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            String of log.dirs property value to be set
        """
        return ",".join(
            [os.fspath(storage.location) for storage in self.charm.model.storages[STORAGE]]
        )

    @property
    def client_properties(self) -> List[str]:
        """Builds all properties necessary for running an admin Kafka client.

        This includes SASL/SCRAM auth and security mechanisms.

        Returns:
            List of properties to be set.
        """
        client_properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{ADMIN_USER}" password="{self.internal_user_credentials[ADMIN_USER]}";',
            "sasl.mechanism=SCRAM-SHA-512",
            f"security.protocol={self.security_protocol}",  # FIXME: will need changing once multiple listener auth schemes
            f"bootstrap.servers={','.join(self.bootstrap_server)}",
        ]

        if self.charm.tls.enabled:
            client_properties += self.tls_properties

        return client_properties

    @property
    def server_properties(self) -> List[str]:
        """Builds all properties necessary for starting Kafka service.

        This includes charm config, replication, SASL/SCRAM auth and default properties.

        Returns:
            List of properties to be set
        Raises:
            KeyError if inter-broker username and password not set to relation data.
        """
        protocol_map = [listener.protocol_map for listener in self.all_listeners]
        listeners_repr = [listener.listener for listener in self.all_listeners]
        advertised_listeners = [listener.advertised_listener for listener in self.all_listeners]

        properties = (
            [
                f"super.users={self.super_users}",
                f"log.dirs={self.log_dirs}",
                f"listener.security.protocol.map={','.join(protocol_map)}",
                f"listeners={','.join(listeners_repr)}",
                f"advertised.listeners={','.join(advertised_listeners)}",
                f"inter.broker.listener.name={self.internal_listener.name}",
            ]
            + self.config_properties
            + self.scram_properties
            + self.default_replication_properties
            + self.auth_properties
            + DEFAULT_CONFIG_OPTIONS.split("\n")
        )

        if self.charm.tls.enabled:
            properties += self.tls_properties + self.zookeeper_tls_properties
        return properties

    @property
    def config_properties(self) -> List[str]:
        """Configure server properties from config."""
        return [
            f"{conf_key.replace('_', '.')}={str(value)}"
            for conf_key, value in self.charm.config.dict().items()
            if value is not None
        ]

    def set_zk_jaas_config(self) -> None:
        """Writes the ZooKeeper JAAS config using ZooKeeper relation data."""
        jaas_config = f"""
            Client {{
                org.apache.zookeeper.server.auth.DigestLoginModule required
                username="{self.zookeeper_config['username']}"
                password="{self.zookeeper_config['password']}";
            }};
        """
        push(
            container=self.container,
            content=jaas_config,
            path=self.zk_jaas_filepath,
        )

    def set_server_properties(self) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        push(
            content="\n".join(self.server_properties),
            path=self.server_properties_filepath,
            container=self.container,
        )

    def set_client_properties(self) -> None:
        """Writes all client config properties to the `client.properties` path."""
        push(
            content="\n".join(self.client_properties),
            path=self.client_properties_filepath,
            container=self.container,
        )

    def set_kafka_opts(self) -> None:
        """Writes the env-vars needed for SASL/SCRAM auth to `/etc/environment` on the unit."""
        opts_string = " ".join(self.extra_args)
        push(
            content=f"KAFKA_OPTS={opts_string}",
            path="/etc/environment",
            container=self.container,
        )

    def get_host_from_unit(self, unit: Unit) -> str:
        """Builds K8s host address for a given `Unit`.

        Args:
            unit: the desired unit

        Returns:
            String of host address
        """
        broker_id = unit.name.split("/")[1]

        return f"{self.charm.app.name}-{broker_id}.{self.charm.app.name}-endpoints"
