(how-to-monitoring-integrate-alerts-and-dashboards)=
# Integrate custom alerting rules and dashboards

This guide shows you how to integrate an existing set of rules and/or dashboards to your Charmed Apache Kafka and Charmed Apache ZooKeeper deployment to be consumed with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack).
To do so, we will sync resources stored in a git repository to COS Lite.

## Prerequisites

Deploy the `cos-lite` bundle in a Kubernetes environment and integrate Charmed Apache Kafka and Charmed Apache ZooKeeper to the COS offers, as shown in the [How to Enable Monitoring](how-to-monitoring-enable-monitoring) guide.
This guide will refer to the models that charms are deployed into as:

* `<cos-model>` for the model containing observability charms (and deployed on K8s)

* `<apps-model>` for the model containing Charmed Apache Kafka and Charmed Apache ZooKeeper

* `<apps-model>` for other optional charms (e.g. TLS-certificates operators, `grafana-agent`, `data-integrator`, etc.).

## Create a repository with a custom monitoring setup

Create an empty git repository, or in an existing one, save your alert rules and dashboard models under the `<path_to_prom_rules>`, `<path_to_loki_rules>` and `<path_to_models>` folders.

If you want a primer to rule writing, refer to the [Prometheus documentation](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).  
You may also find an example in the [{spellexception}`kafka-test-app repository`](https://github.com/canonical/kafka-test-app).

Then, push your changes to the remote repository.

## Deploy the COS configuration charm

Deploy the [COS configuration](https://charmhub.io/cos-configuration-k8s) charm in the `<cos-model>` model:

```shell
juju deploy cos-configuration-k8s cos-config \
  --config git_repo=<repository_url> \
  --config git_branch=<branch> \
```

The COS configuration charm keeps the monitoring stack in sync with our repository, by forwarding resources to Prometheus, Loki and Grafana.
Refer to the [documentation](https://charmhub.io/cos-configuration-k8s/configure) for all configuration options, including how to access a private repository.  
Adding, updating or deleting an alert rule or a dashboard in the repository will be reflected in the monitoring stack.

```{note}
You need to manually refresh `cos-config`'s local repository with the *sync-now* action if you do not want to wait for the next [update-status event](https://documentation.ubuntu.com/juju/3.6/reference/hook/#update-status) to pull the latest changes.
```

## Forward the rules and dashboards

The path to the resource folders can be set after deployment:

```shell
juju config cos-config \
  --config prometheus_alert_rules_path=<path_to_prom_rules>
  --config loki_alert_rules_path=<path_to_loki_rules>
  --config grafana_dashboards_path=<path_to_models>
```

Then, integrate the charm to the COS operator to forward the rules and dashboards:

```shell
juju integrate cos-config prometheus
juju integrate cos-config grafana
juju integrate cos-config loki
```

After this is complete, the monitoring COS stack should be up, and ready to fire alerts based on our rules.
As for the dashboards, they should be available in the Grafana interface.

## Conclusion

In this guide, we enabled monitoring on a Charmed Apache Kafka deployment and integrated alert rules and dashboards by syncing a git repository to the COS stack.
