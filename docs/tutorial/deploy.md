---
myst:
  html_meta:
    description: "Deploy Apache Kafka K8s clusters with brokers and KRaft controllers on Kubernetes using Juju commands."
---

(tutorial-deploy)=
# 2. Deploy Apache Kafka

This is a part of the [Charmed Apache Kafka K8s Tutorial](tutorial-introduction).

## Deploy Charmed Apache Kafka K8s

To deploy Charmed Apache Kafka K8s, all you need to do is run the following commands,
which will automatically fetch [Apache Kafka](https://charmhub.io/kafka-k8s?channel=4/edge)
from [Charmhub](https://charmhub.io/) and deploy it to your model.

For example, to deploy a cluster of three Apache Kafka brokers, you can simply run:

```shell
juju deploy kafka-k8s -n 3 --channel 4/edge --config roles=broker --trust
```

Apache Kafka also uses the KRaft consensus protocol for coordinating broker information,
topic + partition metadata, and Access Control Lists (ACLs), ran as a quorum of controller
nodes using the Raft consensus algorithm.

```{note}
KRaft replaces the dependency on Apache ZooKeeper for metadata management.
For more information on the differences between the two solutions,
please refer to the [upstream Apache Kafka documentation](https://kafka.apache.org/41/getting-started/zk2kraft/)
```

Charmed Apache Kafka K8s can run both with `roles=broker` and/or `roles=controller`.
With this configuration option, the charm can be deployed either as a single application
running both Apache Kafka brokers and KRaft controllers, or as multiple applications with
a separate controller cluster and broker cluster.

To deploy a cluster of three KRaft controllers, run:

```shell
juju deploy kafka-k8s -n 3 --channel 4/edge --config roles=controller kraft --trust
```

After this, it is necessary to connect the two clusters, taking care to specify which
cluster is the orchestrator:

```shell
juju integrate kafka-k8s:peer-cluster-orchestrator kraft:peer-cluster
```

Juju will now fetch Charmed Apache Kafka K8s and begin deploying both applications to the cloud
before connecting them to exchange access credentials and machine endpoints.
This process can take several minutes depending on the resources available.
You can track the progress by running:

```shell
watch -n 1 --color juju status --color
```

This command is useful for checking the status of both Charmed Apache Kafka K8s applications,
and for gathering information about the machines hosting the two applications.
Some of the helpful information it displays includes IP addresses, ports, status etc.
The command updates the status of the cluster every second and as the application starts
you can watch the status and messages both applications change.

Wait until the application is ready - when it is ready, `watch -n 1 --color juju status --color`
will show:

```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  microk8s    microk8s/localhost  3.6.12   unsupported  17:30:56Z

App        Version  Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
kafka-k8s  4.0.0    active      3  kafka-k8s  4/edge    96  10.152.183.93   no       
kraft      4.0.0    active      3  kafka-k8s  4/edge    96  10.152.183.160  no       

Unit          Workload  Agent      Address       Ports  Message
kafka-k8s/0*  active    idle       10.1.188.228         
kafka-k8s/1   active    idle       10.1.188.227         
kafka-k8s/2   active    idle       10.1.188.231         
kraft/0       active    idle       10.1.188.230         
kraft/1       active    idle       10.1.188.229         
kraft/2*      active    idle       10.1.188.232  
```

To exit the screen, press `Ctrl+C`.

## Connect to brokers

Now that we have Apache Kafka cluster set up and ready,
we can test it by connecting to it and running some simple commands.

Charmed Apache Kafka K8s aims to follow the secure by default paradigm.
As a consequence, after being deployed the Apache Kafka cluster won’t expose
any external listeners – the cluster will be unreachable.
Ports are only opened when client applications are integrated.

However, it is always possible to run a command from within the Apache Kafka cluster
using the internal listeners and ports in place of the external ones.
See [Apache Kafka listeners reference](reference-broker-listeners) page.

To connect to a running Charmed Apache Kafka K8s unit and run a command,
for example listing files in a directory:

```shell
juju ssh --container kafka kafka-k8s/leader "ls /opt/kafka/bin/"
```

where the printed result will be the output from the `ls \$BIN/bin` command being
executed on the `kafka-k8s` leader unit.

The Charmed Apache Kafka K8s image ships with the Apache Kafka `bin/*.sh` scripts,
that can be found under `/opt/kafka/bin/`. They can be used to do various administrative tasks,
for example, `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh`
for topic management, etc. See [Apache Kafka documentation](https://kafka.apache.org/41/operations/basic-kafka-operations/).
Within the image you can also find a `client.properties` file that already provides
the relevant settings to connect to the cluster using the CLI.

We will need a bootstrap server Apache Kafka broker address and port to initially connect to.

```{note}
When any application connects for the first time to a bootstrap server,
the client will automatically make a metadata request that returns the full set of Apache Kafka brokers
with their addresses and ports.
```

Use `kafka-k8s/0` as a bootstrap server, retrieve its IP address and export it with a port as a variable:

```shell
bootstrap_address=$(juju show-unit kafka-k8s/0 | yq -r '.[] | .address // ""' | sed '/^$/d')
export BOOTSTRAP_SERVER=$bootstrap_address:19093
```

where `19093` refers to the available open internal port on the broker unit.

Now, use the administrative scripts from the Charmed Apache Kafka K8s image.
For example, create a topic:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --create --topic test_topic \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```

Then, list all topic:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --list \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```

Make sure the topic we created earlier is in the list.
Finally, delete the topic from earlier:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --delete \
    --topic test_topic \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```

Now we have Apache Kafka cluster installed and tested.

Next, continue to the following page to connect using client applications.
