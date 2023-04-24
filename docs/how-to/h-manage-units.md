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
juju run-action kafka-k8s/leader get-admin-credentials --wait 
```

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