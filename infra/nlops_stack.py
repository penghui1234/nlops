"""NLOps CDK Stack (v2).

Architecture (see docs/02-design.md §1.2):

  L1 Orchestrator Lambda
    - Entry point for caller API GW
    - Strands SDK in-process orchestration of 5 logical Tools:
      Router / Discovery / Analysis / Knowledge / Report
    - Calls AWS DevOps Agent (chat / investigation)
    - Invokes L2 cross-Lambda for write actions

  L2 Execution Lambda
    - Independent IAM (write boundary)
    - Validates Confirm Token (DDB) + Policy
    - Calls AWS resource APIs (ECS/EC2/RDS/...) under tag boundary

  L3 EventBridge Subscriber Lambda
    - Subscribes to 'aws.aidevops' source events
    - Renders HTML diagnostic page, pushes IM card

  L4 MCP Server Lambda
    - Exposes customer's private tools as MCP Server (for DevOps Agent)
    - Behind a separate API Gateway with AWS_IAM (SigV4) auth

Plus:
  - 1 caller-facing API Gateway (Quick / WeCom / Feishu webhooks)
  - 1 MCP API Gateway
  - S3 bucket (reports + KB sink)
  - 3 DynamoDB tables: sessions / audit / confirm-tokens
  - SNS topic for notifications
  - EventBridge Rule for DevOps Agent investigation events
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

SRC_DIR = Path(__file__).resolve().parent.parent / "src"


class NLOpsStack(Stack):
    """v2 stack: 4 Lambdas + DevOps Agent integration."""

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
        # 3. Common environment
        # ============================================================== #
        common_env = {
            "REPORT_BUCKET": report_bucket.bucket_name,
            "SESSIONS_TABLE": sessions_table.table_name,
            "AUDIT_TABLE": audit_table.table_name,
            "CONFIRM_TOKENS_TABLE": confirm_tokens_table.table_name,
            "NOTIFY_TOPIC_ARN": notify_topic.topic_arn,
            "BEDROCK_MODEL_ID": "moonshotai.kimi-k2.5",
            "BEDROCK_EMBED_MODEL": "amazon.titan-embed-text-v2:0",
            "DOA_AGENT_SPACE_ID": "774d6ebc-e1c0-498b-853f-e28fc457142c",  # nlops-demo
            "LOG_LEVEL": "INFO",
        }

        code_asset = lambda_.Code.from_asset(str(SRC_DIR))

        # ============================================================== #
        # 4. L1 Orchestrator Lambda (entry + Strands SDK in-proc agents)
        # ============================================================== #
        orchestrator_role = self._make_role(
            "OrchestratorRole",
            extra_policies=[
                self._bedrock_policy(),
                self._doa_read_chat_policy(),
                self._doa_create_investigation_policy(),
            ],
        )
        sessions_table.grant_read_write_data(orchestrator_role)
        audit_table.grant_write_data(orchestrator_role)
        confirm_tokens_table.grant_read_write_data(orchestrator_role)
        notify_topic.grant_publish(orchestrator_role)
        report_bucket.grant_put(orchestrator_role)
        report_bucket.grant_read(orchestrator_role)

        orchestrator_fn = lambda_.Function(
            self,
            "OrchestratorFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.api_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=1024,
            role=orchestrator_role,
            environment=common_env,
        )

        # ============================================================== #
        # 5. L2 Execution Lambda (write isolation)
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
        # Allow L1 Orchestrator to invoke L2 Execution
        execution_fn.grant_invoke(orchestrator_role)
        # Pass execution function name to L1 via env
        orchestrator_fn.add_environment("EXECUTION_FN_NAME", execution_fn.function_name)

        # ============================================================== #
        # 6. L3 EventBridge Subscriber (DOA investigation events)
        # ============================================================== #
        ebsub_role = self._make_role(
            "EventBridgeSubscriberRole",
            extra_policies=[
                self._bedrock_policy(),
                iam.PolicyStatement(
                    actions=[
                        "aidevops:GetInvestigation",
                        "aidevops:GetEvaluation",
                        "aidevops:ListInvestigations",
                    ],
                    resources=["*"],
                ),
            ],
        )
        report_bucket.grant_put(ebsub_role)
        notify_topic.grant_publish(ebsub_role)
        audit_table.grant_write_data(ebsub_role)

        ebsub_fn = lambda_.Function(
            self,
            "EventBridgeSubscriberFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.eventbridge_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=ebsub_role,
            environment=common_env,
        )

        # EventBridge rule: subscribe to DevOps Agent investigation events
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
            targets=[targets.LambdaFunction(ebsub_fn)],
        )

        # ============================================================== #
        # 7. L4 MCP Server Lambda (exposes customer tools to DOA)
        # ============================================================== #
        mcp_role = self._make_role("McpServerRole")
        # NLOps MCP Server should NOT have AWS resource permissions.
        # It only proxies to customer's internal endpoints (CMDB / Jira / APM).
        # Customer wires VPC link / Private Connection via parameters.
        audit_table.grant_write_data(mcp_role)

        mcp_fn = lambda_.Function(
            self,
            "McpServerFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handlers.mcp_handler.handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=mcp_role,
            environment={
                **common_env,
                "MCP_TOOLS_ALLOWLIST": "get_service_owner,get_recent_jira_tickets,get_internal_apm_metric",
            },
        )

        # ============================================================== #
        # 8. Caller-facing API Gateway  (/chat /voice /webhook)
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
        # 9. MCP API Gateway (DOA -> NLOps MCP server, SigV4)
        # ============================================================== #
        mcp_api = apigw.LambdaRestApi(
            self,
            "McpApi",
            handler=mcp_fn,
            proxy=False,
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=50,
                throttling_rate_limit=25,
                metrics_enabled=True,
            ),
        )
        # Single /mcp resource with AWS_IAM auth (SigV4)
        mcp_resource = mcp_api.root.add_resource("mcp")
        mcp_resource.add_method(
            "POST",
            authorization_type=apigw.AuthorizationType.IAM,
        )

        # IAM Role that DevOps Agent will assume to call our MCP Server
        # The trust policy lets aidevops.amazonaws.com sts:AssumeRole this role,
        # with confused-deputy guards.
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
        """Read & chat — used by Orchestrator (L1) and EB Subscriber (L3).

        Real API operations (verified via boto3.client('devops-agent')
        .meta.service_model.operation_names in 2026-05):
          CreateChat / SendMessage / ListChats
          GetBacklogTask / ListBacklogTasks
          ListAgentSpaces / GetAgentSpace
        """
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
        """Create backlog tasks (investigations / knowledge) — Orchestrator (L1) only."""
        return iam.PolicyStatement(
            actions=[
                "aidevops:CreateBacklogTask",
                "aidevops:UpdateBacklogTask",
            ],
            resources=["*"],
        )
