# Security hardening guide

This document provides guidance and instructions to achieve 
a secure deployment of [Charmed Kafka K8s](https://github.com/canonical/kafka-k8s-bundle), including setting up and managing a secure environment.
The document is divided into the following sections:

1. Environment, outlining the recommendation for deploying a secure environment
2. Applications, outlining the product features that enable a secure deployment of a Kafka cluster
3. Additional resources, providing any further information about security and compliance

## Environment

The environment where applications operate can be divided in two components:

1. Kubernetes
2. Juju 

### Kubernetes

Charmed Spark can be deployed on top of several Kubernetes distributions. 
The following table provides references for the security documentation for the 
main supported cloud platforms.

| Cloud              | Security guide                                                                                                                                                                                                                                                                                                                                   |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Charmed Kubernetes | [Security in Charmed Kubernetes](https://ubuntu.com/kubernetes/docs/security)                                                                                                                                                                                                                                                                    |
| AWS EKS            | [Best Practices for Security, Identity and Compliance](https://aws.amazon.com/architecture/security-identity-compliance), [AWS security credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/security-creds.html#access-keys-and-secret-access-keys), [Security in EKS](https://docs.aws.amazon.com/eks/latest/userguide/security.html) | 
| Azure              | [Azure security best practices and patterns](https://learn.microsoft.com/en-us/azure/security/fundamentals/best-practices-and-patterns), [Managed identities for Azure resource](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/), [Security in AKS](https://learn.microsoft.com/en-us/azure/aks/concepts-security)                                                      |

### Juju 

Juju is the component responsible for orchestrating the entire lifecycle, from deployment to Day 2 operations, of 
all applications. Therefore, Juju must be set up securely. For more information, see the
[Juju security page](/t/juju-security/15684) and the [How to harden your deployment guide](https://juju.is/docs/juju/harden-your-deployment).

#### Cloud credentials

When configuring the cloud credentials to be used with Juju, ensure that the users have correct permissions to operate at the required level on the Kubernetes cluster. 
Juju superusers responsible for bootstrapping and managing controllers require elevated permissions to manage several kind of resources. For this reason, the 
K8s user used for bootstrapping and managing the deployments should have full permissions, such as: 

* create, delete, patch, and list:
    * namespaces
    * services
    * deployments
    * stateful sets
    * pods
    * PVCs

In general, it is common practice to run Juju using the admin role of K8s, to have full permissions on the Kubernetes cluster. 

#### Juju users

It is very important that juju users are set up with minimal permissions depending on the scope of their operations. 
Please refer to the [User access levels](https://juju.is/docs/juju/user-permissions) documentation for more information on the access level and corresponding abilities 
that the different users can be granted. 

Juju user credentials must be stored securely and rotated regularly to limit the chances of unauthorized access due to credentials leakage.

## Applications

In the following we provide guidance on how to harden your deployment using:

1. Base images
2. Charmed operator security upgrades
3. Encryption 
4. Authentication
5. Monitoring and auditing

### Base images

Charmed Kafka K8s and Charmed ZooKeeper K8s run on top of rockcraft-based image shipping the Apache Kafka and Apache ZooKeeper 
distribution binaries built by Canonical, and available in the [Kafka release page](https://launchpad.net/kafka-releases) and 
[ZooKeeper release page](https://launchpad.net/zookeeper-releases), respectively. Both images are based on Ubuntu 22.04. 
The images that can be found in the [Charmed Kafka rock](https://github.com/canonical/charmed-spark-rock) and 
[Charmed ZooKeeper rock](https://github.com/canonical/charmed-zookeeper-rock) Github repositories are used as the base 
images for the different pods providing Kafka and ZooKeeper services. 
The following table summarise the relation between the component and its underlying base image. 

| Component         | Image                                                                                                 |
|-------------------|-------------------------------------------------------------------------------------------------------|
| Charmed Kafka     | [`charmed-kafka`](https://github.com/orgs/canonical/packages/container/package/charmed-kafka)         |
| Charmed ZooKeeper | [`charmed-zookeeper`](https://github.com/orgs/canonical/packages/container/package/charmed-zookeeper) |

New versions of Charmed Kafka and Charmed ZooKeeper images may be released to provide patching of vulnerabilities (CVEs). 

### Charmed operator security upgrades

Charmed Kafka K8s and Charmed ZooKeeper K8s operators install a pinned revision of the images outlined in the previous table 
in order to provide reproducible and secure environments. 
New versions of Charmed Kafka K8s and Charmed ZooKeeper K8s operators may therefore be released to provide patching of vulnerabilities (CVEs). 
It is important to refresh the charm regularly to make sure the workload is as secure as possible. 
For more information on how to refresh the charm, see the [how-to refresh](/t/charmed-kafka-k8s-documentation-how-to-upgrade/13267) user guide.

### Encryption

Charmed Kafka K8s must be deployed with encryption enabled. 
To do that, you need to relate Kafka and ZooKeeper charms to one of the TLS certificate operator charms. 
Please refer to the [Charming Security page](https://charmhub.io/topics/security-with-x-509-certificates) for more information on how to select the right certificate
provider for your use-case. 

For more information on encryption setup, see the [How to enable encryption](/t/charmed-kafka-k8s-how-to-enable-encryption/10289) guide.

### Authentication

Charmed Kafka supports the following authentication layers:

1. [SCRAM-based SASL Authentication](/t/charmed-kafka-k8s-how-to-manage-app/10293)
2. [certificate-base Authentication (mTLS)](/t/create-mtls-client-credentials/11079)
3. OAuth Authentication using [Hydra](/t/how-to-connect-to-kafka-using-hydra-as-oidc-provider/14610) or [Google](/t/how-to-connect-to-kafka-using-google-as-oidc-provider/14611)

Each combination of authentication scheme and encryption is associated to the dedicated listener and it maps to a well-defined port. 
Please refer to the [listener reference documentation](/t/charmed-kafka-k8s-documentation-reference-listeners/13270) for more information. 

### Monitoring and Auditing

Charmed Kafka provides native integration with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To reduce the blast radius of infrastructure disruptions, the general recommendation is to deploy COS and the observed application into 
separate environments, isolated one another. Refer to the [COS production deployments best practices](https://charmhub.io/topics/canonical-observability-stack/reference/best-practices)
for more information. 

Refer to How-To user guide for more information on:
* [how to integrate the Charmed Kafka deployment with COS](/t/charmed-kafka-k8s-how-to-enable-monitoring/10291)
* [how to customise the alerting rules and dashboards](/t/charmed-kafka-k8s-documentation-how-to-integrate-custom-alerting-rules-and-dashboards/13528)

External user access to Kafka is logged to the `kafka-authorizer.log` that is pushes to [Loki endpoint](https://charmhub.io/loki-k8s) and exposed via [Grafana](https://charmhub.io/grafana), both components being part of the COS stack.
Access denials are logged at INFO level, whereas allowed accesses are logged at DEBUG level. Depending on the auditing needs, 
customize the logging level either for all logs via the [`log_level`](https://charmhub.io/kafka-k8s/configurations?channel=3/stable#log_level) config option or 
only tune the logging level of the `authorizerAppender` in the `log4j.properties` file. Refer to the Reference documentation, for more information about 
the [file system paths](/t/charmed-kafka-k8s-documentation-reference-file-system-paths/13269).

## Additional Resources

For further information and details on the security and cryptographic specifications used by Charmed Kafka, please refer to the [Security Explanation page](/t/charmed-kafka-k8s-documentation-explanation-security/15715).