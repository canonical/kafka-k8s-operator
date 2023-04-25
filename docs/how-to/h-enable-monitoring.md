# Enable Monitoring

The Charmed Kafka K8s Operator comes with several exporters by default. The metrics can be queried by accessing the following endpoints:

- JMX exporter: `http://<pod-ip>:9101/metrics`

Additionally, the charm provides integration with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

Deploy `cos-lite` bundle in a Kubernetes environment. This can be done by following the [deployment tutorial](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s). It is needed to offer the endpoints of the COS relations. The [offers-overlay](https://github.com/canonical/cos-lite-bundle/blob/main/overlays/offers-overlay.yaml) can be used, and this step is shown on the COS tutorial.

Once COS is deployed, we can find the offers from the Kafka model:
```shell
# We are on the `cos` model. Switch to `kafka` model
juju switch <kafka_model_name>

juju find-offers <k8s_controller_name>:
```

A similar output should appear, if `micro` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:
```
Store  URL                   Access  Interfaces                         
micro  admin/cos.grafana     admin   grafana_dashboard:grafana-dashboard
micro  admin/cos.prometheus  admin   prometheus_scrape:metrics-endpoint
. . .
```

Now, integrate kafka with the `metrics-endpoint`, `grafana-dashboard` and `logging` relations:
```shell
juju relate micro:admin/cos.prometheus kafka-k8s
juju relate micro:admin/cos.grafana kafka-k8s
juju relate micro:admin/cos.loki kafka-k8s
```

After this is complete, Grafana will show a new dashboard: `Kafka JMX Metrics`