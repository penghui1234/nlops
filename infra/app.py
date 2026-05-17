"""CDK app entrypoint for NLOps platform."""
import os

import aws_cdk as cdk

from nlops_stack import NLOpsStack

app = cdk.App()

NLOpsStack(
    app,
    "NLOpsStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="Natural Language driven AI Ops platform (NLOps)",
)

app.synth()
