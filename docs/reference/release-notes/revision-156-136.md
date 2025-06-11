(reference-release-notes-revision-156-136)=
# Revision 156/136

# Revision 156/136
<sub>Thursday, July 4, 2024</sub>

Dear community,

We are glad to report that we have just released a new updated version for Charmed Apache ZooKeeper on the `3/stable` channel, upgrading its revision from 126 to 136. 
The release of a new version was promoted by the need of backporting some features that 
should provide increased robustness and resilience during operation as well as smaller workload upgrades and fixes. See the technical notes for further information.

Please reach out should you have any question, comment, feedback or information. You can find us here in [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or also on [Discourse](https://discourse.charmhub.io/).

## Features

* [DPE-3726] Workload upgrade to 3.8.4-ubuntu0

## Bug fixes

* [DPE-4183] (backport) fix: only handle quorum removal on relation-departed
* [DPE-4362] (backport) add alive check fix

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) 
and [GitHub](https://github.com/canonical/kafka-operator/issues) platforms.

[GitHub Releases](https://github.com/canonical/kafka-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.

## Inside the charms

* Charmed Apache ZooKeeper charm ships the ZooKeeper [3.8.4-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.4-ubuntu0), built and supported by Canonical
* Charmed Apache Kafka charm ships the Apache Kafka [3.6.0-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.0-ubuntu0), built and supported by Canonical
* Charmed Apache ZooKeeper charm is based on [charmed-zookeeper snap](https://snapcraft.io/charmed-zookeeper) on the `3/stable` (Ubuntu LTS “22.04” - core22-based)
* Charmed Apache Kafka charm is based on [charmed-kafka snap](https://snapcraft.io/charmed-kafka) on the `3/stable` channel (Ubuntu LTS “22.04” - core22-based)
* Principal charms support the latest LTS series “22.04” only.

More information about the artefacts is provided by the following table:

| Artefact               | Track/Series | Version/Revision | Code                                                                                                                |
|------------------------|--------------|------------------|---------------------------------------------------------------------------------------------------------------------|
| Apache ZooKeeper distribution | 3.x          | 3.8.4-ubuntu0    | [78499c](https://git.launchpad.net/zookeeper-releases/tree/?h=lp-3.8.4&id=78499c9f4d4610f9fb963afdad1ffd1aab2a96b8) |
| Apache Kafka distribution     | 3.x          | 3.6.0-ubuntu0    | [424389](https://git.launchpad.net/kafka-releases/tree/?h=lp-3.6.0&id=424389bb8f230beaef4ccb94aca464b5d22ac310)     |
| Charmed Apache ZooKeeper snap | 3/stable     | 30               | [d85fed](https://github.com/canonical/charmed-zookeeper-snap/tree/d85fed4c2f83d99dbc028ff10c2e38915b6cdf04)         |        
| Charmed Apache ZooKeeper operator     | 3/stable     | 136              | [0b7d66](https://github.com/canonical/zookeeper-operator/tree/0b7d66170d80e23804032034119a419f174bb965)             | 
| Charmed Apache Kafka snap     | 3/stable     | 30               | [c0ce27](https://github.com/canonical/charmed-kafka-snap/tree/c0ce275f70f688e66f10f295456d2b5ff33d4f64)             |  
| Charmed Apache Kafka operator         | 3/stable     | 156              | [01d65c](https://github.com/canonical/kafka-operator/tree/01d65c3444b593d5f18d197a6514421afd3f2bc6)                 |   

## Technical notes

* Rev126 on Charmed Apache ZooKeeper was observed to sporadically trigger Apache ZooKeeper reconfiguration of the clusters by removing all servers but the Juju leader from the Apache ZooKeeper quorum. This leads to a 
  non-highly available cluster, that it is however still up and running. 
  The reconfiguration generally resulted from some glitch and connection drop with the Juju controller that resulted in transient inconsistent 
  databag of juju events. This was once observed during a controller upgrade  (see reported [bug](https://bugs.launchpad.net/juju/+bug/2053055) on Juju), but its occurrence is not limited to it. 
  The current revision provides more robust logic (ticket [DPE-4183](https://warthogs.atlassian.net/browse/DPE-4183)) to avoid dynamic reconfiguration in such cases.  
* Upgrades from previous stable versions can be done with the standard upgrading process, as outlined in the [documentation](/how-to/upgrade)

