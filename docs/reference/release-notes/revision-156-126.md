(reference-release-notes-revision-156-126)=
# Revision 156/126
<sub>Wednesday, February 28, 2024</sub>

Dear community,

We are extremely thrilled and excited to share that Charmed Apache Kafka and Charmed Apache ZooKeeper have now been released as GA. You can find them in [charmhub.io](https://charmhub.io/) under the `3/stable` track.

More information is available on the [Canonical website](https://canonical.com/data/kafka), alongside its [documentation](https://canonical.com/data/docs/kafka/iaas).
Also find the full announcement of the release [here](https://canonical.com/blog/charmed-kafka-general-availability) and [here](https://discourse.charmhub.io/t/announcing-general-availability-of-charmed-kafka/13277). 
And more importantly, make sure you don't miss out the [webinar](https://www.linkedin.com/events/7161727829259366401/about/) that Raúl Zamora and Rob Gibbon will be holding later today.

Please reach out should you have any question, comment, feedback or information. You can find us here in [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or also on [Discourse](https://discourse.charmhub.io/).

## Features

* Deploying on VM (tested with LXD, MAAS)
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
and [GitHub](https://github.com/canonical/kafka-operator/issues) platforms.

[GitHub Releases](https://github.com/canonical/kafka-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.

## Inside the charms

* Charmed Apache ZooKeeper charm ships the Apache ZooKeeper [3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0), built and supported by Canonical
* Charmed Apache Kafka charm ships the Apache Kafka [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0), built and supported by Canonical
* Charmed Apache ZooKeeper charm is based on [charmed-zookeeper snap](https://snapcraft.io/charmed-zookeeper) on the `3/stable` (Ubuntu LTS “22.04” - core22-based)
* Charmed Apache Kafka charm is based on [charmed-kafka snap](https://snapcraft.io/charmed-kafka) on the `3/stable` channel (Ubuntu LTS “22.04” - core22-based)
* Principal charms support the latest LTS series “22.04” only.

More information about the artefacts is provided by the following table:

| Artefact               | Track/Series | Version/Revision | Code                                                                                                                |
|------------------------|--------------|------------------|---------------------------------------------------------------------------------------------------------------------|
| Apache ZooKeeper distribution | 3.x          | 3.8.2-ubuntu0    | [5bb82d](https://git.launchpad.net/zookeeper-releases/tree/?h=lp-3.8.2&id=5bb82df4ffba910a5b30dd42499921466405f087) |
| Apache Kafka distribution     | 3.x          | 3.6.0-ubuntu0    | [424389](https://git.launchpad.net/kafka-releases/tree/?h=lp-3.6.0&id=424389bb8f230beaef4ccb94aca464b5d22ac310)     |
| Charmed Apache ZooKeeper snap | 3/stable     | 28               | [9757f4](https://github.com/canonical/charmed-zookeeper-snap/tree/9757f4a2a889981275f8f2a1a87e1c78ae1adb77)         |        
| Charmed Apache ZooKeeper operator     | 3/stable     | 126              | [9ebd9a](https://github.com/canonical/zookeeper-operator/commit/9ebd9a2050e0bd626feb0019222d45f211ca7774)           | 
| Charmed Apache Kafka snap     | 3/stable     | 30               | [c0ce27](https://github.com/canonical/charmed-kafka-snap/tree/c0ce275f70f688e66f10f295456d2b5ff33d4f64)             |  
| Charmed Apache Kafka operator         | 3/stable     | 156              | [01d65c](https://github.com/canonical/kafka-operator/tree/01d65c3444b593d5f18d197a6514421afd3f2bc6)                 |   

## Technical notes

* A Charmed Apache Kafka cluster is secure by default, meaning that when deployed if there are no client charms related to it, external listeners will not be enabled.
* We recommend deploying one `data-integrator` with `extra-user-roles=admin` alongside the Charmed Apache Kafka deployment, in order to enable listeners and also create one user with elevated permission 
  to perform administrative tasks. For more information, see the [How-to manage application](/how-to/manage-applications) guide.
* The current release has been tested with Juju 2.9.45+ and Juju 3.1+
* In-place upgrade for charms tracking `latest` is not supported, both for Charmed Apache ZooKeeper and Charmed Apache Kafka charms. Perform data migration to upgrade to a Charmed Apache Kafka cluster managed via a `3/stable` charm. 
  For more information on how to perform the migration, see [How-to migrate a cluster](/how-to/cluster-replication/migrate-a-cluster) guide.
