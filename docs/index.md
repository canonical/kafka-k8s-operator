# Charmed Kafka K8s Documentation

The Charmed Kafka K8s Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform deployed on top of a [Kubernetes cluster](https://kubernetes.io/). It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

This operator charm comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authentication enabled by default.
- Access control management supported with user-provided ACL lists.

The Kafka K8s Operator uses the latest upstream Kafka binaries released by The Apache Software Foundation that comes with Kafka, made available using the [`ubuntu/kafka` OCI image](https://registry.hub.docker.com/r/ubuntu/kafka) distributed by Canonical.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper K8s Operator](https://github.com/canonical/zookeeper-k8s-operator) for various essential functions.

The Charmed Kafka K8s operator comes in two flavours to deploy and operate Kafka on [physical/virtual machines](https://github.com/canonical/kafka-operator) and [Kubernetes](https://github.com/canonical/kafka-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed Kafka K8s Operator meets the need of deploying Kafka in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of Kafka in production at scale in a reliable way.

### License

The Charmed Kafka K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-operator/blob/main/LICENSE) for more information.

## Project and community

Charmed Kafka K8s is an official distribution of Apache Kafka. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka-k8s)
- [Contribute](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-k8s-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us](/t/charmed-kafka-k8s-documentation-reference-contacts/13206) for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/charmed-kafka-k8s-tutorial-overview/11945)</br>  Get started - a hands-on introduction to using Charmed Kafka K8s operator for new users </br> |  [How-to guides](/t/charmed-kafka-k8s-how-to-manage-units/10295) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/kafka-k8s/actions?channel=3/stable) </br> Technical information - specifications, APIs, architecture | [Explanation]() </br> Concepts - discussion and clarification of key topics  |
