"""Lambda handler module path for CDK packaging."""

from dev_cloud_control.handler import handle_request


def lambda_handler(event, context):
    return handle_request(event, context)
