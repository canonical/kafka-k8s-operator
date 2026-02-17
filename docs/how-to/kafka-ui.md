(how-to-kafka-ui)=
# How to use Kafka UI

Administration of a Charmed Apache Kafka cluster can be performed using the Juju CLI and the utilities included with the Apache Kafka rock.
However, some administrators prefer to use a graphical user interface (GUI) to monitor the cluster and perform administrative tasks.
To support this, the Charmed Apache Kafka solution includes a charmed operator for [Kafbat's Kafka UI](https://github.com/kafbat/kafka-ui), which enables users to:

- View Apache Kafka cluster configuration, topics, ACLs, consumer groups and more
- Broker performance monitoring via JMX metrics dashboards
- Seamless integration with other Charmed Apache Kafka K8s operators, like [Charmed Apache Kafka Connect](https://charmhub.io/kafka-connect-k8s) and [Charmed Karapace](https://charmhub.io/karapace-k8s)

In this guide, you will:

- Deploy the Charmed Kafka UI K8s operator
- Connect it to Charmed Apache Kafka and related products
- Configure authentication and TLS to secure access to Kafka UI

## Prerequisites

This guide assumes you already have an Apache Kafka cluster deployed with the Charmed Apache Kafka K8s operator and the `ingress` relation provided by the [Traefik K8s operator](https://charmhub.io/traefik-k8s) via a cross-model [Juju offer](https://documentation.ubuntu.com/juju/latest/reference/offer/).

To deploy Apache Kafka cluster, follow the [Charmed Apache Kafka K8s Deployment guide](how-to-deploy-deploy-anywhere).

Moreover, the Kafka UI K8s operator requires an ingress relation, which can be provided by the [Traefik K8s operator](https://charmhub.io/traefik-k8s).
You can follow the documentation to deploy the Traefik K8s operator and enable ingress on your Juju K8s cluster.
To deploy [Traefik K8s operator](https://charmhub.io/traefik-k8s) and enable ingress on your Juju K8s cluster, follow the [documenation](https://documentation.ubuntu.com/traefik-k8s-charm/latest/).

For reference, a cluster with three brokers and three KRaft controllers produces `juju status` output similar to the following.
As described above, the ingress relation is available via the `traefik` offer.

<details>
<summary> Output example</summary>

```text
Model  Controller  Cloud/Region        Version  SLA          Timestamp
ui     k8s         microk8s/localhost  3.6.11   unsupported  07:52:33+01:00

SAAS           Status  Store  URL
traefik        active  k8s    admin/cos.traefik

App           Version  Status   Scale  Charm         Channel      Rev  Address         Exposed  Message
kafka-k8s     4.0.0    active       3  kafka-k8s     4/edge        96  10.152.183.212  no       
kraft         4.0.0    active       3  kafka-k8s     4/edge        96  10.152.183.38   no       

Unit             Workload  Agent  Address     Ports  Message
kafka-k8s/0*     active    idle   10.1.81.14         
kafka-k8s/1      active    idle   10.1.81.8          
kafka-k8s/2      active    idle   10.1.81.59         
kraft/0          active    idle   10.1.81.63         
kraft/1          active    idle   10.1.81.49         
kraft/2*         active    idle   10.1.81.61         
```

</details>

## Deploy charmed Kafka UI

To deploy the Kafka UI K8s charmed operator:

```bash
juju deploy kafka-ui-k8s --channel latest/edge --trust
```

Once the charmed Kafka UI K8s operator is deployed, it will end up in `blocked` state, since it needs to be integrated with a charmed Apache Kafka cluster. The output of `juju status` command will be like below:

```text
...
kafka-ui-k8s/0*  blocked   idle       10.1.81.21         application needs Kafka client relation
...
```

## Integrate Kafka UI with Apache Kafka and Ingress

To activate the Charmed Kafka UI application, integrate it with the Charmed Apache Kafka application:

```bash
juju integrate kafka-ui-k8s kafka-k8s
```

After a while, the Charmed Kafka UI K8s application should still be in `blocked` state, and reporting that it requires an ingress relation:

```text
...
kafka-ui-k8s/0*  blocked      idle       10.1.81.21         application needs ingress relation
...
```

To resolve that, integrate the Kafka UI application with the ingress offer consumed before:

```bash
juju integrate kafka-ui-k8s traefik
```

After a few seconds, the Charmed Kafka UI K8s application should be in `active|idle` state.

## Configure authentication

By default, the Charmed Kafka UI K8s application enables authentication for the internal `admin` user.
To change the admin password:

1. Create a Juju secret containing the new credentials
2. Configure the Charmed Kafka UI K8s application to use that secret

First, add a custom secret for the internal `admin` user with your desired password:

```bash
juju add-secret ui-secret admin='My$trongP4ss'
```

You will receive a secret ID in response, for example:

```text
secret:d5f0a07mp25c7654dhi0
```

Then, grant access to the secret with:

```bash
juju grant-secret ui-secret kafka-ui-k8s
```

Finally, configure the UI application to use the provided secret:

```bash
juju config kafka-ui-k8s system-users=secret:d5f0a07mp25c7654dhi0
```

## Access the Kafka UI

To retrieve the Kafka UI URL, use the [`show-proxied-endpoints`](https://charmhub.io/traefik-k8s/actions#show-proxied-endpoints) action of the Traefik K8s operator,
sample output is provided below:

```text
Running operation 26 with 1 task
  - task 27 on unit-traefik-0

Waiting for task 27...
proxied-endpoints: '{"traefik": {"url": "http://10.160.219.1"}, "prometheus/0": {"url":
  "http://10.160.219.1/cos-prometheus-0"}, "loki/0": {"url": "http://10.160.219.1/cos-loki-0"},
  "alertmanager": {"url": "http://10.160.219.1/cos-alertmanager"}, "catalogue": {"url":
  "http://10.160.219.1/cos-catalogue"}, "remote-3919ad00a430430781b28c4768f7a7ee":
  {"url": "http://10.160.219.1/ui-kafka-ui-k8s"}}'
```

Based on the output example above, the UI is available at the `"http://10.160.219.1/ui-kafka-ui-k8s` address, which can be accessed using a web browser.

Once opened in the web browser, you should see an authentication page prompting for username and password, in which you can use the `admin` username and the password configured before to log in.

Once logged in, you can use the left menu to access the brokers, KRaft controllers, topics, schemas, and connectors configuration along with various monitoring metrics.
To familiarise yourself with Kafbat's Kafka UI features, it is advised to consult the product's [official documentation](https://ui.docs.kafbat.io/).

## Integrate charmed Kafka UI with other products

The charmed Kafka UI K8s operator can integrate with other charmed operators, including the charmed Kafka Connect K8s and the charmed Karapace K8s operators.
For more information on these products and their use-cases, please refer to the
[How to use Kafka Connect for ETL workloads](how-to-use-kafka-connect) and
[Schemas and serialisation](how-to-schemas-serialisation) guides.

If you have followed aforementioned guides, you can integrate the charmed Kafka Connect and charmed Karapace applications with the Kafka UI using:

```bash
juju integrate kafka-ui-k8s kafka-connect-k8s
juju integrate kafka-ui-k8s karapace-k8s
```

Once all applications settle to `active|idle` state, you will have access to the Kafka Connect and Karapace configuration and current state via the `Kafka Connect` and `Schema Registry` menus in the Kafka UI web interface respectively. 
