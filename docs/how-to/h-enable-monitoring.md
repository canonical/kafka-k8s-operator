# Enable monitoring

Both Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s come with the [JMX exporter](https://github.com/prometheus/jmx_exporter/).
The metrics can be queried by accessing the `http://<kafka-unit-ip>:9101/metrics` and `http://<zookeeper-unit-ip>:9998/metrics` endpoints, respectively.

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

## Prerequisites

* A deployed [Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s bundle](/t/charmed-kafka-k8s-documentation-how-to-deploy/13266)
* A deployed [`cos-lite` bundle in a Kubernetes environment](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)

## Offer interfaces via the COS controller

First, we will switch to the COS K8s environment and offer COS interfaces to be cross-model integrated with the Charmed Apache Kafka K8s model.

To switch to the Kubernetes controller for the COS model, run

```shell
juju switch <k8s_cos_controller>:<cos_model_name>
```
To offer the COS interfaces, run 

```shell
juju offer grafana:grafana-dashboard grafana-dashboards
juju offer loki:logging loki-logging
juju offer prometheus:receive-remote-write prometheus-receive-remote-write
```

## Consume offers via the Apache Kafka model

Next, we will switch to the Charmed Apache Kafka K8s model, find offers, and consume them.

We are currently on the Kubernetes controller for the COS model. To switch to the Apache Kafka model, run

```shell
juju switch <k8s_db_controller>:<kafka_model_name>
```
To find offers, run the following command (make sure not to miss the ":" at the end!):

```shell
juju find-offers <k8s_cos_controller>: 
```

The output should be similar to the sample below, where `k8s` is the K8s controller name and `cos` is the model where `cos-lite` has been deployed:

```shell
Store     URL                                        Access  Interfaces
k8s  admin/cos.grafana-dashboards               admin   grafana_dashboard:grafana-dashboard
k8s  admin/cos.loki-logging                     admin   loki_push_api:logging
k8s  admin/cos.prometheus-receive-remote-write  admin   prometheus_remote_write:receive-remote-write
...
```

To consume offers to be reachable in the current model, run

```shell
juju consume <k8s_cos_controller>:admin/<cos_model_name>.grafana-dashboards
juju consume <k8s_cos_controller>:admin/<cos_model_name>.loki-logging
juju consume <k8s_cos_controller>:admin/<cos_model_name>.prometheus-receive-remote-write
```
## Deploy and integrate Grafana

First, deploy [grafana-agent-k8s](https://charmhub.io/grafana-agent-k8s): 

```shell
juju deploy grafana-agent-k8s --trust
```
Then, integrate `grafana-agent-k8s` with consumed COS offers:

```shell
juju integrate grafana-agent-k8s grafana-dashboards
juju integrate grafana-agent-k8s loki-logging
juju integrate grafana-agent-k8s prometheus-receive-remote-write
```
Finally, integrate (previously known as "[relate](https://juju.is/docs/juju/integration)") it with Charmed Apache Kafka K8s

```shell
juju integrate grafana-agent-k8s kafka-k8s:grafana-dashboard
juju integrate grafana-agent-k8s kafka-k8s:logging
juju integrate grafana-agent-k8s kafka-k8s:metrics-endpoint
```

and Charmed Apache ZooKeeper K8s

```shell
juju integrate grafana-agent-k8s zookeeper-k8s:grafana-dashboard
juju integrate grafana-agent-k8s zookeeper-k8s:logging
juju integrate grafana-agent-k8s zookeeper-k8s:metrics-endpoint
```

Wait for all components to settle down on a `active/idle` state on both 
models, e.g. `<kafka_model_name>` and `<cos_model_name>`.

After this is complete, the monitoring COS stack should be up and running and ready to be used. 

### Connect Grafana web interface

To connect to the Grafana web interface, follow the [Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s?_ga=2.201254254.1948444620.1704703837-757109492.1701777558#heading--browse-dashboards) section of the MicroK8s "Getting started" guide.
```shell
juju run grafana/leader get-admin-password --model <k8s_cos_controller>:<cos_model_name>
```

## Tune server logging level

To tune the level of the server logs for Apache Kafka and Apache ZooKeeper, configure the `log-level` and `log_level` properties accordingly.

### Apache Kafka 

```
juju config kafka log_level=<LOG_LEVEL>
```

Possible values are `ERROR`, `WARNING`, `INFO`, `DEBUG`.

### Apache ZooKeeper

```
juju config kafka log-level=<LOG_LEVEL>
```

Possible values are `ERROR`, `WARNING`, `INFO`, `DEBUG`.