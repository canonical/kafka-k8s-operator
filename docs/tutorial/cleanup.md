(tutorial-cleanup)=
# 9. Cleanup your environment

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

(remove-kafka-and-juju)=
## Remove Charmed Apache Kafka and Juju

If you're done using Charmed Apache Kafka and Juju and would like to free up resources on your machine, you can safely remove both.

```{caution}
Removing Charmed Apache Kafka as shown below will delete all the data in the Apache Kafka. Further, when you remove Juju as shown below you lose access to any other applications you have hosted on Juju.
```

To remove Charmed Apache Kafka and the model it is hosted on run the command:

```shell
juju destroy-model tutorial --destroy-storage --force
```

Next step is to remove the Juju controller. You can see all of the available controllers by entering `juju controllers`. To remove the controller enter:

```shell
juju destroy-controller overlord
```

Finally to remove Juju altogether, enter:

```shell
sudo snap remove juju --purge
```

## What's next?

In this tutorial, we've successfully deployed Apache Kafka, added/removed replicas, added/removed users to/from the cluster, and even enabled and disabled TLS.
You may now keep your Charmed Apache Kafka deployment running or remove it entirely using the steps in [Remove Charmed Apache Kafka and Juju](remove-kafka-and-juju).
If you're looking for what to do next you can:

- Run [Charmed Apache Kafka on Kubernetes](https://github.com/canonical/kafka-k8s-operator).
- Check out our other Charmed offerings from [Canonical's Data Platform team](https://canonical.com/data)
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-operator/issues) any problems you encountered.
- [Give us your feedback](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
- [Contribute to the code base](https://github.com/canonical/kafka-operator)

