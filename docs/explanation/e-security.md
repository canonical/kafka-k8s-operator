# Cryptography

This document describes cryptography used by Charmed Apache Kafka K8s.

## Resource checksums

Every version of the Charmed Apache Kafka K8s and Charmed Apache ZooKeeper K8s operators employs a pinned revision of the Charmed Apache Kafka rock
and Charmed Apache ZooKeeper rock, respectively, to 
provide reproducible and secure environments. 
The [Charmed Apache Kafka rock](https://github.com/canonical/charmed-kafka-rock/pkgs/container/charmed-kafka) and 
[Charmed Apache ZooKeeper rock](https://github.com/canonical/charmed-zookeeper-rock/pkgs/container/charmed-zookeeper) are OCI images
derived by the Charmed Apache Kafka snap and Charmed Apache ZooKeeper snap, which package the Apache Kafka and Apache ZooKeeper workload together with 
a set of dependencies and utilities required by the lifecycle of the operators (see [Charmed Apache Kafka snap contents](https://github.com/canonical/charmed-kafka-snap/blob/3/edge/snap/snapcraft.yaml) and [Charmed Apache ZooKeeper snap contents](https://github.com/canonical/charmed-zookeeper-snap/blob/3/edge/snap/snapcraft.yaml)).

Every artifact bundled into the Charmed Apache Kafka snap and Charmed Apache ZooKeeper snap is verified against their MD5, SHA256 or SHA512 checksum after download. 
The installation of certified snaps into the rock is ensured by snap primitives that verify their 
squashfs filesystems images GPG signature. For more information on the snap verification process, refer to the [snapcraft.io documentation](https://snapcraft.io/docs/assertions). 

## Sources verification

Charmed Apache Kafka sources are stored in:

* GitHub repositories for snaps, rocks and charms
* LaunchPad repositories for the Apache Kafka and Apache ZooKeeper upstream fork used for building their respective distributions

### LaunchPad

Distributions are built using private repositories only, hosted as part of the [SOSS namespace](https://launchpad.net/soss) to eventually
integrate with Canonical's standard process for fixing CVEs. 
Branches associated with releases are mirrored to a public repository, hosted in the [Data Platform namespace](https://launchpad.net/~data-platform) 
to also provide the community with the patched source code. 

### GitHub

All Charmed Apache Kafka and Charmed Apache ZooKeeper artifacts are published and released 
programmatically using release pipelines implemented via GitHub Actions. 
Distributions are published as both GitHub and LaunchPad releases via the [central-uploader repository](https://github.com/canonical/central-uploader), while 
charms, snaps and rocks are published using the workflows of their respective repositories. 

All repositories in GitHub are set up with branch protection rules, requiring:

* new commits to be merged to main branches via pull request with at least 2 approvals from repository maintainers
* new commits to be signed (e.g. using GPG keys)
* developers to sign the [Canonical Contributor License Agreement (CLA)](https://ubuntu.com/legal/contributors)

## Encryption

The Charmed Apache Kafka operator can be used to deploy a secure Apache Kafka cluster on K8s that provides encryption-in-transit capabilities out of the box 
for:

* Interbroker communications
* Apache ZooKeeper connection
* External client connection 

To set up a secure connection Apache Kafka and Apache ZooKeeper applications need to be integrated with TLS Certificate Provider charms, e.g. 
`self-signed-certificates` operator. CSRs are generated for every unit using `tls_certificates_interface` library that uses `cryptography` 
python library to create X.509 compatible certificates. The CSR is signed by the TLS Certificate Provider and returned to the units, and 
stored in a password-protected Keystore file. The password of the Keystore is stored in Juju secrets starting from revision 168 on Apache Kafka 
and revision 130 on Apache ZooKeeper. The relation provides also the certificate for the CA to be loaded in a password-protected Truststore file.

When encryption is enabled, hostname verification is turned on for client connections, including inter-broker communication. Cipher suite can 
be customized by providing a list of allowed cipher suite to be used for external clients and Apache Apache ZooKeeper connections, using the charm config options
`ssl_cipher_suites`  and `zookeeper_ssl_cipher_suites` config options respectively. Please refer to the [reference documentation](https://charmhub.io/kafka-k8s/configurations)
for more information. 

Encryption at rest is currently not supported, although it can be provided by the substrate (cloud or on-premises).

## Authentication

In the Charmed Apache Kafka solution, authentication layers can be enabled for:

1. Apache ZooKeeper connections
2. Apache Kafka inter-broker communication 
3. Apache Kafka Clients

### Apache Kafka authentication to Apache ZooKeeper

Authentication to Apache ZooKeeper is based on Simple Authentication and Security Layer (SASL) using digested MD5 hashes of
username and password, and implemented both for client-server (with Apache Kafka) and server-server communication.
Username and passwords are exchanged using peer relations among Apache ZooKeeper units and using normal relations between Apache Kafka and Apache ZooKeeper.
Juju secrets are used for exchanging credentials starting from revision 168 on Apache Kafka and revision 130 on Apache ZooKeeper.

Username and password for the different users are stored in Apache ZooKeeper servers in a JAAS configuration file in plain format. 
Permission on the file is restricted to the root user. 

### Apache Kafka Inter-broker authentication

Authentication among brokers is based on SCRAM-SHA-512 protocol. Username and passwords are exchanged 
via peer relations, using Juju secrets from revision 168 on Charmed Apache Kafka.

Apache Kafka username and password used by brokers to authenticate one another are stored 
both in a Apache ZooKeeper zNode and in a JAAS configuration file in the Apache Kafka server in plain format. 
The file needs to be readable and
writable by root (as it is created by the charm), and be readable by the `snap_daemon` user running the Apache Kafka server snap commands.

### Client authentication to Apache Kafka

Clients can authenticate to Kafka using:

1. username and password exchanged using SCRAM-SHA-512 protocols 
2. client certificates or CAs (mTLS)

When using SCRAM, username and passwords are stored in Apache ZooKeeper to be used by the Apache Kafka processes, 
in peer-relation data to be used by the Apache Kafka charm and in external relation to be shared with client applications. 
Starting from revision 168 on Charmed Apache Kafka, Juju secrets are used for storing the credentials in place of plain unencrypted text.

When using mTLS, client certificates are loaded into a `tls-certificates` operator and provided to the Apache Kafka charm via the plain-text unencrypted 
relation. Certificates are stored in the password-protected Truststore file.