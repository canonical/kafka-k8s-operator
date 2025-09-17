#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Balancer."""

import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

import requests
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

from core.models import JSON, BrokerCapacities, BrokerCapacity
from literals import BALANCER, BALANCER_TOPICS, MODE_FULL, STORAGE
from managers.config import BalancerConfigManager

if TYPE_CHECKING:
    from charm import KafkaCharm
    from events.balancer import BalancerOperator
    from events.broker import BrokerOperator


logger = logging.getLogger(__name__)


class CruiseControlClient:
    """Client wrapper for CruiseControl."""

    def __init__(self, username: str, password: str, host: str = "localhost", port: int = 9090):
        self.username = username
        self.password = password
        self.address = f"http://{host}:{port}/kafkacruisecontrol"
        self.default_params = {"json": "True"}

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        """CruiseControl GET request.

        Args:
            endpoint: the REST API endpoint to GET.
                e.g `state`, `load`, `user_tasks`
            **kwargs: any REST API query parameters provided by that endpoint
        """
        r = requests.get(
            url=f"{self.address}/{endpoint}",
            auth=(self.username, self.password),
            params=kwargs | self.default_params,
        )
        logger.debug(f"GET {endpoint} - {vars(r)}")

        return r

    def post(self, endpoint: str, dryrun: bool = False, **kwargs) -> requests.Response:
        """CruiseControl POST request.

        Args:
            endpoint: the REST API endpoint to POST.
                e.g `add_broker`, `demote_broker`, `rebalance`
            dryrun: flag to decide whether to return only proposals (True), or execute (False)
            **kwargs: any REST API query parameters provided by that endpoint
        """
        payload = {"dryrun": str(dryrun)}
        if (brokerid := kwargs.get("brokerid", None)) is not None:
            payload |= {"brokerid": brokerid}

        r = requests.post(
            url=f"{self.address}/{endpoint}",
            auth=(self.username, self.password),
            params=kwargs | payload | self.default_params,
        )
        logger.debug(f"POST {endpoint} - {vars(r)}")

        return r

    def get_task_status(self, user_task_id: str) -> str:
        """Gets the task status from the `user_tasks` API endpoint for the provided `user_task_id`.

        Returns:
            The status of the task
                e.g 'Completed', 'CompletedWithError', 'Active'
        """
        for task in self.get(endpoint="user_tasks").json().get("userTasks"):
            if task.get("UserTaskId", "") == user_task_id:
                return task.get("Status", "")

        return ""

    @property
    @retry(
        wait=wait_fixed(5),
        stop=stop_after_attempt(3),
        retry=retry_if_result(lambda res: res is False),
        retry_error_callback=lambda _: False,
    )
    def monitoring(self) -> bool:
        """Flag to confirm that the CruiseControl Monitor is up-and-running."""
        # Retry-able because CC oftentimes goes into "SAMPLING"
        return (
            self.get(endpoint="state", verbose="True")
            .json()
            .get("MonitorState", {})
            .get("state", "")
            == "RUNNING"
        )

    @property
    def executing(self) -> bool:
        """Flag to confirm that the CruiseControl Executor is currently executing a task."""
        return (
            self.get(endpoint="state", verbose="True")
            .json()
            .get("ExecutorState", {})
            .get("state", "")
            != "NO_TASK_IN_PROGRESS"
        )

    @property
    def ready(self) -> bool:
        """Flag to confirm that the CruiseControl Analyzer is ready to generate proposals."""
        monitor_state = self.get(endpoint="state", verbose="True").json().get("MonitorState", "")
        return all(
            [
                monitor_state.get("numMonitoredWindows", 0),
                monitor_state.get("numValidPartitions", 0),
            ]
        )


