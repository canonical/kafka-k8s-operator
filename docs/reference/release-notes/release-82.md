(reference-release-notes-release-82)=
# Release 82

This release upgrades workload versions for Apache Kafka to `3.9.0` and for Apache ZooKeeper to `3.9.2`, as well as adds support for: Cruise Control partition rebalancing, KRaft consensus protocol, Karapace, and backup/restore using S3.

[Charmhub](https://charmhub.io/kafka-k8s) | [Deploy guide](how-to-deploy-index) | [Upgrade instructions](how-to-upgrade) | [System requirements](reference-requirements)

## Charmed Apache Kafka K8s

New features and bug fixes in the Charmed Apache Kafka K8s:

### Features

- [DPE-2872](https://warthogs.atlassian.net/browse/DPE-2872) - feat: partition rebalancing with Cruise Control [#219](https://github.com/canonical/kafka-operator/pull/#219)
- [DPE-4328](https://warthogs.atlassian.net/browse/DPE-4328) - feat: support KRaft [#232](https://github.com/canonical/kafka-operator/pull/#232)
- [DPE-6574](https://warthogs.atlassian.net/browse/DPE-6574) - feat: support cross-model K8s relations with juju expose [#309](https://github.com/canonical/kafka-operator/pull/#309)
- [DPE-6260](https://warthogs.atlassian.net/browse/DPE-6260) - feat: trust multi-certificate ca-chains [#297](https://github.com/canonical/kafka-operator/pull/#297)
- [DPE-6636](https://warthogs.atlassian.net/browse/DPE-6636) - feat: support non-unit/port extra_listeners [#315](https://github.com/canonical/kafka-operator/pull/#315)

### Improvements

- [DPE-4956](https://warthogs.atlassian.net/browse/DPE-4956) - test: stabilise integration tests  [#229](https://github.com/canonical/kafka-operator/pull/#229)
- [DPE-5226](https://warthogs.atlassian.net/browse/DPE-5226) - refactor: make 'broker' the central relation [#244](https://github.com/canonical/kafka-operator/pull/#244)
- [DPE-5591](https://warthogs.atlassian.net/browse/DPE-5591) - refactor: rework status handling [#254](https://github.com/canonical/kafka-operator/pull/#254)
- [DPE-5945](https://warthogs.atlassian.net/browse/DPE-5945) - chore: rename expose_external configuration option [#274](https://github.com/canonical/kafka-operator/pull/#274)
- [DPE-5553](https://warthogs.atlassian.net/browse/DPE-5553) - feat: don't restart server on keystore/truststore updates [#272](https://github.com/canonical/kafka-operator/pull/#272)
- [DPE-5349](https://warthogs.atlassian.net/browse/DPE-5349) - feat: add internal user and SASL/SCRAM authentication [#284](https://github.com/canonical/kafka-operator/pull/#284)
- [DPE-6138](https://warthogs.atlassian.net/browse/DPE-6138) - chore: update zookeeper client lib [#282](https://github.com/canonical/kafka-operator/pull/#282)
- [DPE-6266](https://warthogs.atlassian.net/browse/DPE-6266) - chore: prepare charm for Charmcraft 3 [#293](https://github.com/canonical/kafka-operator/pull/#293)
- [DPE-5232](https://warthogs.atlassian.net/browse/DPE-5232);[DPE-5233](https://warthogs.atlassian.net/browse/DPE-5233) - chore: support for scaling operations in KRaft mode (single & multi-app) [#281](https://github.com/canonical/kafka-operator/pull/#281)
- [DPE-6247](https://warthogs.atlassian.net/browse/DPE-6247) - {spellexception}`test/cicd`: stabilise int-test CI [#320](https://github.com/canonical/kafka-operator/pull/#320)

### Bug fixes

- [DPE-4703](https://warthogs.atlassian.net/browse/DPE-4703) - chore: sync vm + k8s w. nodeport feature [#226](https://github.com/canonical/kafka-operator/pull/#226)
- [DPE-4951](https://warthogs.atlassian.net/browse/DPE-4951) - fix: re-enable prefixed topic names during relations [#227](https://github.com/canonical/kafka-operator/pull/#227)
- [DPE-5208](https://warthogs.atlassian.net/browse/DPE-5208) - fix: secure written znodes [#231](https://github.com/canonical/kafka-operator/pull/#231)
- [DPE-5218](https://warthogs.atlassian.net/browse/DPE-5218) - chore: enable compatibility with ZK restore feature [#243](https://github.com/canonical/kafka-operator/pull/#243)
- [DPE-5686](https://warthogs.atlassian.net/browse/DPE-5686) - test: fix flaky CI
- [DPE-5611](https://warthogs.atlassian.net/browse/DPE-5611) - fix: remove cruise-control metrics reporter if no balancer [#250](https://github.com/canonical/kafka-operator/pull/#250)
- [DPE-5826](https://warthogs.atlassian.net/browse/DPE-5826) - fix: remove lost+found from new storages [#275](https://github.com/canonical/kafka-operator/pull/#275)
- [DPE-6261](https://warthogs.atlassian.net/browse/DPE-6261) - fix: remove '/' character from generated SANs for Digicert [#297](https://github.com/canonical/kafka-operator/pull/#297)
- [DPE-6498](https://warthogs.atlassian.net/browse/DPE-6498) - fix: gracefully handle rebalance action when role not set [#313](https://github.com/canonical/kafka-operator/pull/#313)
- [DPE-6547](https://warthogs.atlassian.net/browse/DPE-6547) - fix: KRaft multi-mode scaling bug on broker side [#319](https://github.com/canonical/kafka-operator/pull/#319)

## Charmed Apache ZooKeeper K8s

New features and bug fixes in the Charmed Apache ZooKeeper K8s:

### Features

- [DPE-5216](https://warthogs.atlassian.net/browse/DPE-5216) - feat: S3 integration [#151](https://github.com/canonical/zookeeper-operator/pull/#151)
- [DPE-5987](https://warthogs.atlassian.net/browse/DPE-5987) - feat: add expose-external configuration option [#172](https://github.com/canonical/zookeeper-operator/pull/#172)
- [DPE-5438](https://warthogs.atlassian.net/browse/DPE-5438) - feat: enable digest auth [#173](https://github.com/canonical/zookeeper-operator/pull/#173)
- [DPE-6262](https://warthogs.atlassian.net/browse/DPE-6262) - feat: support TLS certificate chains [#181](https://github.com/canonical/zookeeper-operator/pull/#181)

### Improvements

- [DPE-3477](https://warthogs.atlassian.net/browse/DPE-3477) - chore: reload stores [#152](https://github.com/canonical/zookeeper-operator/pull/#152)
- [DPE-5373](https://warthogs.atlassian.net/browse/DPE-5373) - chore: create backup action [#156](https://github.com/canonical/zookeeper-operator/pull/#156)
- [DPE-5126](https://warthogs.atlassian.net/browse/DPE-5126) - chore: use admin server instead of the 4lw commands [#154](https://github.com/canonical/zookeeper-operator/pull/#154)
- [DPE-5373](https://warthogs.atlassian.net/browse/DPE-5373) - chore: implement list-backups action [#157](https://github.com/canonical/zookeeper-operator/pull/#157)
- [DPE-5549](https://warthogs.atlassian.net/browse/DPE-5549) - chore: enable TLS v1.2 for client communication [#161](https://github.com/canonical/zookeeper-operator/pull/#161)
- [DPE-5218](https://warthogs.atlassian.net/browse/DPE-5218) - chore: implement restore flow [#162](https://github.com/canonical/zookeeper-operator/pull/#162)
- [DPE-5874](https://warthogs.atlassian.net/browse/DPE-5874) - test/refactor: Unit test migration [#171](https://github.com/canonical/zookeeper-operator/pull/#171)

### Bug fixes

- [DPE-5208](https://warthogs.atlassian.net/browse/DPE-5208) - fix: enforce client auth [#150](https://github.com/canonical/zookeeper-operator/pull/#150)
- [DPE-5463](https://warthogs.atlassian.net/browse/DPE-5463);[DPE-5462](https://warthogs.atlassian.net/browse/DPE-5462) - fix: quote SERVER_JVMFLAGS, safe rm tls files [#160](https://github.com/canonical/zookeeper-operator/pull/#160)
- [DPE-5462](https://warthogs.atlassian.net/browse/DPE-5462) - fix: handle NoNodeError during relation-broken [#168](https://github.com/canonical/zookeeper-operator/pull/#168)
- [DPE-6157](https://warthogs.atlassian.net/browse/DPE-6157) - fix: don't erase previous records from /etc/hosts [#175](https://github.com/canonical/zookeeper-operator/pull/#175)

## Compatibility

Principal charms support the latest LTS series “22.04” only.

| Charm | Revision | Hardware architecture | Juju version | Artefacts |
|---|---|---|---|---|
| Charmed Apache Kafka K8s | [82](https://github.com/canonical/kafka-k8s-operator/tree/rev82) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.9.0-ubuntu1](https://launchpad.net/kafka-releases/3.x/3.9.0-ubuntu1). <br> `charmed-kafka` rock: [{spellexception}`sha256:fa919f`](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka/370866723). |
| Charmed Apache ZooKeeper K8s | [51](https://github.com/canonical/zookeeper-k8s-operator/tree/rev51) | AMD64 | 2.9.45+, Juju 3.1+ | Distribution: [3.8.2-ubuntu0](https://launchpad.net/zookeeper-releases/3.x/3.8.2-ubuntu0). <br> `charmed-zookeeper` rock: [{spellexception}`sha256:a7a004`](https://github.com/canonical/charmed-zookeeper-rock/pkgs/container/charmed-zookeeper/169796097). |

Apache Kafka release notes: [3.7.0](https://archive.apache.org/dist/kafka/3.7.0/RELEASE_NOTES.html), [3.8.0](https://archive.apache.org/dist/kafka/3.8.0/RELEASE_NOTES.html), [3.9.0](https://archive.apache.org/dist/kafka/3.9.0/RELEASE_NOTES.html).

Apache ZooKeeper release notes: [3.9.0](https://zookeeper.apache.org/doc/r3.9.0/releasenotes.html), [3.9.1](https://zookeeper.apache.org/doc/r3.9.1/releasenotes.html), [3.9.2](https://zookeeper.apache.org/doc/r3.9.2/releasenotes.html).
