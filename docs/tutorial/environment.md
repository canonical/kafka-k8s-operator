(tutorial-environment)=
# 1. Set up the environment

This is a part of the [Charmed Apache Kafka K8s Tutorial](index.md).

## Setup the environment

For this tutorial, we will need to set up the environment with two main components,
and extra command-line tooling:

* [Multipass](https://multipass.run/) - is a quick and easy way to launch virtual machines running Ubuntu
* [Juju](https://github.com/juju/juju) - enables us to deploy and manage Charmed Apache Kafka K8s and integrated applications
* [yq](https://github.com/mikefarah/yq) - a command-line YAML processor
* [jq](https://github.com/jqlang/jq) - a command-line JSON processor

### Prepare Multipass

Let's install Multipass from [Snap](https://snapcraft.io/multipass) and launch a new VM using
"[{spellexception}`charm-dev`](https://github.com/canonical/multipass-blueprints/blob/main/v1/charm-dev.yaml)"
cloud-init configuration:

```shell
sudo snap install multipass && \
multipass launch --cpus 4 --memory 8G --disk 50G --name my-vm charm-dev
```

```{note}
See all `multipass launch` parameters in the
[launch command reference](https://multipass.run/docs/launch-command)*.
```

Multipass [list of commands](https://multipass.run/docs/multipass-cli-commands)
is short and self-explanatory, for example, to show all running VMs:

```shell
multipass list
```

As soon as the new VM starts, enter:

```shell
multipass shell my-vm
```

```{note}
If at any point you'd like to leave Multipass VM, use `Ctrl+D` or type `exit`.
```

### Prepare Juju

[Juju](https://juju.is/) is an Operator Lifecycle Manager (OLM) for clouds,
bare metal, LXD or Kubernetes.
We will be using it to deploy and manage Charmed Apache Kafka K8s.

All the parts have been pre-installed inside VM already, like MicroK8s, LXD and Juju
(the files `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` contain all
low-level installation details).
Also, the image already comes with two Juju controllers already setup,
one for LXD and one for MicroK8s

```shell
juju list-controllers
```

Make sure that you use the controller bound to the MicroK8s cluster, e.g.:

```shell
juju switch microk8s
```

The Juju controller can work with different models; models host applications such as
Charmed Apache Kafka K8s. Set up a specific model for Charmed Apache Kafka K8s named `tutorial`:

```shell
juju add-model tutorial
```

Check the model status with the `juju status` command.
For a newly created model, you should see the "Model XXX is empty" message.
