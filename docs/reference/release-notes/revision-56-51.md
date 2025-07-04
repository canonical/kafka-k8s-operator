(reference-release-notes-revision-56-51)=
# Revision 56/51
<sub>Wednesday, February 28, 2024</sub>

Dear community,

We are extremely thrilled and excited to share that Charmed Apache Kafka K8s and Charmed ZooKeeper K8s have now been released as GA. You can find them in [Charmhub](https://charmhub.io/) under the `3/stable` track.

More information are available in the [Canonical website](https://canonical.com/data/kafka), alongside its [documentation](https://canonical.com/data/docs/kafka/k8s).
Also find the full announcement of the release [here](https://canonical.com/blog/charmed-kafka-general-availability) and [here](https://discourse.charmhub.io/t/announcing-general-availability-of-charmed-kafka/13277).
And more importantly, make sure you don't miss out the [webinar](https://www.linkedin.com/events/7161727829259366401/about/) that Raúl Zamora and Rob Gibbon will be holding later today.

Please reach out should you have any question, comment, feedback or information. You can find us here in [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or also on [Discourse](https://discourse.charmhub.io/).

## Features

* Deploying on Kubernetes (tested with MicroK8s)
* Apache ZooKeeper using SASL authentication
* Scaling up/down in one simple Juju command
* Multi-broker support and Highly-Available setups
* Inter-broker authenticated communication
* TLS/SSL support using `tls-certificates` Provider charms (see more [here](https://charmhub.io/topics/security-with-x-509-certificates))
* SASL/SCRAM and mTLS authentication for clients
* DB access outside of Juju using [`data-integrator`](https://charmhub.io/data-integrator)
* Persistent storage support with Juju Storage
* Super-user creation
* Documentation featuring Diàtaxis framework

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) 
and [GitHub](https://github.com/canonical/kafka-k8s-operator/issues) platforms.

[GitHub Releases](https://github.com/canonical/kafka-k8s-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.

## Inside the charms

* Charmed Apache ZooKeeper K8s charm ships the Apache ZooKeeper [3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0), built and supported by Canonical
* Charmed Apache Kafka K8s charm ships the Apache Kafka [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0), built and supported by Canonical
* Charmed Apache ZooKeeper K8s charm is provided with the [charmed-zookeeper rock](https://snapcraft.io/charmed-zookeeper) on the `3-22.04_stable` tag (based on top of a Ubuntu LTS “22.04” base)
* Charmed Apache Kafka K8s charm is provided with the [{spellexception}`charmed-kafka rock`](https://snapcraft.io/charmed-zookeeper) on the `3-22.04_stable` tag (based on top of a Ubuntu LTS “22.04” base)

More information about the artefacts is provided by the following table:

| Artefact               | Track/Series/Tag | Version/Revision/Hash                                                                                           | Code                                                                                                                |
|------------------------|------------------|-----------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| ZooKeeper distribution | `3.x`              | `3.8.2-ubuntu0`                                                                                                   | [{spellexception}`5bb82d`](https://git.launchpad.net/zookeeper-releases/tree/?h=lp-3.8.2&id=5bb82df4ffba910a5b30dd42499921466405f087) |
| Apache Kafka distribution     | `3.x`             | `3.6.0-ubuntu0`                                                                                                   | [424389](https://git.launchpad.net/kafka-releases/tree/?h=lp-3.6.0&id=424389bb8f230beaef4ccb94aca464b5d22ac310)     |
| Charmed ZooKeeper rock | `3-22.04_stable`   | [{spellexception}`sha256:a7a004`](https://github.com/canonical/charmed-zookeeper-rock/pkgs/container/charmed-zookeeper/169796097) | [b56171](https://github.com/canonical/charmed-zookeeper-rock/tree/b5617134c6094f8df6974501be50cd13c6e72e50)         |        
| Zookeeper K8s operator | `3/stable`        | `51`                                                                                                              | [{spellexception}`48fa4f`](https://github.com/canonical/zookeeper-k8s-operator/tree/48fa4f0ff9ccd9e6b881890fa031443d6fb07ae4)         | 
| Charmed Apache Kafka rock     | `3-22.04_stable`   | [{spellexception}`sha256:4b3495`](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka/169796414)         | [66518b](https://github.com/canonical/charmed-kafka-rock/tree/66518b362e73528c8aaec06e331337fbfd0697f1)             |  
| Charmed Apache Kafka K8s operator     | `3/stable`         | `56`                                                                                                              | [{spellexception}`fe1f1c`](https://github.com/canonical/kafka-k8s-operator/tree/fe1f1ce1d8412423e1cccb91b06a96b9622789b1)             |   

## Technical notes

* A Charmed Apache Kafka K8s cluster is secure by default, meaning that when deployed if there are no client charms related to it, external listeners will not be enabled.
* We recommend deploying one `data-integrator` with `extra-user-roles=admin` alongside the Charmed Apache Kafka deployment, in order to enable listeners and also create one user with elevated permission
  to perform administrative tasks. For more information, see the [How-to manage application](how-to-manage-applications) guide.
* The current version of Apache Kafka does not yet support direct integration with Ingress, NodePort or Load Balancer services. We recommend using it for usage within the K8s network.
* The current release has been tested with Juju 2.9.45+ and Juju 3.1+
* In-place upgrade for charms tracking `latest` is not supported, both for Apache ZooKeeper and Apache Kafka charms. Perform data migration to upgrade to a Charmed Apache Kafka cluster managed via a `3/stable` charm.
  For more information on how to perform the migration, see [How-to migrate a cluster](how-to-migrate-a-cluster) guide.
