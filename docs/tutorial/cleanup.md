(tutorial-cleanup)=
# 8. Cleanup your environment

This is part of the [Charmed Apache Kafka K8s Tutorial](index.md). Please refer to this page for more information and an overview of the content.

## Remove Multipass VM

```{caution}
Removing Multipass VM as shown below you will delete all the data in Apache Kafka and any other applications inside it!
```

To remove Multipass VM:

```shell
multipass delete --purge my-vm
```

## What's next?

In this tutorial, we've successfully deployed Apache Kafka, added/removed users, connected client applications and even enabled and disabled TLS. 
If you're looking for what to do next you can:

- Run [Charmed Apache Kafka on VMs](https://github.com/canonical/kafka-operator).
- Check out our Charmed offerings of [MySQL](https://charmhub.io/mysql-k8s), [PostgreSQL](https://charmhub.io/postgresql-k8s), [MongoDB](https://charmhub.io/mongodb-k8s).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/kafka-k8s-operator/issues) any problems you encountered.
- [Give us your feedback](https://matrix.to/#/#charmhub-data-platform:ubuntu.com).
- [Contribute to the code base](https://github.com/canonical/kafka-k8s-operator)
