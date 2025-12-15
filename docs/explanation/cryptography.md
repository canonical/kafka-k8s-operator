(explanation-cryptography)=
# Cryptography

This document describes the cryptography used by Charmed Apache Kafka K8s.

## Resource checksums

Charmed Apache Kafka K8s operator uses a pinned revision of the Charmed Kafka rock
to provide a reproducible and secure environment.

The [Charmed Apache Kafka rock](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka)
is an OCI image derived from the respective snap. The snap packages the Apache Kafka workload
along with the necessary dependencies and utilities required for the operators lifecycle.
See the snap contents for the
[Charmed Apache Kafka K8s](https://github.com/canonical/charmed-kafka-snap/blob/4/edge/snap/snapcraft.yaml).

Every artifact bundled into the Charmed Apache Kafka K8s snap (which the rock is built from)
is verified after download using its MD5, SHA-256, or SHA-512 checksum.
The installation of certified snaps into the rock is ensured by snap primitives that verify their
Squashfs file systems images GPG signature.
For more information on the snap verification process,
refer to the [Snapcraft documentation](https://snapcraft.io/docs/assertions).

## Sources verification

Charmed Apache Kafka K8s sources are stored in:

* GitHub repositories for snaps, rocks and charms
* Launchpad repositories for the Apache Kafka upstream fork for building from the source

### Launchpad

Distributions are built using private repositories only, hosted as part of the
[SOSS namespace](https://launchpad.net/soss) (private) to eventually
integrate with Canonical's standard process for fixing CVE.
Branches associated with releases are mirrored to a public repository,
hosted in the [Data Platform namespace](https://launchpad.net/~data-platform)
to also provide the community with the patched source code.

### GitHub

All Apache Kafka artefacts built by Canonical are published and released
programmatically using release pipelines implemented via GitHub Actions.
Distributions are published as both GitHub and Launchpad releases via the
[central-uploader repository](https://github.com/canonical/central-uploader), while
charms, snaps, and rocks are published using the workflows of their respective repositories.

All repositories in GitHub are set up with branch protection rules, requiring:

* new commits to be merged to main branches via pull request with at least 2 approvals from repository maintainers
* new commits to be signed (e.g. using GPG keys)
* developers to sign the [Canonical Contributor License Agreement (CLA)](https://ubuntu.com/legal/contributors)

## Encryption

Charmed Apache Kafka K8s can be used to deploy a secure Apache Kafka cluster on K8s
that provides encryption-in-transit capabilities out of the box for:

* Interbroker communications
* Broker-controller communications
* Client connections

To set up a secure connection Charmed Apache Kafka K8s need to be integrated with
TLS Certificate Provider charms, e.g., `self-signed-certificates` operator.
Certificate Signing Requests (CSRs) are generated for every unit using the
`tls_certificates_interface` library that uses the `cryptography` Python library
to create X.509 compatible certificates.
The CSR is signed by the TLS Certificate Provider, returned to the units, and stored
in a password-protected Keystore file.
The password of the Keystore is stored in Juju secrets.
The relation also provides the CA certificate, which is loaded into a password-protected
Truststore file.

When encryption is enabled, hostname verification is turned on for client connections,
including both inter-broker and broker-controller communications.
The cipher suite can be customised by specifying a list of allowed cipher suites
for external clients. This is done using the charm configuration option
`ssl_cipher_suites` (see [reference documentation](https://charmhub.io/kafka-k8s/configurations)).

Encryption at rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication

In Charmed Apache Kafka K8s, authentication layers can be enabled for:

1. Inter-broker communications
2. Broker-controller communications
3. Clients connections

### Inter-broker and broker-controller authentication

Authentication between brokers and between brokers and KRaft controllers are based
on the SCRAM-SHA-512 protocol. Usernames and passwords are exchanged via Juju secrets.

The Apache Kafka username and password, used by brokers and controllers to authenticate one another,
are stored in JAAS configuration files on the Charmed Apache Kafka K8s units in plain text format.

These files are readable and writable by `root` (as it is created by the charm) and readable
by the snap-internal `_daemon_` user running the Apache Kafka server snap commands.

### Client authentication to Apache Kafka

Clients can authenticate to Apache Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols
2. client certificates or CA (mTLS)
3. OAuth Authentication using [Hydra](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-hydra-as-oidc-provider/14610) or [Google](https://discourse.charmhub.io/t/how-to-connect-to-kafka-using-google-as-oidc-provider/14611)

When using SCRAM, usernames and passwords are stored in the KRaft controller metadata logs,
in plain text in configuration files on the broker and controller units, and in Juju secrets.
When using mTLS, client certificates provided to the Apache Kafka cluster via Juju secrets
by integrated charms are stored in password-protected JKS truststores.
