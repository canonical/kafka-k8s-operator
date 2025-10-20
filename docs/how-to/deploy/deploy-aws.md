(how-to-deploy-deploy-on-aws)=
# How to deploy on AWS

[Amazon Web Services](https://aws.amazon.com/) is a popular subsidiary of Amazon that provides on-demand cloud computing platforms on a metered pay-as-you-go basis. Access the AWS web console at [{spellexception}`console.aws.amazon.com`](https://console.aws.amazon.com/).

## Install AWS and Juju tooling

Install Juju via snap:

```shell
sudo snap install juju
```

Follow the [AWS documentation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) for guidance on how to install the Amazon Web Services CLI.

To check whether both Juju and AWS CLI are correctly installed, run commands to display their versions:

```shell
juju version
aws --version
```

<details>

<summary> Output example</summary>

```text
3.5.4-genericlinux-amd64
aws-cli/2.13.25 Python/3.11.5 Linux/6.2.0-33-generic exe/x86_64.ubuntu.23 prompt/off
```

</details>

### Authenticate

[Create an IAM account](https://docs.aws.amazon.com/eks/latest/userguide/getting-started-console.html) or use legacy user access keys and secret key to operate AWS EC2:

```shell
mkdir -p ~/.aws && cat <<- EOF >  ~/.aws/credentials.yaml
credentials:
  aws:
    NAME_OF_YOUR_CREDENTIAL:
      auth-type: access-key
      access-key: SECRET_ACCESS_KEY_ID
      secret-key: SECRET_ACCESS_KEY_VALUE
EOF
```

## Bootstrap Juju controller on AWS EC2

Add AWS credentials to Juju:

```shell
juju add-credential aws -f ~/.aws/credentials.yaml
```

Bootstrap Juju controller ([check all supported configuration options](https://juju.is/docs/juju/amazon-ec2)):

```shell
juju bootstrap aws <CONTROLLER_NAME>
```

<details>

<summary> Output example</summary>

```text
Creating Juju controller "aws-us-east-1" on aws/us-east-1
Looking for packaged Juju agent version 3.5.4 for amd64
Located Juju agent version 3.5.4-ubuntu-amd64 at https://juju-dist-aws.s3.amazonaws.com/agents/agent/3.5.4/juju-3.5.4-linux-amd64.tgz
Launching controller instance(s) on aws/us-east-1...
 - i-0f4615983d113166d (arch=amd64 mem=8G cores=2)           
Installing Juju agent on bootstrap instance
Waiting for address
Attempting to connect to 54.226.221.6:22
Attempting to connect to 172.31.20.34:22
Connected to 54.226.221.6
Running machine configuration script...
Bootstrap agent now started
Contacting Juju controller at 54.226.221.6 to verify accessibility...

Bootstrap complete, controller "aws-us-east-1" is now available
Controller machines are in the "controller" model

Now you can run
	juju add-model <model-name>
to create a new model to deploy workloads.
```

</details>

## Deploy charms

Create a new Juju model, if needed:

```shell
juju add-model <MODEL_NAME>
```

```{caution}
(Optional) Increase the debug level if you are troubleshooting charms:
```shell
juju model-config logging-config='<root>=INFO;unit=DEBUG'
```
```

Deploy Charmed Apache Kafka K8s:

```shell
juju deploy kafka -n 3 --config roles=broker,controller [--constraints "instance-type=<INSTANCE_TYPE>"]
```

```{caution}
The smallest AWS instance types may not provide sufficient resources to host an Apache Kafka broker. We recommend choosing an instance type with a minimum of `8` GB of RAM and `4` CPU cores, such as `m7i.xlarge`.

For more guidance on sizing production environments, see the [Requirements page](reference-requirements). Additional information about AWS instance types is available in the [AWS documentation](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=running).
```

We also recommend to deploy a [Data Integrator](https://charmhub.io/data-integrator) for creating an admin user to manage the content of the Kafka cluster:

```shell
juju deploy data-integrator \
  --config extra-user-roles=admin \
  --config topic-name=__admin-user
```

And integrate it with the Kafka application:

```shell
juju integrate kafka data-integrator
```

For more information on Data Integrator and how to use it, please refer to the [how-to manage client connections](how-to-client-connections) guide.

## Clean up

```{caution}
Always clean AWS resources that are no longer necessary! Abandoned resources are tricky to detect and they can become expensive over time.
```

To list all controllers that have been registered to your local client, use the `juju controllers` command.

To destroy the Juju controller and remove AWS instance (**Warning**: all your data will be permanently deleted):

```shell
juju destroy-controller <CONTROLLER_NAME> --destroy-all-models --destroy-storage --force
```

Should the destroying process take a long time or be seemingly stuck, proceed to delete EC2 resources also manually 
via the AWS portal. See [Amazon AWS documentation](https://repost.aws/knowledge-center/terminate-resources-account-closure) for more information 
on how to remove active resources no longer needed.

After destroying the controller, check and manually delete all unnecessary AWS EC2 instances, to show the list of all your EC2 instances run the following command (make sure to use the correct region):

```shell
aws ec2 describe-instances --region us-east-1 --query "Reservations[].Instances[*].{InstanceType: InstanceType, InstanceId: InstanceId, State: State.Name}" --output table
```

<details>

<summary> Output example</summary>

```text
-------------------------------------------------------
|                  DescribeInstances                  |
+---------------------+----------------+--------------+
|     InstanceId      | InstanceType   |    State     |
+---------------------+----------------+--------------+
|  i-0f374435695ffc54c|  m7i.xlarge    |  terminated  |
|  i-0e1e8279f6b2a08e0|  m7i.xlarge    |  terminated  |
|  i-061e0d10d36c8cffe|  m7i.xlarge    |  terminated  |
|  i-0f4615983d113166d|  m7i.xlarge    |  terminated  |
+---------------------+----------------+--------------+
```

</details>

List your Juju credentials with the `juju credentials` command:

```shell
...
Client Credentials:
Cloud        Credentials
aws          NAME_OF_YOUR_CREDENTIAL
...
```

Remove AWS EC2 CLI credentials from Juju:

```shell
juju remove-credential aws NAME_OF_YOUR_CREDENTIAL
```

Finally, remove AWS CLI user credentials (to avoid forgetting and leaking):

```shell
rm -f ~/.aws/credentials.yaml
```
