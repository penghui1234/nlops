"""NLOps CDK Stack v3.

Architecture (post-merger / 2026-05-19):
  L1 OrchestratorFn  — single entry for chat / voice / webhook / MCP / EventBridge
                       Strands Agents SDK drives 5 high-level tools that call DOA.
                       Hosts:
                         • api_handler       (chat / voice / webhook entry)
                         • mcp_handler       (18 + 3 MCP tools, also exposes smart_diagnose)
                         • eventbridge_handler (alarm-driven HTML + SES email + KB sink)
  L2 ExecutionFn     — write-isolated Lambda (still independent for IAM boundary)

Plus:
  - 1 caller-facing API Gateway (Quick / WeCom / Feishu webhooks)
  - 1 MCP API Gateway (DOA / Quick Desktop)
  - S3 bucket (reports + KB sink)
  - 3 DynamoDB tables: sessions / audit / confirm-tokens
  - SNS topic for legacy fan-out
  - EventBridge Rule for DOA investigation events
  - SES email identity (verified out-of-band)
  - 1 Lambda Layer for strands-agents SDK

L3 EventBridgeSubscriberFn and L4 McpServerFn are removed (merged into L1).
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from constructs import Construct

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
STRANDS_LAYER_ZIP = Path("/tmp/strands-layer/strands-layer.zip")


class NLOpsStack(Stack):
    """v3 stack: 2 Lambdas (L1 + L2 only) + DOA integration + SES email."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================== #
        # 1. Storage
        # ============================================================== #
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

        confirm_tokens_table = ddb.Table(
            self,
            "ConfirmTokensTable",
            partition_key=ddb.Attribute(name="token", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================================== #
        # 2. Notifications
        # ============================================================== #
        notify_topic = sns.Topic(
            self,
            "NotifyTopic",
            display_name="NLOps Notifications",
        )

        # ============================================================== #
        # 3. Common environment + Strands layer
        # ============================================================== #
        common_env = {
            "REPORT_BUCKET": report_bucket.bucket_name,
            "SESSIONS_TABLE": sessions_table.table_name,
            "AUDIT_TABLE": audit_table.table_name,
            "CONFIRM_TOKENS_TABLE": confirm_tokens_table.table_name,
            "NOTIFY_TOPIC_ARN": notify_topic.topic_arn,
            "BEDROCK_MODEL_ID": "amazon.nova-pro-v1:0",
            "NOVA_SONIC_MODEL_ID": "amazon.nova-sonic-v1:0",
            "BEDROCK_EMBED_MODEL": "amazon.titan-embed-text-v2:0",
            "BEDROCK_KB_ID": "",
            "BEDROCK_KB_DATA_SOURCE_ID": "",
            "DOA_AGENT_SPACE_ID": "52e43342-bbe2-4fb7-aadd-c072410509ba",  # nlops-demo
            "DOA_BOTO3_SERVICE": "devops-agent",  # GA service name (not 'aidevops')
            # SES alert email (must be verified in SES sandbox)
            "ALERT_EMAIL_FROM": "penghuichen@nwcdcloud.cn",
            "ALERT_EMAIL_TO": "penghuichen@nwcdcloud.cn",
            # Default to real mode; flip to "true" on McpServer for demo rehearsal.
            "MOCK_MODE": "false",
            "LOG_LEVEL": "INFO",
        }

        code_asset = lambda_.Code.from_asset(str(SRC_DIR))

        # Strands Agents Lambda Layer (built locally via pip --platform)
        strands_layer = lambda_.LayerVersion(
            self,
            "StrandsLayer",
            code=lambda_.Code.from_asset(str(STRANDS_LAYER_ZIP)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="strands-agents SDK + deps for NLOps L1 Orchestrator",
        )

        # ============================================================== #
        # 4. L2 Execution Lambda (declared first because L1 depends on it)
        # ============================================================== #
        execution_role = self._make_role("ExecutionRole")
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:UpdateService",
                    "ecs:DescribeServices",
                    "autoscaling:SetDesiredCapacity",
                    "autoscaling:UpdateAutoScalingGroup",
                    "rds:RebootDBInstance",
                    "rds:ModifyDBProxy",
                    "rds:DescribeDBProxies",
                    "ec2:RebootInstances",
                    "ec2:DescribeInstances",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "aws:ResourceTag/nlops:managed": "true",
                    }
                },
            )
        )
        confirm_tokens_table.grant_read_write_data(execution_role)
        audit_table.grant_write_data(execution_role)

        execution_fn = lambda_.Function(
            self,
            "ExecutionFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.execution_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=execution_role,
            environment=common_env,
        )

        # ============================================================== #
        # 5. L1 OrchestratorFn — handles chat / mcp / eventbridge
        # ============================================================== #
        orchestrator_role = self._make_role(
            "OrchestratorRole",
            extra_policies=[
                self._bedrock_policy(),
                self._doa_read_chat_policy(),
                self._doa_create_investigation_policy(),
            ],
        )
        # Storage
        sessions_table.grant_read_write_data(orchestrator_role)
        audit_table.grant_read_write_data(orchestrator_role)
        confirm_tokens_table.grant_read_write_data(orchestrator_role)
        notify_topic.grant_publish(orchestrator_role)
        report_bucket.grant_read_write(orchestrator_role)

        # SES email
        orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail", "ses:GetSendQuota"],
                resources=["*"],
            )
        )

        # Cross-Lambda: invoke L2 Execution
        execution_fn.grant_invoke(orchestrator_role)

        # Read-only AWS observability + tag for analyze_*/discover_* MCP tools
        orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    # CloudWatch
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:DescribeAlarms",
                    # CloudWatch Logs (Insights)
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:FilterLogEvents",
                    "logs:StartQuery",
                    "logs:StopQuery",
                    "logs:GetQueryResults",
                    # X-Ray
                    "xray:GetServiceGraph",
                    "xray:GetTraceSummaries",
                    "xray:BatchGetTraces",
                    "xray:GetTraceGraph",
                    # Resource discovery
                    "ecs:ListClusters",
                    "ecs:ListServices",
                    "ecs:DescribeServices",
                    "ec2:DescribeInstances",
                    "ec2:DescribeRegions",
                    "rds:DescribeDBInstances",
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "lambda:ListFunctions",
                    # Tags lookup
                    "tag:GetResources",
                    "tag:GetTagKeys",
                    "tag:GetTagValues",
                ],
                resources=["*"],
            )
        )

        orchestrator_fn = lambda_.Function(
            self,
            "OrchestratorFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.api_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(120),  # Strands + DOA chat may take 30s+
            memory_size=1536,                # Strands SDK + Bedrock client
            role=orchestrator_role,
            environment={
                **common_env,
                "EXECUTION_FN_NAME": execution_fn.function_name,
                "MCP_TOOLS_ALLOWLIST": "",  # empty = all tools
            },
            layers=[strands_layer],
        )

        # ============================================================== #
        # 6. EventBridge Rule — target is L1 directly (no L3 anymore)
        # ============================================================== #
        events.Rule(
            self,
            "DOAInvestigationRule",
            event_pattern=events.EventPattern(
                source=["aws.aidevops"],
                detail_type=[
                    "Investigation Completed",
                    "Investigation Updated",
                    "Evaluation Completed",
                ],
            ),
            targets=[targets.LambdaFunction(orchestrator_fn)],
        )

        # ============================================================== #
        # 7. Caller-facing API Gateway (/chat /voice /webhook)
        # ============================================================== #
        caller_api = apigw.LambdaRestApi(
            self,
            "CallerApi",
            handler=orchestrator_fn,
            proxy=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=200,
                throttling_rate_limit=100,
                metrics_enabled=True,
            ),
        )
        for path in ("chat", "voice", "webhook"):
            caller_api.root.add_resource(path).add_method("POST")

        # ============================================================== #
        # 8. MCP API Gateway (also targets L1 — no L4 anymore)
        # ============================================================== #
        mcp_api = apigw.LambdaRestApi(
            self,
            "McpApi",
            handler=orchestrator_fn,
            proxy=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=50,
                throttling_rate_limit=25,
                metrics_enabled=True,
            ),
        )
        # /mcp — IAM-authenticated for AWS DevOps Agent (mcp-out path)
        mcp_resource = mcp_api.root.add_resource("mcp")
        mcp_resource.add_method("POST", authorization_type=apigw.AuthorizationType.IAM)

        # /mcp-public, /mcp-quick, /sse, /message — NoAuth for Quick Desktop
        for name in ("mcp-public", "mcp-quick", "sse", "message"):
            r = mcp_api.root.add_resource(name)
            r.add_method("POST", authorization_type=apigw.AuthorizationType.NONE)
            r.add_method("GET", authorization_type=apigw.AuthorizationType.NONE)
            r.add_method("OPTIONS", authorization_type=apigw.AuthorizationType.NONE)

        # ============================================================== #
        # 9. IAM Role assumed by AWS DevOps Agent to call our MCP Server
        # ============================================================== #
        doa_invoke_role = iam.Role(
            self,
            "DOAInvokeMcpRole",
            assumed_by=iam.ServicePrincipal(
                "aidevops.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:aidevops:{self.region}:{self.account}:agent-space/*"
                    },
                },
            ),
            description="Role assumed by AWS DevOps Agent to call NLOps MCP Server",
        )
        doa_invoke_role.add_to_policy(
            iam.PolicyStatement(
                actions=["execute-api:Invoke"],
                resources=[
                    self.format_arn(
                        service="execute-api",
                        resource=mcp_api.rest_api_id,
                        resource_name="prod/POST/mcp",
                    )
                ],
            )
        )

        # ============================================================== #
        # 10. Outputs
        # ============================================================== #
        CfnOutput(self, "CallerApiUrl", value=caller_api.url)
        CfnOutput(self, "McpApiUrl", value=mcp_api.url)
        CfnOutput(self, "McpInvokeRoleArn", value=doa_invoke_role.role_arn)
        CfnOutput(self, "ReportBucketName", value=report_bucket.bucket_name)
        CfnOutput(self, "NotifyTopicArn", value=notify_topic.topic_arn)
        CfnOutput(self, "OrchestratorFnArn", value=orchestrator_fn.function_arn)
        CfnOutput(self, "ExecutionFnArn", value=execution_fn.function_arn)
        CfnOutput(self, "StrandsLayerArn", value=strands_layer.layer_version_arn)

    # ====================================================================== #
    # Helpers
    # ====================================================================== #
    def _make_role(
        self,
        name: str,
        extra_policies: list[iam.PolicyStatement] | None = None,
    ) -> iam.Role:
        role = iam.Role(
            self,
            name,
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )
        for stmt in extra_policies or []:
            role.add_to_policy(stmt)
        return role

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

    @staticmethod
    def _doa_read_chat_policy() -> iam.PolicyStatement:
        """Read & chat for L1 (collapsed from L1+L3+L4 roles in v3 merger)."""
        return iam.PolicyStatement(
            actions=[
                "aidevops:CreateChat",
                "aidevops:SendMessage",
                "aidevops:ListChats",
                "aidevops:GetBacklogTask",
                "aidevops:ListBacklogTasks",
                "aidevops:ListAgentSpaces",
                "aidevops:GetAgentSpace",
                "aidevops:GetRecommendation",
                "aidevops:ListRecommendations",
            ],
            resources=["*"],
        )

    @staticmethod
    def _doa_create_investigation_policy() -> iam.PolicyStatement:
        return iam.PolicyStatement(
            actions=[
                "aidevops:CreateBacklogTask",
                "aidevops:UpdateBacklogTask",
            ],
            resources=["*"],
        )
