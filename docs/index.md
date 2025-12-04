(index)=

```{note}
This is a **Kubernetes** operator.
To deploy on IAAS/VM, see [Charmed Apache Kafka operator](https://documentation.ubuntu.com/charmed-kafka/4/).
```

# Charmed Apache Kafka K8s documentation

Charmed Apache Kafka K8s is an open-source software operator, packaged as a
[Juju charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/),
that simplifies the deployment, scaling, and management of Apache Kafka clusters
on Kubernetes.

[Apache Kafka](https://kafka.apache.org) is a free, open-source software project
by the Apache Software Foundation.

The charm helps ops teams and administrators automate Apache Kafka operations from
[Day 0 to Day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/)
with additional capabilities, such as: replication, TLS encryption, password rotation,
easy-to-use application integration, and monitoring.

## In this documentation

| | |
|--|--|
|  [Tutorial](tutorial-introduction)</br>  Learn how to deploy, configure, and use the charm with our step-by-step guidance. Get started from [step one](tutorial-environment). </br> |  [How-to guides](how-to-index) </br> Practical instructions for key tasks, like [deploy](how-to-deploy-index) on different platforms, [manage](how-to-manage-units) Juju units, [Monitor](how-to-monitoring-enable-monitoring) metrics, use [Kafka Connect](how-to-use-kafka-connect). |
| [Reference](reference-index) </br> Technical information, for example: charm's [actions](https://charmhub.io/kafka-k8s/actions?channel=4/edge), [configuration parameters](https://charmhub.io/kafka-k8s/configurations?channel=4/edge), [libraries](https://charmhub.io/kafka-k8s/libraries/kafka?channel=4/edge), [statuses](reference-statuses), as well as [requirements](reference-requirements), and [file system paths](reference-file-system-paths). | [Explanation](explanation-index) </br> Explore and grow your understanding of key topics, such as: [security](explanation-security), [cryptography](explanation-cryptography), and [MirrorMaker usage](explanation-mirrormaker2-0). |

## Project and community

Charmed Apache Kafka K8s is a distribution of Apache Kafka. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/kafka)
- [Contribute](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/kafka-operator/issues/new)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contact us](reference-contact) for all further questions

Apache®, Apache Kafka, Kafka®, and the Apache Kafka logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.

## License

The Charmed Apache Kafka K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) for more information.

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