class BalancerManager:
    """Manager for handling Balancer."""

    def __init__(self, dependent: "BrokerOperator | BalancerOperator") -> None:
        self.dependent = dependent
        self.charm: "KafkaCharm" = dependent.charm
        self.config_manager = cast(BalancerConfigManager, dependent.config_manager)

    @property
    def cruise_control(self) -> CruiseControlClient:
        """Client for the CruiseControl REST API."""
        return CruiseControlClient(
            username=self.charm.state.peer_cluster.balancer_username,
            password=self.charm.state.peer_cluster.balancer_password,
        )

    @property
    def cores(self) -> str:
        """Gets the total number of CPU cores for the machine."""
        return self.dependent.workload.exec(["nproc", "--all"]).strip()

    @property
    def storages(self) -> str:
        """A string of JSON containing key storage-path, value storage size for all unit storages."""
        return json.dumps(
            {
                str(storage.location): str(
                    self._get_storage_size(path=storage.location.absolute().as_posix())
                )
                for storage in self.charm.model.storages[STORAGE]
            }
        )

    def create_internal_topics(self) -> None:
        """Create Cruise Control topics."""
        bootstrap_servers = self.charm.state.peer_cluster.broker_uris
        property_file = f'{BALANCER.paths["CONF"]}/cruisecontrol.properties'

        for topic in BALANCER_TOPICS:
            if topic not in self.dependent.workload.run_bin_command(
                "topics",
                [
                    "--list",
                    "--bootstrap-server",
                    bootstrap_servers,
                    "--command-config",
                    property_file,
                ],
            ):
                self.dependent.workload.run_bin_command(
                    "topics",
                    [
                        "--create",
                        "--topic",
                        topic,
                        "--bootstrap-server",
                        bootstrap_servers,
                        "--command-config",
                        property_file,
                    ],
                )
                logger.info(f"Created topic {topic}")

    def rebalance(
        self, mode: str, dryrun: bool = True, brokerid: int | None = None, **kwargs
    ) -> tuple[requests.Response, str]:
        """Triggers a full Kafka cluster partition rebalance.

        Returns:
            Tuple of requests.Response and string of the CruiseControl User-Task-ID for the rebalance
        """
        mode = f"{mode}_broker" if mode != MODE_FULL else "rebalance"
        rebalance_request = self.cruise_control.post(
            endpoint=mode, dryrun=dryrun, brokerid=brokerid
        )

        return (rebalance_request, rebalance_request.headers.get("User-Task-ID", ""))

    def wait_for_task(self, user_task_id: str) -> None:
        """Waits for the provided User-Task-ID to complete execution."""
        # block entire charm event handling while rebalance in progress
        while (
            "Completed" not in self.cruise_control.get_task_status(user_task_id=user_task_id)
            or self.cruise_control.executing
        ):
            logger.info(f"Waiting for task execution to finish for {user_task_id=}...")
            time.sleep(10)  # sleep needed as CC API rejects too many requests within a short time

    def _get_storage_size(self, path: str) -> int:
        """Gets the total storage volume of a mounted filepath, in KB."""
        return int(
            self.dependent.workload.exec(["bash", "-c", f"df --output=size {path} | sed 1d"])
        )

    def _build_new_key(self, nested_key: str, nested_value: JSON) -> dict[str, JSON]:
        """Builds a nested key:value pair for JSON lists from the output of a rebalance proposal.

        The keys where this is needed are `brokers`, `hosts` and `goalSummary` goals. Turns this:
        ```
        "loadAfterOptimization": {
            "brokers": [
              {
                "BrokerState": "ALIVE",
                "Broker": 0,
              },
              {
                "BrokerState": "ALIVE",
                "Broker": 1,
              },
        }
        ```

        into this:

        ```
        "loadAfterOptimization": {
            "brokers.0":
              {
                "brokerstate": "ALIVE",
                "broker": 0,
              },
            "brokers.1":
              {
                "brokerstate": "ALIVE",
                "broker": 1,
              },
        }
        ```

        """
        mapping = {"brokers": "Broker", "hosts": "Host", "goalSummary": "goal"}
        label_key = mapping.get(nested_key, "")

        if not (label_key and isinstance(nested_value, list)):
            return {}

        nested_dict = {}
        for item in nested_value:
            if not isinstance(item, dict):
                continue

            label_value = item.get(label_key)
            clean_label_value = self._sanitise_key(label_value)
            new_key = f"{nested_key}.{clean_label_value}".lower()

            nested_dict[new_key] = self.clean_results(item)  # continue recursing

        return nested_dict

    def _sanitise_key(self, key: Any) -> Any:
        """Sanitises keys for passing as Juju Actions results.

        When calling `event.set_results(dict)`, the passed dict has some limitations:
            - All keys must be lower-case with no special characters, must be similar to 'key', 'some-key2', or 'some.key'
            - Non-string types will be forced in to a 'str()' shape
        """
        if not isinstance(key, str):
            return key

        return key.replace(".", "-").replace("_", "-").lower()

    def clean_results(self, value: JSON) -> JSON:
        """Recursively cleans JSON responses returned from the CruiseControl API, for passing to Action results."""
        if isinstance(value, list):
            return [self.clean_results(item) for item in value]

        elif isinstance(value, dict):
            nested_dict = {}
            for nested_key, nested_value in value.items():
                if new_key := self._build_new_key(nested_key, nested_value):
                    nested_dict.update(new_key)
                else:
                    nested_dict[self._sanitise_key(nested_key)] = self.clean_results(nested_value)

            return nested_dict

        else:
            return value

    def compare_capacities_files(
        self, old: BrokerCapacities, new: BrokerCapacities
    ) -> tuple[list[BrokerCapacity], list[BrokerCapacity]]:
        """Compare two capacities files to get the added/deleted brokers.

        This method keeps the diff simple: a change in a nested field is a complete change of a broker.
        """
        if not old:
            return [], new.get("brokerCapacities", [])

        if not new:
            return new.get("brokerCapacities", []), []

        # we keep it simple at the most macro level, no need to get the exact key change
        deleted = [
            broker_capacity
            for broker_capacity in old.get("brokerCapacities", [])
            if broker_capacity not in new.get("brokerCapacities", [])
        ]

        added = [
            broker_capacity
            for broker_capacity in new.get("brokerCapacities", [])
            if broker_capacity not in old.get("brokerCapacities", [])
        ]

        return deleted, added

    def config_change_detected(self) -> bool:
        """Check if written balancer config is different from the current state."""
        changed_map = [
            (
                "properties",
                self.dependent.workload.paths.cruise_control_properties,
                self.config_manager.cruise_control_properties,
            ),
        ]

        content_changed = False
        for kind, path, state_content in changed_map:
            file_content = self.dependent.workload.read(path)
            if set(file_content) ^ set(state_content):
                logger.info(
                    (
                        f"Balancer {self.charm.unit.name.split('/')[1]} updating config - "
                        f"OLD {kind.upper()} = {set(map(str.strip, file_content)) - set(map(str.strip, state_content))}, "
                        f"NEW {kind.upper()} = {set(map(str.strip, state_content)) - set(map(str.strip, file_content))}"
                    )
                )
                content_changed = True

        # On k8s, adding/removing a broker does not change the bootstrap server property if exposed by nodeport
        broker_capacities = self.charm.state.peer_cluster.broker_capacities
        if (
            file_content := json.loads(
                "".join(
                    self.dependent.workload.read(self.dependent.workload.paths.capacity_jbod_json)
                )
            )
        ) != broker_capacities:
            deleted, added = self.compare_capacities_files(file_content, broker_capacities)
            logger.info(
                f"Balancer {self.charm.unit.name.split('/')[1]} updating capacity config - "
                f"ADDED {added}, "
                f"DELETED {deleted}"
            )

            content_changed = True

        return content_changed
