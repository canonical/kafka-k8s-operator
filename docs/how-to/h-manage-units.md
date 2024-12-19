# How to manage units

Unit management guide for scaling and running admin utility scripts.

## Replication and scaling

Increasing the number of Apache Kafka brokers can be achieved by adding more units
to the Charmed Apache Kafka K8s application:

```shell
juju add-unit kafka-k8s -n <num_brokers_to_add>
```

For more information on how to manage units, please refer to the [Juju documentation](https://juju.is/docs/juju/manage-units)

It is important to note that when adding more units, the Apache Kafka cluster will not 
*automatically* rebalance existing topics and partitions. New storage and new brokers
will be used only when new topics and new partitions are created. 

Partition reassignment can still be done manually by the admin user by using the 
`/opt/kafka/bin/kafka-reassign-partitions.sh` Apache Kafka bin utility script. Please refer to the
[Apache Kafka documentation](https://kafka.apache.org/documentation/#basic_ops_partitionassignment) for more information on the script usage. 

[note type="caution"]
Scaling down is currently not supported in the charm automation.  
If partition reassignment is not manually performed before scaling down in order 
to make sure the decommissioned units do not hold any data, **your cluster may 
suffer to data loss**. 
[/note]

## Running Apache Kafka admin utility scripts

Apache Kafka ships with `bin/*.sh` commands to do various administrative tasks such as:

* `bin/kafka-config.sh` to update cluster configuration
* `bin/kafka-topics.sh` for topic management
* `bin/kafka-acls.sh` for management of ACLs of Apache Kafka users

Please refer to the upstream [Apache Kafka project](https://github.com/apache/kafka/tree/trunk/bin) or its [documentation](https://kafka.apache.org/documentation/#basic_ops), 
for a full list of the bash commands available in Apache Kafka distributions. Also, you can 
use `--help` argument for printing a short summary of the argument for a given 
bash command. 

These scripts can be found in the `/opt/kafka/bin` folder of the workload container.

[note type="caution"]
Before running bash scripts, make sure that some listeners have been correctly 
opened by creating appropriate integrations. Please refer to [this table](/t/charmed-kafka-k8s-documentation-reference-listeners/13270) for more 
information about how listeners are opened based on integrations. To simply open a 
SASL/SCRAM listener, just integrate a client application using the data integrator, 
as described in the [How to manage app guide](/t/charmed-kafka-k8s-how-to-manage-app/10293).
[/note]

To run most of the scripts, you need to provide:

1. the Apache Kafka service endpoints, generally referred to as *bootstrap servers* 
2. authentication information 

### Juju admins of the Apache Kafka deployment

For Juju admins of the Apache Kafka deployment, the bootstrap servers information can 
be obtained using the `get-admin-credentials` action output:

```
BOOTSTRAP_SERVERS=$(juju run kafka-k8s/leader get-admin-credentials | grep "bootstrap.servers" | cut -d "=" -f 2)
```

Admin client authentication information is stored in the 
`/etc/kafka/client.properties` file that is present on every Apache Kafka
container. The content of the file can be accessed using `juju ssh` command:

```
juju ssh --container kafka kafka-k8s/leader 'cat /etc/kafka/client.properties'
```

where `--container kafka` is to select the Apache Kafka workload container of the unit. By default, the charm operator container is opened.

This file can be provided to the Apache Kafka bin commands via the `--command-config`
argument. Note that `client.properties` may also refer to other files (
e.g. truststore and keystore for TLS-enabled connections). Those
files also need to be accessible and correctly specified. 

Commands can be run within a Apache Kafka broker, since both the authentication 
file (along with the truststore if needed) and the Charmed Apache Kafka binaries are 
already present. 

#### Example (listing topics)

For instance, to list the current topics on the Apache Kafka cluster, you can run:

```shell
juju ssh --container kafka kafka-k8s/leader '/opt/kafka/bin/kafka-topics.sh --bootstrap-server $BOOTSTRAP_SERVERS --list --command-config /etc/kafka/client.properties'
```

As long as `BOOTSTRAP_SERVERS` variable contains the information we retrieved earlier in the **Juju admins of the Apache Kafka deployment** section.

For example, a full command without the usage of the variable might look like the following:

```shell
juju ssh --container kafka kafka-k8s/leader '/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-3.kafka-k8s-endpoints:9092 --list --command-config /etc/kafka/client.properties'
```

where `kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-3.kafka-k8s-endpoints:9092` - is the contents of the `$BOOTSTRAP_SERVERS` variable.

### Juju external users

For external users managed by the  [Data Integrator Charm](https://charmhub.io/data-integrator), 
the endpoints and credentials can be fetched using the dedicated action:

```shell
juju run data-integrator/leader get-credentials --format yaml
```

The `client.properties` file can be generated by substituting the relevant information in the 
file available on the brokers at `/etc/kafka/client.properties`.

To do so, fetch the information using `juju` commands:

```
BOOTSTRAP_SERVERS=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.endpoints )
USERNAME=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.username )
PASSWORD=$(juju run data-integrator/leader get-credentials --format yaml | yq .kafka.password )
```

Then copy the `/etc/kafka/client.properties` and substitute the following lines:

```
...
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="<USERNAME>" password="<PASSWORD>";
...
bootstrap.servers=<BOOTSTRAP_SERVERS>
```