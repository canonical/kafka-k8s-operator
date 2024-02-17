This is part of the [Charmed Kafka K8s Tutorial](/t/charmed-kafka-k8s-documentation-tutorial-overview/11945). Please refer to this page for more information and the overview of the content.

## Cleanup your environment
If you're done with testing and would like to free up resources on your machine, just remove Multipass VM.

> **Warning** When you remove VM as shown below you will lose all the data in Kafka and any other applications inside Multipass VM!

```shell
multipass delete --purge my-vm
```

## What's next?

In this tutorial we've successfully deployed Kafka, added/removed users, connected client applications and even enabled and disabled TLS. 
If you're looking for what to do next you can:
- Run [Charmed Kafka on VMs](https://github.com/canonical/kafka-operator).
- Check out our Charmed offerings of [MySQL](https://charmhub.io/mysql-k8s), [PostgreSQL](https://charmhub.io/postgresql-k8s), [MongoDB](https://charmhub.io/mongodb-k8s).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-k8s-operator/issues) any problems you encountered.
- [Give us your feedback](https://chat.charmhub.io/charmhub/channels/data-platform).
- [Contribute to the code base](https://github.com/canonical/kafka-k8s-operator)