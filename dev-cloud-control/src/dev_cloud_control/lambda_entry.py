"""Lambda handler module path for CDK packaging."""

from dev_cloud_control.handler import handle_request, handle_stream_request, is_stream_request


def lambda_handler(event, context):
    if is_stream_request(event):
        try:
            import awslambda

            return awslambda.streamify_response(_stream_handler)(event, context)
        except ImportError:
            pass
    return handle_request(event, context)


def _stream_handler(event, response_stream, context):
    handle_stream_request(event, response_stream, context)
