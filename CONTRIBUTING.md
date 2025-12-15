# Contributing

## Overview

This documents explains the processes and practices recommended for contributing enhancements to this operator.

- Generally, before developing enhancements to this charm, you should consider [opening an issue](https://github.com/canonical/kafka-operator/issues) explaining your problem with examples, and your desired use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju administrators this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Requirements

To build the charm locally, you will need to install
[Charmcraft](https://juju.is/docs/sdk/install-charmcraft).

To run the charm locally with Juju, it is recommended to use
[Multipass](https://canonical.com/multipass) and [MicroK8s](https://canonical.com/microk8s).

## Build and Deploy

To build the charm in this repository, from the root of the dir you can run:
Once you have Juju set up locally, to download, build and deploy the charm you can run:

### Deploy

```bash
# Clone and enter the repository
git clone https://github.com/canonical/kafka-k8s-operator.git
cd kafka-k8s-operator/

# Create a working model
juju add-model kafka-k8s

# Enable DEBUG logging for the model
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Build the charm locally
charmcraft pack

# Deploy the charm
juju deploy ./*.charm \
  --trust \
  -n 3 \
  --config roles="broker,controller" \
  --resource kafka-image=$(yq -r '."resources"."kafka-image"."upstream-source"' metadata.yaml) 
```

## Developing

You can create an environment for development with `tox`:

```shell
tox devenv -e integration
source venv/bin/activate
```

### Testing

```shell
tox run -e format        # update your code according to linting rules
tox run -e lint          # code style
tox run -e unit          # unit tests
tox run -e integration   # integration tests
tox                      # runs 'lint' and 'unit' environments
```

## Documentation

Product documentation is stored in this repository under the `docs` folder and published on ReadtheDocs.

1. Create a branch (either in the main repo or in a fork) from the current `main` and modify documentation files as necessary.
2. Raise a PR against the `main` to start the review process, and conduct the code review within the PR before merging back to the `main`.

### Terminology

Apache®, [Apache Kafka, Kafka®](https://kafka.apache.org/), [Apache ZooKeeper, ZooKeeper™](https://zookeeper.apache.org/) and their respective logos are either registered trademarks or trademarks of the [Apache Software Foundation](https://www.apache.org/) in the United States and/or other countries.

For documentation in this repository the following conventions are applied (see the table below).

| Full form | Alternatives | Incorrect examples |
| -------- | ------- | ------- |
| Apache Kafka | | Kafka |
| Charmed Apache Kafka K8s | | Charmed Kafka K8s, Charmed Kafka |
| Kafka Connect | | Kafka connect |
| Apache Kafka brokers | | Kafka brokers, Apache Kafka Brokers |
| Apache Kafka cluster | | Charmed Apache Kafka cluster |

The full form must be used at least once per page.
The full form must be used at the first entry to the page’s headings, body of text, callouts, and graphics.
For subsequent usage, the full form can be substituted by alternatives.

## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed Apache Kafka K8s.
Please check out our [contributor agreement](https://ubuntu.com/legal/contributors)
if you're interested in contributing to the solution.
