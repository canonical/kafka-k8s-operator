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

### How to deploy Kafka

The Kafka K8s Operator may be deployed using the Juju command line as in

```shell
$ juju add-model kafka-k8s
$ juju deploy kafka-k8s
$ juju deploy zookeeper-k8s
$ juju relate kafka-k8s zookeeper-k8s
```

### How to scale Kafka

Scale Kafka by executing the following command

```shell
$ juju scale-application kafka-k8s 3
```

## Reference

- [Kafka documentation](https://kafka.apache.org/documentation/)
- [OCI image](https://hub.docker.com/r/confluentinc/cp-kafka): currently using tag `7.0.1`.

## Explanation

- [What is Apache Kafka?](https://kafka.apache.org/intro)

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
`CONTRIBUTING.md` for developer guidance.
