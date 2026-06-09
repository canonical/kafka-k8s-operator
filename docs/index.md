---
myst:
  html_meta:
    description: "Complete documentation for Charmed Apache Kafka K8s - deploy, manage, and scale Apache Kafka clusters on Kubernetes."
---

(index)=
# Charmed Apache Kafka K8s documentation

Charmed Apache Kafka K8s is an open-source operator, packaged as a
[Juju charm](https://documentation.ubuntu.com/juju/latest/reference/charm/),
that simplifies the deployment, scaling, and management of
[Apache Kafka](https://kafka.apache.org) clusters on Kubernetes
including AKS, EKS, and custom K8s environments.

```{note}
This is a **Kubernetes** operator.
To deploy on IAAS/VM, see [Charmed Apache Kafka operator](https://documentation.ubuntu.com/charmed-kafka/4/).
```

The charm automates Apache Kafka operations from
[Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/)
with capabilities such as replication, TLS encryption, password rotation,
application integration, and monitoring.

## In this documentation

| | |
|---|---|
| **Getting started** | [Introduction](tutorial-introduction) • [Environment setup](tutorial-environment) • [Requirements](reference-requirements) |
| **Deployment** | [Deploy](how-to-deploy-index) • [Juju CLI](how-to-deploy-deploy-anywhere) • [AKS](how-to-deploy-on-aks) • [EKS](how-to-deploy-on-eks) |
| **Operations** | [Connections management](how-to-client-connections) • [Unit management](how-to-manage-units) • [Monitoring](how-to-monitoring) • [Listeners](reference-broker-listeners) • [Statuses](reference-statuses) |
| **Maintenance** | [Version upgrade](how-to-upgrade) • [Migration](how-to-cluster-migration) • [Replication](how-to-cluster-replication) • [MirrorMaker](explanation-mirrormaker2-0) • [Backups](explanation-backups) |
| **Security** | [Overview](explanation-security) • [Enable encryption](how-to-tls-encryption) • [mTLS](how-to-create-mtls-client-credentials) • [Cryptography](explanation-cryptography) |
| **Extensions** | [Kafka Connect](how-to-use-kafka-connect) • [Schema registry](how-to-schemas-serialisation) • [Kafka UI](how-to-kafka-ui) |
| **Internals** | [File paths](reference-file-system-paths) • [External K8s connection](how-to-external-k8s-connection) • [Release notes](reference-release-notes-index) |

## How the documentation is organised

This documentation uses the [Diátaxis documentation structure](https://diataxis.fr/):

- The [Tutorial](tutorial-introduction) walks you through deploying your first Charmed Apache Kafka K8s cluster from scratch, step by step.
- [How-to guides](how-to-index) help you solve specific operational tasks such as enabling TLS, connecting clients, or scaling brokers.
- [Reference](reference-index) lets you look up configuration options, status codes, file paths, and system requirements.
- [Explanation](explanation-index) helps you understand the design decisions behind security, replication, and integration architecture.

## Project and community

Charmed Apache Kafka K8s is part of the [Juju](https://juju.is/) ecosystem of open-source,
self-driving deployment tools. It can be integrated with multiple other Juju charms,
also available on [Charmhub](https://charmhub.io/).

It's an open-source project developed and supported by [Canonical](https://canonical.com/)
that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-k8s-operator/issues/new)
- Explore [Canonical's open-source data platform](https://canonical.com/data)
- [Contact us](reference-contact) for all further questions

## License and trademarks

[Apache Kafka](https://kafka.apache.org) is a free, open-source software project
by the Apache Software Foundation.
Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks
or trademarks of the Apache Software Foundation in the United States and/or other countries.

The Charmed Apache Kafka K8s Operator is free software, distributed under the Apache Software License,
version 2.0.
See [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) for more information.

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Home <self>
tutorial/index
how-to/index
reference/index
explanation/index
```
