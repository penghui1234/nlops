"""NLOps CDK Stack.

Provisions:
  * API Gateway (REST) with /chat /voice /webhook
  * Entry Lambda (router/dispatcher)
  * Six Agent Lambdas (Router/Discovery/Analysis/Execution/Knowledge/Report)
  * S3 bucket for HTML reports (lifecycle to IA -> Glacier)
  * DynamoDB tables: sessions (TTL), audit (TTL)
  * SNS topic for notifications
  * IAM roles - one per Agent, least privilege
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from constructs import Construct

# Path to the src/ directory (sibling of infra/)
SRC_DIR = Path(__file__).resolve().parent.parent / "src"


class NLOpsStack(Stack):
    """Main stack for the NLOps platform."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # 1. Storage layer
        # ------------------------------------------------------------------ #
        report_bucket = s3.Bucket(
            self,
            "ReportBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        ),
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(365),
                        ),
                    ]
                )
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        sessions_table = ddb.Table(
            self,
            "SessionsTable",
            partition_key=ddb.Attribute(name="session_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        audit_table = ddb.Table(
            self,
            "AuditTable",
            partition_key=ddb.Attribute(name="trace_id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="ts", type=ddb.AttributeType.NUMBER),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------ #
        # 2. Notification topic
        # ------------------------------------------------------------------ #
        notify_topic = sns.Topic(self, "NotifyTopic", display_name="NLOps Notifications")

        # ------------------------------------------------------------------ #
        # 3. Common Lambda layer / shared env
        # ------------------------------------------------------------------ #
        common_env = {
            "REPORT_BUCKET": report_bucket.bucket_name,
            "SESSIONS_TABLE": sessions_table.table_name,
            "AUDIT_TABLE": audit_table.table_name,
            "NOTIFY_TOPIC_ARN": notify_topic.topic_arn,
            "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "BEDROCK_EMBED_MODEL": "amazon.titan-embed-text-v2:0",
            "LOG_LEVEL": "INFO",
        }

        code_asset = lambda_.Code.from_asset(str(SRC_DIR))

        # ------------------------------------------------------------------ #
        # 4. Agent Lambdas (one per Agent, distinct IAM roles)
        # ------------------------------------------------------------------ #
        agents = {}
        agent_specs = [
            ("Router",    "agents.router.handler",    self._router_policies()),
            ("Discovery", "agents.discovery.handler", self._discovery_policies()),
            ("Analysis",  "agents.analysis.handler",  self._analysis_policies()),
            ("Execution", "agents.execution.handler", self._execution_policies()),
            ("Knowledge", "agents.knowledge.handler", self._knowledge_policies()),
            ("Report",    "agents.report.handler",    self._report_policies(report_bucket)),
        ]

        for name, handler, policies in agent_specs:
            role = iam.Role(
                self,
                f"{name}AgentRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaBasicExecutionRole"
                    )
                ],
            )
            for stmt in policies:
                role.add_to_policy(stmt)

            fn = lambda_.Function(
                self,
                f"{name}AgentFn",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=code_asset,
                timeout=Duration.seconds(60),
                memory_size=512,
                role=role,
                environment=common_env,
            )
            agents[name] = fn

        # Allow Router to invoke all sub-agents
        for sub_name, sub_fn in agents.items():
            if sub_name == "Router":
                continue
            sub_fn.grant_invoke(agents["Router"])

        # Knowledge can be invoked by Analysis (Agent-as-Tool example)
        agents["Knowledge"].grant_invoke(agents["Analysis"])

        # ------------------------------------------------------------------ #
        # 5. Entry Lambda
        # ------------------------------------------------------------------ #
        entry_role = iam.Role(
            self,
            "EntryRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        sessions_table.grant_read_write_data(entry_role)
        audit_table.grant_write_data(entry_role)
        notify_topic.grant_publish(entry_role)
        agents["Router"].grant_invoke(entry_role)
        # Nova Sonic + Bedrock for ASR/TTS
        entry_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        entry_fn = lambda_.Function(
            self,
            "EntryFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.api_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=entry_role,
            environment={
                **common_env,
                "ROUTER_AGENT_FN": agents["Router"].function_name,
            },
        )

        # ------------------------------------------------------------------ #
        # 6. API Gateway
        # ------------------------------------------------------------------ #
        api = apigw.LambdaRestApi(
            self,
            "NLOpsApi",
            handler=entry_fn,
            proxy=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=200,
                throttling_rate_limit=100,
                metrics_enabled=True,
            ),
        )
        for path in ("chat", "voice", "webhook"):
            api.root.add_resource(path).add_method("POST")

        # ------------------------------------------------------------------ #
        # 7. CloudFormation Outputs
        # ------------------------------------------------------------------ #
        from aws_cdk import CfnOutput

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "ReportBucketName", value=report_bucket.bucket_name)
        CfnOutput(self, "NotifyTopicArn", value=notify_topic.topic_arn)

    # ====================================================================== #
    # Per-Agent IAM policies (least privilege)
    # ====================================================================== #
    @staticmethod
    def _bedrock_policy() -> iam.PolicyStatement:
        return iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:Retrieve",
                "bedrock:RetrieveAndGenerate",
            ],
            resources=["*"],
        )

    def _router_policies(self):
        return [self._bedrock_policy()]

    def _discovery_policies(self):
        return [
            self._bedrock_policy(),
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:DescribeLogGroups",
                    "xray:GetTraceSummaries",
                    "xray:BatchGetTraces",
                    "ec2:Describe*",
                    "ecs:Describe*",
                    "ecs:List*",
                    "rds:Describe*",
                    "elasticloadbalancing:Describe*",
                ],
                resources=["*"],
            ),
        ]

    def _analysis_policies(self):
        # Read-only across observability surfaces
        return [
            self._bedrock_policy(),
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:Get*",
                    "cloudwatch:List*",
                    "cloudwatch:Describe*",
                    "logs:Filter*",
                    "logs:Get*",
                    "xray:Get*",
                    "xray:BatchGet*",
                ],
                resources=["*"],
            ),
        ]

    def _execution_policies(self):
        # Write surface; constrained to a tag boundary in real deployments
        return [
            self._bedrock_policy(),
            iam.PolicyStatement(
                actions=[
                    "ecs:UpdateService",
                    "autoscaling:SetDesiredCapacity",
                    "autoscaling:UpdateAutoScalingGroup",
                    "rds:RebootDBInstance",
                    "ec2:RebootInstances",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:ResourceTag/nlops:managed": "true"}
                },
            ),
        ]

    def _knowledge_policies(self):
        return [
            self._bedrock_policy(),
            # Permissions to Bedrock KB will be granted via the KB resource
            # arn in production; using broad action set here for clarity.
            iam.PolicyStatement(
                actions=[
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "aoss:APIAccessAll",
                ],
                resources=["*"],
            ),
        ]

    def _report_policies(self, report_bucket: s3.Bucket):
        stmt = iam.PolicyStatement(
            actions=["s3:PutObject", "s3:PutObjectAcl", "s3:GetObject"],
            resources=[f"{report_bucket.bucket_arn}/*"],
        )
        return [self._bedrock_policy(), stmt]
