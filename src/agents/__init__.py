"""6 logical Agents — implemented as Strands-style Tools.

Each Agent exposes a single ``run(ctx, **kwargs)`` method invoked from
the Orchestrator. Agents are *not* independent Lambdas (except Execution,
which proxies to a separate L2 Lambda for IAM isolation).
"""
