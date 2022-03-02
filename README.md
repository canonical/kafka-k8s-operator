<!-- Copyright 2022 Canonical Ltd.
See LICENSE file for licensing details. -->

# Kafka K8s Operator

[![code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black/tree/main)
[![Run-Tests](https://github.com/charmed-osm/kafka-k8s-operator/actions/workflows/ci.yaml/badge.svg)](https://github.com/charmed-osm/kafka-k8s-operator/actions/workflows/ci.yaml)

[![Kafka K8s](https://charmhub.io/kafka-k8s/badge.svg)](https://charmhub.io/kafka-k8s)

## Description

Apache Kafka is an open-source distributed event streaming platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.

This repository contains a Charm Operator for deploying the Kafka in a Kubernetes cluster.

<!-- ## Tutorials
-  -->

## How-to guides

### Deploy Kafka

The Kafka K8s Operator may be deployed using the Juju command line as in

```shell
$ juju add-model kafka-k8s
$ juju deploy kafka-k8s
$ juju deploy zookeeper-k8s
$ juju relate kafka-k8s zookeeper-k8s
```

### Scale Kafka

Scale Kafka by executing the following command

```shell
$ juju scale-application kafka-k8s 3
```

## Integration with Canonical Observability Stack

This exporter can very easily be integrated with Canonical Observability Stack (COS).

To do so, after following the steps from the previous section, execute the following commands:

```shell
$ juju deploy cos-lite --channel beta --trust
$ juju upgrade-charm grafana --channel edge
$ juju relate grafana kafka-k8s
$ juju relate prometheus kafka-k8s
```

Wait until everything is deployed:
```shell
$ watch -c juju status --color
Model      Controller          Cloud/Region        Version  SLA          Timestamp
kafka-k8s  microk8s-localhost  microk8s/localhost  2.9.25   unsupported  15:33:09+01:00

App            Version  Status   Scale  Charm             Store     Channel  Rev  OS          Address          Message
alertmanager            waiting      1  alertmanager-k8s  charmhub  beta       9  kubernetes  10.152.183.185
grafana                 active       1  grafana-k8s       charmhub  edge      28  kubernetes  10.152.183.247
kafka-k8s               active       1  kafka-k8s         charmhub  edge       0  kubernetes  10.152.183.25
loki                    active       1  loki-k8s          charmhub  beta      13  kubernetes  10.152.183.32
prometheus              active       1  prometheus-k8s    charmhub  beta      19  kubernetes  10.152.183.211
zookeeper-k8s           active       1  zookeeper-k8s     charmhub  edge      10  kubernetes  10.152.183.153

Unit              Workload     Agent  Address       Ports  Message
alertmanager/0*   active       idle   10.1.245.86
grafana/0*        active       idle   10.1.245.101
kafka-k8s/0*      active       idle   10.1.245.68
loki/0*           active       idle   10.1.245.107
prometheus/0*     active       idle   10.1.245.82
zookeeper-k8s/0*  active       idle   10.1.245.81
```

To see the metrics, you can get the grafana admin password as follows:

```shell
$ juju run-action grafana/0 get-admin-password --wait
unit-grafana-0:
  UnitId: grafana/0
  id: "2"
  results:
    admin-password: *************
  status: completed
  timing:
    completed: 2022-03-02 14:31:49 +0000 UTC
    enqueued: 2022-03-02 14:31:39 +0000 UTC
    started: 2022-03-02 14:31:48 +0000 UTC
```

Open your browser and go to the Grafana dashboard at port 3000.

## Reference

- [Kafka documentation](https://kafka.apache.org/documentation/)
- [OCI image](https://hub.docker.com/r/confluentinc/cp-kafka): currently using tag `7.0.1`.

## Explanation

- [What is Apache Kafka?](https://kafka.apache.org/intro)

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
`CONTRIBUTING.md` for developer guidance.
