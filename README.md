# Charmed Kafka K8s Operator

## Overview

The Charmed Kafka K8s Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform.

The Kafka K8s Operator uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [`ubuntu/kafka` OCI image](https://registry.hub.docker.com/r/ubuntu/kafka) distributed by Canonical.

This operator charm comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authenticaion enabled by default.
- Access control management supported with user-provided ACL lists.

As currently Kafka requires a paired ZooKeeper deployment in production, this operator makes use of the [ZooKeeper K8s Operator](https://github.com/canonical/zookeeper-k8s-operator) for various essential functions.

## Requirements

For production environments, it is recommended to deploy at least 5 nodes for Zookeeper and 3 for Kafka.
While the following requirements are meant to be for production, the charm can be deployed in much smaller environments.

- 64GB of RAM
- 24 cores
- 12 storage devices
- 10 GbE card

## Usage

### Basic usage

The Kafka and ZooKeeper operators can both be deployed as follows:
```shell
$ juju deploy zookeeper-k8s --channel latest/edge -n 5
$ juju deploy kafka-k8s --channel latest/edge -n 3
```

After this, it is necessary to connect them:
```shell
$ juju relate kafka-k8s zookeeper-k8s
```

To watch the process, `juju status` can be used. Once all the units show as `active|idle` the credentials to access a broker can be queried with:
```shell
juju run-action kafka-k8s/leader get-admin-credentials --wait 
```

### Replication
#### Scaling application
The charm can be scaled using `juju scale-application` command.
```shell
juju scale-application kafka-k8s <num_of_brokers_to_scale_to>
```

This will add or remove brokers to match the required number. To scale a deployment with 3 kafka units to 5, run:
```shell
juju scale-application kafka-k8s 5
```

### Password rotation
#### Internal operator user
The operator user is used internally by the Charmed MongoDB Operator, the `set-password` action can be used to rotate its password.
```shell
# to set a specific password for the operator user
juju run-action kafka-k8s/leader set-password password=<password> --wait

# to randomly generate a password for the operator user
juju run-action kafka-k8s/leader set-password --wait
```

## Relations

Supported [relations](https://juju.is/docs/olm/relations):

#### `tls` interface:

To enable TLS:

```shell
# deploy the TLS charm 
juju deploy tls-certificates-operator --channel=edge
# add the necessary configurations for TLS
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA" 
# to enable TLS relate the two applications 
juju relate tls-certificates-operator zookeeper-k8s
juju relate tls-certificates-operator kafka-k8s
```

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action.
```shell
# Updates can be done with auto-generated keys with
juju run-action kafka-k8s/0 set-tls-private-key --wait
juju run-action kafka-k8s/1 set-tls-private-key --wait
juju run-action kafka-k8s/2 set-tls-private-key --wait
```

Passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`. With three brokers this schema should be followed:
```shell
# generate shared internal key
openssl genrsa -out internal-key.pem 3072
# generate external keys for each unit
openssl genrsa -out external-key-0.pem 3072
openssl genrsa -out external-key-1.pem 3072
openssl genrsa -out external-key-2.pem 3072
# apply both private keys on each unit, shared internal key will be allied only on juju leader
juju run-action kafka-k8s/0 set-tls-private-key "external-key=$(base64 -w0 external-key-0.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka-k8s/1 set-tls-private-key "external-key=$(base64 -w0 external-key-1.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka-k8s/2 set-tls-private-key "external-key=$(base64 -w0 external-key-2.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait
```

To disable TLS remove the relation
```shell
juju remove-relation kafka-k8s tls-certificates-operator
juju remove-relation zookeeper-k8s tls-certificates-operator
```

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)


## Security
Security issues in the Charmed Kafka K8s Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.


## License
The Charmed Kafka K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) for more information.
