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

## Access Apache Kafka brokers

Charmed Apache Kafka K8s aims to follow the secure by default paradigm.
As a consequence, after being deployed the Apache Kafka cluster won’t expose
any external listeners – the cluster will be unreachable.
Ports are only opened when client applications are integrated.

For most cluster administrators, it may be most helpful to create a user
with the admin role, which has superuser permissions on the Apache Kafka cluster.

### Create an admin user

To create an admin user, deploy the
[Data Integrator Charm](https://charmhub.io/data-integrator)
with the `extra-user-roles` set to `admin`:

```shell
juju deploy data-integrator --config topic-name="__admin-user" --config extra-user-roles="admin"
```

Then, integrate it with the Apache Kafka charm:

```shell
juju integrate data-integrator kafka-k8s
```

Check `juju status` and wait for the new charmed application to be deployed and integrated with the `idle`/`active` status.

Retrieve authentication information:

```shell
juju run data-integrator/leader get-credentials
```

That will return `username` and `password`, as well as endpoints.

<details>

<summary>Output example</summary>

The output of the previous command will look something like this:

```shell
Running operation 5 with 1 task
  - task 6 on unit-data-integrator-0

Waiting for task 6...
kafka:
  data: '{"resource": "__admin-user", "salt": "C9qptFtwVMLmqVDp", "extra-user-roles":
    "admin", "provided-secrets": ["mtls-cert"], "requested-secrets": ["username",
    "password", "tls", "tls-ca", "uris", "read-only-uris"]}'
  endpoints: kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092
  password: 6OtdPWzEM336uR0FMzU9O38YnQnxhfgE
  resource: __admin-user
  salt: rsbLcRVkIldhuWLf
  tls: disabled
  topic: __admin-user
  username: relation-8
  version: v0
ok: "True"
```

</details>

### Bootstrap server

```{caution}
When no other application is integrated to Charmed Apache Kafka K8s,
the cluster is secured-by-default and external listeners (bound to port `9092`) are disabled,
thus preventing any external incoming connection. 
```

We will also need a bootstrap server Apache Kafka broker address and port to initially connect to.
When any application connects for the first time to a bootstrap server,
the client will automatically make a metadata request that returns the full set of Apache Kafka brokers
with their addresses and ports.

To use `kafka-k8s/0` as a bootstrap server, retrieve its IP address and add a port, export as a variable:

```shell
bootstrap_address=$(juju show-unit kafka-k8s/0 | yq -r '.[] | .address // ""' | sed '/^$/d')
export BOOTSTRAP_SERVER=$bootstrap_address:19093
```

where `19093` refers to the available open internal port on the broker unit.

### Connect from inside

It is always possible to run a command from within the Apache Kafka cluster using the internal
listeners and ports in place of the external ones. For an explanation of Charmed Apache Kafka K8s
listeners, please refer to [Apache Kafka listeners](reference-broker-listeners).

To jump in to a running Charmed Apache Kafka K8s unit and run a command,
for example listing files in a directory, you can do the following:

```shell
juju ssh --container kafka kafka-k8s/leader "ls /opt/kafka/bin/"
```

where the printed result will be the output from the `ls \$BIN/bin` command being
executed on the `kafka-k8s` leader unit.

The Charmed Apache Kafka K8s image ships with the Apache Kafka `bin/*.sh` commands,
that can be found under `/opt/kafka/bin/`. They can be used to do various administrative tasks,
for example, `bin/kafka-config.sh` to update cluster configuration, `bin/kafka-topics.sh`
for topic management, etc.
Within the image you can also find a `client.properties` file that already provides
the relevant settings to connect to the cluster using the CLI.

For example, in order to create a topic, you can run:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --create --topic test_topic \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```

You can similarly then list the topic, using:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --list \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```

making sure the topic was successfully created.

You can finally delete the topic, using:

```shell
juju ssh --container kafka kafka-k8s/0 \
    "/opt/kafka/bin/kafka-topics.sh --delete \
    --topic test_topic \
    --bootstrap-server $BOOTSTRAP_SERVER \
    --command-config /etc/kafka/client.properties"
```
