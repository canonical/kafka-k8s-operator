# Charmed Kafka K8s Operator

[![CharmHub Badge](https://charmhub.io/kafka-k8s/badge.svg)](https://charmhub.io/kafka-k8s)
[![Release](https://github.com/canonical/kafka-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/kafka-k8s-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/kafka-k8s-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/kafka-k8s-operator/actions/workflows/ci.yaml?query=branch%3Amain)
[![Docs](https://github.com/canonical/kafka-k8s-operator/actions/workflows/sync_docs.yaml/badge.svg)](https://github.com/canonical/kafka-k8s-operator/actions/workflows/sync_docs.yaml)

## Overview

The Charmed Kafka K8s Operator delivers automated operations management from day 0 to day 2 on the [Apache Kafka](https://kafka.apache.org) event streaming platform deployed on top of a [Kubernetes cluster](https://kubernetes.io/). It is an open source, end-to-end, production ready data platform on top of cloud native technologies.

The Kafka K8s Operator can be found on [Charmhub](https://charmhub.io/kafka-k8s) and it comes with features such as:
- Fault-tolerance, replication, scalability and high-availability out-of-the-box.
- SASL/SCRAM auth for Broker-Broker and Client-Broker authentication enabled by default.
- Access control management supported with user-provided ACL lists.

The Kafka K8s Operator uses the latest upstream Kafka binaries released by the The Apache Software Foundation that comes with Kafka, made available using the [`ubuntu/kafka` OCI image](https://registry.hub.docker.com/r/ubuntu/kafka) distributed by Canonical.

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
$ juju deploy zookeeper-k8s --channel edge -n 5
$ juju deploy kafka-k8s --channel edge -n 3
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
The operator user is used internally by the Charmed Kafka K8s Operator, the `set-password` action can be used to rotate its password.
```shell
# to set a specific password for the operator user
juju run-action kafka-k8s/leader set-password password=<password> --wait

# to randomly generate a password for the operator user
juju run-action kafka-k8s/leader set-password --wait
```

### Storage support

Currently, the Charmed Kafka K8s Operator makes use of a 10GB storage mount, tied to a [Kubernetes PVC](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).

This is used for logs storage, mounted on `/logs/kafka`

## Relations

Supported [relations](https://juju.is/docs/olm/relations):

#### `kafka_client` interface:

The `kafka_client` interface is used with the `data-integrator` charm. This charm allows to automatically create and manage product credentials needed to authenticate with different kinds of data platform charmed products:

Deploy the data-integrator charm with the desired `topic-name` and user roles: 
```shell
juju deploy data-integrator --channel edge
juju config data-integrator topic-name=test-topic extra-user-roles=producer,consumer
```

Relate the two applications with:
```shell
juju relate data-integrator kafka-k8s
```

To retrieve information, enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```

This should output something like:
```yaml
unit-data-integrator-0:                                                         
  UnitId: data-integrator/0                                                     
  id: "4"                                                                       
  results:                                                                      
    kafka:                                                                      
      consumer-group-prefix: relation-27-                                       
      endpoints: 10.123.8.133:19092                                             
      password: ejMp4SblzxkMCF0yUXjaspneflXqcyXK                                
      tls: disabled                                                             
      username: relation-27                                                     
      zookeeper-uris: 10.123.8.154:2181,10.123.8.181:2181,10.123.8.61:2181/kafka
    ok: "True"                                                                  
  status: completed                                                             
  timing:                                                                       
    completed: 2023-01-27 14:22:51 +0000 UTC                                    
    enqueued: 2023-01-27 14:22:50 +0000 UTC                                     
    started: 2023-01-27 14:22:51 +0000 UTC                                      
```

#### `tls-certificates` interface:

The `tls-certificates` interface is used with the `tls-certificates-operator` charm.

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
# apply keys on each unit
juju run-action kafka-k8s/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka-k8s/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action kafka-k8s/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)"  --wait
```

To disable TLS remove the relation
```shell
juju remove-relation kafka-k8s tls-certificates-operator
juju remove-relation zookeeper-k8s tls-certificates-operator
```

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)


## Monitoring

The Charmed Kafka K8s Operator comes with several exporters by default. The metrics can be queried by accessing the following endpoints:

- JMX exporter: `http://<pod-ip>:9101/metrics`

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy `cos-lite` bundle in a Kubernetes environment. This can be done by following the [deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s). It is needed to offer the endpoints of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml) can be used, and this step is shown on the COS tutorial.

Once COS is deployed, we can find the offers from the Kafka model:
```shell
# We are on the `cos` model. Switch to `kafka` model
juju switch <kafka_model_name>

juju find-offers <k8s_controller_name>:
```

A similar output should appear, if `micro` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:
```
Store  URL                   Access  Interfaces                         
micro  admin/cos.grafana     admin   grafana_dashboard:grafana-dashboard
micro  admin/cos.prometheus  admin   prometheus_scrape:metrics-endpoint
. . .
```

Now, integrate kafka with the `metrics-endpoint`, `grafana-dashboard` and `logging` relations:
```shell
juju relate micro:admin/cos.prometheus kafka-k8s
juju relate micro:admin/cos.grafana kafka-k8s
juju relate micro:admin/cos.loki kafka-k8s
```

After this is complete, Grafana will show a new dashboard: `Kafka JMX Metrics`

## Security
Security issues in the Charmed Kafka K8s Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.


## License
The Charmed Kafka K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-k8s-operator/blob/main/LICENSE) for more information.
