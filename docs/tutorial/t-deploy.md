This is part of the [Charmed Kafka K8s Tutorial](/t/charmed-kafka-k8s-documentation-tutorial-overview/11945). Please refer to this page for more information and the overview of the content. 

## Deploy Charmed Kafka K8s (and Charmed ZooKeeper K8s)

To deploy Charmed Kafka K8s, all you need to do is run the following commands, which will automatically fetch [Kafka](https://charmhub.io/kafka-k8s?channel=3/stable) and [ZooKeeper](https://charmhub.io/zookeeper-k8s?channel=3/stable) charms from [Charmhub](https://charmhub.io/) and deploy them to your model. For example, to deploy a 5 ZooKeeper unit and 3 Kafka unit cluster, you can simply run

```shell
$ juju deploy zookeeper-k8s -n 3 
$ juju deploy kafka-k8s -n 3 
```

After this, it is necessary to connect them:

```shell
$ juju relate kafka-k8s zookeeper-k8s
```

Juju will now fetch Charmed Kafka K8s and Charmed ZooKeeper K8s and begin deploying it to the local MicroK8s. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

This command is useful for checking the status of Charmed ZooKeeper K8s and Charmed Kafka K8s. Some of the helpful information it displays include IP pods addresses, ports, state, etc. 
The command updates the status of the cluster every second and as the application starts you can watch the status and messages of Charmed Kafka K8s and Charmed ZooKeeper K8s change. 

Wait until the application is ready - when it is ready, `juju status --watch 1s` will show:
```shell
...
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.1.5    unsupported  17:22:21+02:00

App            Version  Status  Scale  Charm          Channel  Rev  Address         Exposed  Message
kafka-k8s               active      3  kafka-k8s      3/beta    46  10.152.183.237  no
zookeeper-k8s           active      3  zookeeper-k8s  3/beta    37  10.152.183.134  no

Unit              Workload  Agent  Address     Ports  Message
kafka-k8s/0       active    idle   10.1.36.78
kafka-k8s/1       active    idle   10.1.36.80
kafka-k8s/2*      active    idle   10.1.36.79
zookeeper-k8s/0   active    idle   10.1.36.84
zookeeper-k8s/1*  active    idle   10.1.36.86
zookeeper-k8s/2   active    idle   10.1.36.85
```
To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.

## Access Kafka cluster

To watch the process, `juju status` can be used. Once all the units show as `active|idle` the credentials to access a broker can be queried with:
```shell
juju run kafka-k8s/leader get-admin-credentials
```

The output of the previous command is something like this:
```shell
Running operation 1 with 1 task
  - task 2 on unit-kafka-k8s-2

Waiting for task 2...
client-properties: |-
  security.protocol=SASL_PLAINTEXT
  sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp";
  sasl.mechanism=SCRAM-SHA-512
  bootstrap.servers=kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092
password: 0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp
username: admin
```

Providing you the `username` and `password` of the Kafka cluster admin user. 

> **IMPORTANT** Note that when no other application is related to Kafka, the cluster is secured-by-default and external listeners (bound to port 9092) are disabled, thus preventing any external incoming connection. 

Nevertheless, it is still possible to run a command from within the Kafka cluster. To do so, log in into one of the Kafka container in one of the units

```shell
juju ssh --container kafka kafka-k8s/leader /bin/bash
```

The Charmed Kafka K8s image ships with the Apache Kafka `bin/*.sh` commands, that can be found under `/opt/kafka/bin/`.
These allow admin to do various administrative tasks, e.g `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh` for topic management, and many more! 
Within the image you can also find a `client.properties` file that already provides the relevant settings to connect to the cluster using the CLI:

```shell
export CLIENT_PROPERTIES=/etc/kafka/client.properties
```

Since we don't have any client applications related yet and therefore external listeners are initially closed, if you wish to run a command from the cluster you ought to use the internal listeners exposed at ports 19092.  
```shell
export INTERNAL_LISTENERS=kafka-k8s-1.kafka-k8s-endpoints:19092,kafka-k8s-2.kafka-k8s-endpoints:19092,kafka-k8s-0.kafka-k8s-endpoints:19092
```

We are now ready to perform some administrative tasks. For example, in order to create a topic, you can run:
```shell
/opt/kafka/bin/kafka-topics.sh \
    --create --topic test_topic \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

You can similarly then list the topic, using
```shell
/opt/kafka/bin//kafka-topics.sh \
    --list \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

making sure the topic was successfully created.

You can finally delete the topic, using 

```shell
/opt/kafka/bin/kafka-topics.sh \
    --delete --topic test_topic \
    --bootstrap-server  $INTERNAL_LISTENERS \
    --command-config $CLIENT_PROPERTIES
```

## What's next?

However, although the commands above can run within the cluster, it is generally recommended during operations
to enable external listeners and use these for running the admin commands from outside the cluster. 
To do so, as we will see in the next section, we will deploy a [data-integrator](https://charmhub.io/data-integrator) charm and relate it to Kafka.