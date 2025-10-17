(reference-release-notes-revision-195-149)=
# Revision 195/149
<sub>Wed, Dec 18th, 2024</sub>

Dear community,

We are pleased to report that we have just released a new updated version for the Charmed Apache Kafka bundles on the `3/stable` channel, 
upgrading Charmed Apache ZooKeeper revision from 136 to 149, and Charmed Apache Kafka from 156 to 195.

The new release comes with a number of new features from the charms, from Juju secrets support, OAuth/OIDC authentication support, various improvements in the UI/UX and dependencies upgrades.  

Please reach out should you have any question, comment, feedback or information. You can find us here in [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or also on [Discourse](https://discourse.charmhub.io/).

## Charmed Apache Kafka bundle

New features and bug fixes in the Charmed Apache Kafka bundle:

### Features

* [DPE-2285] Refer to Charmhub space from GitHub (#200)
* [DPE-3333] Add integration test for broken tls (#188)
* [DPE-3721] chore: use tools-log4j.properties for run_bin_command (#201)
* [DPE-3735] Integration of custom alerting rules and dashboards (#180)
* [DPE-3780] Set workload version in install hook (#182)
* [DPE-3857] Test consistency between workload and metadata versions (#186)
* [DPE-3926] Enforce zookeeper client interface (#196)
* [DPE-3928] feat: secrets integration (#189)
* [DPE-5702] chore: Active Controllers alert set to == 0 (#252)
* [CSS-6503] Add OAuth support for non-charmed external clients (#168)
* [DPE-5757] Add `extra-listeners` configuration option (#269)

### Bug fixes

* [DPE-3880] Remove instance field from Grafana dashboard (#191) 
* [DPE-3880] Remove all instances of $job variable in dashboard (#181)
* [DPE-3900] Remove APT references (#183)
* [DPE-3932] Fix unsupported character on matrix channel (#187)
* [DPE-4133] Do not change permissions on existing folders when reusing storage (#195)
* [DPE-4362] fix: alive, restart and alive handling (#202)
* [DPE-5757] fix: ensure certs are refreshed on SANs DNS changes (#276)

### Other changes

* [MISC] Test on juju 3.4 (#190)
* [MISC] Update package dependencies
* [DPE-3588] Release documentation update  (#175)
* [MISC] CI improvements (#209)
* [DPE-3214] Release 3.6.1 (#179)
* [DPE-5565] Upgrade data platform libs to v38
* [discourse-gatekeeper] Migrate charm docs (#210, #203, #198, #194, #192)
* [DPE-3932] Update information in metadata.yaml

## Charmed Apache ZooKeeper bundle

New features and bug fixes in the Charmed Apache ZooKeeper bundle:

### Features

* [DPE-2285] Refer to Charmhub space from GitHub (#143)
* [DPE-2597] Re use existing storage (#138)
* [DPE-3737] Implement ZK client interface (#142)
* [DPE-3782] Set workload version in install and configure hooks (#130)
* [DPE-3857] Test consistency between workload and metadata versions (#136)
* [DPE-3869] Secrets in ZK (#129)
* [DPE-5626] chore: update ZooKeeper up alerting (#166)

### Bug fixes

* [DPE-3880] Remove job variable from dashboard (#134)
* [DPE-3900] Remove APT references (#131)
* [DPE-3932] Fix unsupported character on matrix channel (#133, #135)
* [DPE-4183] fix: only handle quorum removal on relation-departed (#146)
* [DPE-4362] fix: alive, restart and alive handling (#145)

### Other changes

* [DPE-5565] Stable release upgrade
* chore: bump {spellexception}`dp_libs` version (#147)
* [MISC] General update dependencies (#144)
* [MISC] Update CI to Juju 3.4 (#137)
* [DPE-3932] Update information in metadata.yaml
* [MISC] Update cryptography to 42.0.5

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) 
and [GitHub](https://github.com/canonical/kafka-operator/issues) platforms.

## Inside the charms

Contents of the Charmed Apache Kafka and Charmed Apache ZooKeeper include:

* Charmed Apache ZooKeeper is based on the [charmed-zookeeper snap](https://snapcraft.io/charmed-zookeeper) of the `3/stable` channel (Ubuntu LTS “22.04” - core22-based) that ships the Apache ZooKeeper [3.8.4-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.4-ubuntu0), built and supported by Canonical
* Charmed Apache Kafka is based on the [{spellexception}`charmed-kafka` snap](https://snapcraft.io/charmed-kafka) of the `3/stable` channel (Ubuntu LTS “22.04” - core22-based) that ships the Apache Kafka [3.6.1-ubuntu0](https://launchpad.net/kafka-releases/3.x/3.6.1-ubuntu0), built and supported by Canonical
* Principal charms support the latest LTS series “22.04” only.

More information about the artefacts are provided by the following table:

| Artefact                          | Track/Series | Version/Revision | Code                                                                                                                |
|-----------------------------------|--------------|------------------|---------------------------------------------------------------------------------------------------------------------|
| Apache ZooKeeper distribution     | `3.x`          | `3.8.4-ubuntu0`    | [78499c](https://git.launchpad.net/zookeeper-releases/tree/?h=lp-3.8.4&id=78499c9f4d4610f9fb963afdad1ffd1aab2a96b8) |
| Apache Kafka distribution         | `3.x`          | `3.6.1-ubuntu0`    | [db44db](https://git.launchpad.net/kafka-releases/tree/?h=lp-3.6.1&id=db44db1ebf870854dddfc3be0187a976b997d4dc)     |
| Charmed Apache ZooKeeper snap     | `3/stable`     | `34`               | [13f3c6](https://github.com/canonical/charmed-zookeeper-snap/tree/13f3c620658fdc55b7d6745b81c7b5a00e042e10)         |        
| Charmed Apache ZooKeeper operator | `3/stable`     | `149`              | [40576c](https://github.com/canonical/zookeeper-operator/commit/40576c1c87badd1e2352afc013ed0754808ef44c)           | 
| Charmed Apache Kafka snap         | `3/stable`     | `37`               | [c266f9](https://github.com/canonical/charmed-kafka-snap/tree/c266f9cd283408d2106d4682b67661205a12ea7f)             |  
| Charmed Apache Kafka operator     | `3/stable`     | `195`              | [{spellexception}`7948df`](https://github.com/canonical/kafka-operator/pull/241/commits/7948dfbbfaaa53fccc88beaa90f80de1e70beaa9)                 |   

## Technical notes

* [GitHub Releases](https://github.com/canonical/kafka-operator/releases) provide a detailed list of bug fixes, PRs, and commits for each revision.
* Upgrades from previous stable versions can be done with the standard upgrading process, as outlined in the [documentation](how-to-upgrade)
