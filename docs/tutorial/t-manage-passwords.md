# Manage Passwords

This is part of the [Charmed Kafka K8s Tutorial](/t/charmed-kafka-k8s-documentation-tutorial-overview/11945). Please refer to this page for more information and the overview of the content.

## Passwords

When we accessed Kafka earlier in this tutorial, we needed to include a password in the connection parameters. 
Passwords help to secure our cluster and are essential for security. Over time, it is a good practice to change the password frequently. Here we will go through setting and changing the password for the admin user.

### Kafka cluster admin

### Retrieve the password
As previously mentioned, the admin password can be retrieved by running the `get-admin-credentials` action on the Charmed Kafka application:
```shell
juju run kafka-k8s/leader get-admin-credentials
```
Running the command should output:
```shell 
Running operation 12 with 1 task
  - task 13 on unit-kafka-k8s-2

Waiting for task 13...
client-properties: |-
  sasl.mechanism=SCRAM-SHA-512
  sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp";
  security.protocol=SASL_PLAINTEXT
  bootstrap.servers=kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092
password: 0FIQ5QxSaNfl1bXHtV5dyttb21Nbzmpp
username: admin
```
The admin password is under the result: `password`.

### Rotate the admin password
You can change the admin password to a new random password by entering:
```shell
juju run kafka-k8s/leader set-password username=admin
```
Running the command should output:
```shell
Running operation 14 with 1 task
  - task 15 on unit-kafka-k8s-2

Waiting for task 15...
admin-password: Fz6wPkfGtgjnQ3PCJuZnzJESudZkAvrV
```
The admin password is under the result: `admin-password`. It should be different from your previous password.

*Note when you change the admin password you will also need to update the admin password the in Kafka connection parameters; as the old password will no longer be valid.*

### Set the admin password
You can change the admin password to a specific password by entering:
```shell
juju run kafka-k8s/leader set-password username=admin password=my-new-password
```
Running the command should output:
```shell
Running operation 18 with 1 task
  - task 19 on unit-kafka-k8s-2

Waiting for task 19...
admin-password: my-new-password
```
The admin password under the result: `admin-password` should match the password we provided as the action argument. 

*Note that when you change the admin password you will also need to update the admin password in the Kafka connection parameters, as the old password will no longer be valid.*


### Kafka Users

As mentioned in the previous section of the Tutorial, the recommended way to create and manage users is by means of the data-integrator charm. 
This will allow us to encode users directly in the Juju model, and - as shown in the following - to rotate user credentials rotations with and without application downtime.   

### Retrieve the password

Similarly to the Kafka application, also the `data-integrator` exposes an action to retrieve the credentials, e.g. 
```shell
juju run data-integrator/leader get-credentials
```
Running the command should output:
```shell 
Running operation 22 with 1 task
  - task 23 on unit-data-integrator-0

Waiting for task 23...
kafka:
  endpoints: kafka-k8s-2.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-0.kafka-k8s-endpoints:9092
  password: S4IeRaYaiiq0tsM7m2UZuP2mSI573IGV
  tls: disabled
  topic: test-topic
  username: relation-6
  zookeeper-uris: zookeeper-k8s-0.zookeeper-k8s-endpoints:2181,zookeeper-k8s-1.zookeeper-k8s-endpoints:2181,zookeeper-k8s-2.zookeeper-k8s-endpoints:2181/kafka-k8s
ok: "True"
```

As before, the admin password is under the result: `password`.

### Rotate the password

#### With application downtime

The easiest way to rotate user credentials using the `data-integrator` is by removing and then re-relating the `data-integrator` with the `kafka-k8s` charm

```shell
juju remove-relation kafka-k8s data-integrator
# wait for the relation to be torn down 
juju relate kafka-k8s data-integrator
```

The successful credential rotation can be confirmed by retrieving the new password with the action `get-credentials`

```shell
juju run data-integrator/leader get-credentials
```
Running the command should now output a different password:
```shell 
Running operation 24 with 1 task
  - task 25 on unit-data-integrator-0

Waiting for task 25...
kafka:
  endpoints: kafka-k8s-0.kafka-k8s-endpoints:9092,kafka-k8s-1.kafka-k8s-endpoints:9092,kafka-k8s-2.kafka-k8s-endpoints:9092
  password: ToVfqYQ7tWmNmjy2tJTqulZHmJxJqQ22
  tls: disabled
  topic: test-topic
  username: relation-11
  zookeeper-uris: zookeeper-k8s-0.zookeeper-k8s-endpoints:2181,zookeeper-k8s-1.zookeeper-k8s-endpoints:2181,zookeeper-k8s-2.zookeeper-k8s-endpoints:2181/kafka-k8s
ok: "True"
```

#### Without application downtime

In some use-cases credentials should be rotated with no or limited application downtime.
In order to achieve this, you can deploy a new `data-integrator` with the same permissions and resource definition
```shell
juju deploy data-integrator rotated-user --channel stable \
  --config topic-name=test-topic --config extra-user-roles=admin
```

The `data-integrator` charm can then be related to the `kafka-k8s` charm to create a new user
```shell
juju relate kafka-k8s rotated-user
```

At this point, we effectively have two overlapping users, therefore allowing applications to swap the password
from one to another. 
If the applications consist of fleets of independent producers and consumers, user credentials can be rotated
progressively across fleets, such that no effective downtime is achieved. 

Once all applications have rotated their credentials, it is then safe to remove data first `data-integrator` charm

```shell
juju remove-application data-integrator
```