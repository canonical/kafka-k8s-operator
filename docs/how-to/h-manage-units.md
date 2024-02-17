# How to deploy and manage units

## Basic usage

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
juju run kafka-k8s/leader get-admin-credentials
```

The Charmed Kafka OCI Image ships with `/opt/kafka/bin/*.sh` commands to do various administrative tasks, e.g `kafka-config.sh` to update cluster configuration, `kafka-topics.sh` for topic management, and many more! The Charmed Kafka K8s Operator provides these commands to administrators to easily run their desired cluster configurations securely with SASL authentication, either from within the cluster or as an external client.

If you wish to run a command from the cluster, in order to (for example) list the current topics on the Kafka cluster, you can run:
```
BOOTSTRAP_SERVERS=$(juju run kafka-k8s/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f 2)
juju ssh --container kafka kafka-k8s/leader '/opt/kafka/bin/kafka-topics.sh --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /etc/kafka/client.properties'
```

Note that when no other application is related to Kafka, the cluster is secured-by-default and listeners are disabled, thus preventing any incoming connection. However, even for running the commands above, listeners must be enable. If there is no other application, deploy a `data-integrator` charm and relate it to Kafka, as outlined in the Relation section to enable listeners.

## Replication

### Scaling application
The charm can be scaled using `juju scale-application` command.
```shell
juju scale-application kafka-k8s <num_of_brokers_to_scale_to>
```

This will add or remove brokers to match the required number. To scale a deployment with 3 kafka units to 5, run:
```shell
juju scale-application kafka-k8s 5
```

Even when scaling multiple units at the same time, the charm uses a rolling restart sequence to make sure the cluster stays available and healthy during the operation.