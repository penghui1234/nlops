"""NLOps v4 CDK Stack — simplified.

Resources:
  - 1 Lambda (Orchestrator) with 4 routes (chat / mcp / webhook / EB)
  - 1 API Gateway (REST) exposing all routes
  - S3 bucket for HTML reports (existing one is RETAINed; this re-imports or recreates)
  - 2 DynamoDB tables (Sessions, Audit) — confirm-tokens removed (SSM has its own audit)
  - EventBridge Rule for DOA Investigation Completed
  - 2 SSM Automation Documents (nlops-ecs-scale, nlops-rds-proxy-expand)
  - IAM Role for DOA to invoke our MCP API
  - SNS Topic for CW Alarm fan-in to webhook handler
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack,
)
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
RUNBOOKS_DIR = ROOT_DIR / "ssm-runbooks"
BOTOCORE_LAYER_ZIP = Path("/tmp/botocore-layer.zip")


class NLOpsV4Stack(Stack):
    """v4 stack: 1 Lambda, DOA-native, SSM-driven remediation."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================ #
        # Storage
        # ============================================================ #
        report_bucket = s3.Bucket(
            self, "ReportBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[s3.LifecycleRule(
                transitions=[
                    s3.Transition(
                        storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                        transition_after=Duration.days(30),
                    ),
                ]
            )],
            removal_policy=RemovalPolicy.RETAIN,
        )

        sessions_table = ddb.Table(
            self, "SessionsTable",
            partition_key=ddb.Attribute(name="session_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        audit_table = ddb.Table(
            self, "AuditTable",
            partition_key=ddb.Attribute(name="trace_id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="ts", type=ddb.AttributeType.NUMBER),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # SNS topic for CW Alarm → Lambda webhook handler
        alarm_topic = sns.Topic(self, "AlarmTopic",
                                display_name="NLOps Alarm Fan-In")

        # ============================================================ #
        # Common environment
        # ============================================================ #
        common_env = {
            "REPORT_BUCKET": report_bucket.bucket_name,
            "SESSIONS_TABLE": sessions_table.table_name,
            "AUDIT_TABLE": audit_table.table_name,
            "BEDROCK_MODEL_ID": "amazon.nova-pro-v1:0",
            "DOA_AGENT_SPACE_ID": "52e43342-bbe2-4fb7-aadd-c072410509ba",
            "DOA_ASSOCIATION_ID": "cb14bec4-5f1a-4148-bb68-e827cfff53e5",
            "DOA_CHAT_TIMEOUT_SEC": "25",
            # Webhook for CW Alarm forwarding (set via console after create)
            "DOA_WEBHOOK_URL": "",
            "DOA_WEBHOOK_SECRET": "",
            # SES alert email
            "ALERT_EMAIL_FROM": "penghuichen@nwcdcloud.cn",
            "ALERT_EMAIL_TO": "penghuichen@nwcdcloud.cn",
            # Lark (飞书) custom robot incoming webhook
            "LARK_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/21826540-97a0-46b7-81c3-677b17c6bc7a",
            # Lark (飞书) Custom App credentials
            "LARK_APP_ID": "cli_aa907e509b389bc8",
            "LARK_APP_SECRET": "WtuhHxF2c4PAOAoyXG92ubewyBLwIow8",
            "LOG_LEVEL": "INFO",
        }

        # ============================================================ #
        # Orchestrator Lambda
        # ============================================================ #
        role = iam.Role(
            self, "OrchestratorRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # Bedrock + DOA permissions
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=["*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                # DevOps Agent (GA action prefix may be 'devops-agent' or 'aidevops';
                # we grant both to cover transition period)
                "devops-agent:*",
                "aidevops:*",
            ],
            resources=["*"],
        ))
        # SSM Automation
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "ssm:StartAutomationExecution",
                "ssm:GetAutomationExecution",
                "ssm:DescribeAutomationExecutions",
                "ssm:GetDocument",
            ],
            resources=["*"],
        ))
        # SES
        role.add_to_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=["*"],
        ))
        # Read-only AWS observability (for fallback when DOA unavailable)
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "cloudwatch:GetMetricData",
                "cloudwatch:DescribeAlarms",
                "logs:FilterLogEvents",
                "logs:DescribeLogGroups",
                "ec2:DescribeInstances",
                "ecs:DescribeServices",
                "rds:DescribeDBInstances",
                "iam:PassRole",
                # Self-invoke for async Lark event processing
                "lambda:InvokeFunction",
            ],
            resources=["*"],
        ))
        # Storage
        sessions_table.grant_read_write_data(role)
        audit_table.grant_read_write_data(role)
        report_bucket.grant_read_write(role)

        orchestrator_fn = lambda_.Function(
            self, "OrchestratorFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.api_handler.handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            timeout=Duration.seconds(120),
            memory_size=1024,
            role=role,
            environment=common_env,
            layers=[
                lambda_.LayerVersion(
                    self, "BotocoreLayer",
                    code=lambda_.Code.from_asset(str(BOTOCORE_LAYER_ZIP)),
                    compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
                    description="Latest boto3/botocore with devops-agent service",
                ),
            ],
        )

        # SNS → Lambda subscription (CW Alarm fan-in)
        alarm_topic.add_subscription(subs.LambdaSubscription(orchestrator_fn))

        # ============================================================ #
        # API Gateway (single REST API with all routes)
        # ============================================================ #
        api = apigw.LambdaRestApi(
            self, "NLOpsApi",
            handler=orchestrator_fn,
            proxy=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=100,
                throttling_rate_limit=50,
                metrics_enabled=True,
            ),
        )
        # /chat — public
        api.root.add_resource("chat").add_method(
            "POST", authorization_type=apigw.AuthorizationType.NONE,
        )
        # /webhook-incoming — public (signed by HMAC upstream)
        api.root.add_resource("webhook-incoming").add_method(
            "POST", authorization_type=apigw.AuthorizationType.NONE,
        )
        # /lark-event — public (Lark verifies via app_id/secret on our side)
        api.root.add_resource("lark-event").add_method(
            "POST", authorization_type=apigw.AuthorizationType.NONE,
        )
        # /mcp — IAM auth (for DOA's MCP integration)
        mcp = api.root.add_resource("mcp")
        mcp.add_method("POST", authorization_type=apigw.AuthorizationType.IAM)
        # /mcp-quick — public (for Quick Desktop)
        for name in ("mcp-quick", "sse", "message"):
            r = api.root.add_resource(name)
            r.add_method("POST", authorization_type=apigw.AuthorizationType.NONE)
            r.add_method("GET", authorization_type=apigw.AuthorizationType.NONE)
            r.add_method("OPTIONS", authorization_type=apigw.AuthorizationType.NONE)

        # ============================================================ #
        # EventBridge: DOA Investigation Completed → Lambda
        # ============================================================ #
        events.Rule(
            self, "DOACompletedRule",
            event_pattern=events.EventPattern(
                source=["aws.devopsagent", "aws.aidevops"],
                detail_type=[
                    "Investigation Completed",
                    "Investigation Updated",
                    "Evaluation Completed",
                ],
            ),
            targets=[targets.LambdaFunction(orchestrator_fn)],
        )

        # ============================================================ #
        # IAM Role for DOA to invoke our MCP API
        # (DOA's GA service principal is still 'aidevops.amazonaws.com')
        # ============================================================ #
        doa_invoke_role = iam.Role(
            self, "DOAInvokeMcpRole",
            assumed_by=iam.ServicePrincipal(
                "aidevops.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                },
            ),
            description="DOA assumes this to invoke NLOps MCP API",
        )
        doa_invoke_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:Invoke"],
            resources=[
                self.format_arn(
                    service="execute-api", resource=api.rest_api_id,
                    resource_name="prod/POST/mcp",
                )
            ],
        ))

        # ============================================================ #
        # SSM Runbook documents (loaded from yaml files)
        # ============================================================ #
        import yaml as _yaml
        for rb_name, rb_file in [
            ("nlops-ecs-scale", "ecs-scale.yaml"),
            ("nlops-rds-proxy-expand", "rds-proxy-expand.yaml"),
        ]:
            rb_path = RUNBOOKS_DIR / rb_file
            if rb_path.exists():
                content_dict = _yaml.safe_load(rb_path.read_text())
                ssm.CfnDocument(
                    self, f"Runbook{rb_name.replace('-', '')}",
                    name=rb_name,
                    document_type="Automation",
                    document_format="YAML",
                    content=content_dict,
                    update_method="NewVersion",
                )

        # ============================================================ #
        # Outputs
        # ============================================================ #
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "ChatUrl", value=f"{api.url}chat")
        CfnOutput(self, "WebhookUrl", value=f"{api.url}webhook-incoming")
        CfnOutput(self, "McpUrl", value=f"{api.url}mcp")
        CfnOutput(self, "McpQuickUrl", value=f"{api.url}mcp-quick")
        CfnOutput(self, "AlarmTopicArn", value=alarm_topic.topic_arn)
        CfnOutput(self, "DOAInvokeRoleArn", value=doa_invoke_role.role_arn)
        CfnOutput(self, "ReportBucketName", value=report_bucket.bucket_name)
        CfnOutput(self, "OrchestratorFnArn", value=orchestrator_fn.function_arn)
