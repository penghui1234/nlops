"""CDK app entry — v4."""
from aws_cdk import App, Environment
from nlops_v4_stack import NLOpsV4Stack

app = App()
NLOpsV4Stack(app, "NLOpsV4Stack",
             env=Environment(account="828414850215", region="us-east-1"),
             description="NLOps v4 - DevOps Agent native architecture")
app.synth()
