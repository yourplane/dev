"""AWS CDK stack for cloud dev control plane."""

from __future__ import annotations

import os

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigateway,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_apigatewayv2_authorizers as apigwv2_auth,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import SecretValue
from constructs import Construct


class DevCloudStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "DevCloudTable",
            table_name="dev-cloud",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="entity-index",
            partition_key=dynamodb.Attribute(name="entity", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        table.add_time_to_live_attribute("ttl")

        bucket = s3.Bucket(
            self,
            "DevCloudBucket",
            bucket_name=None,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        user_pool = cognito.UserPool(
            self,
            "DevCloudUserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(min_length=12),
            removal_policy=RemovalPolicy.RETAIN,
        )
        user_pool_client = user_pool.add_client(
            "DevCloudWebClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
            refresh_token_validity=Duration.days(30),
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
        )

        api_fn = lambda_.Function(
            self,
            "DevCloudApi",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="dev_cloud_control.lambda_entry.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "dist", "lambda"),
            ),
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "DEV_CLOUD_TABLE": table.table_name,
                "DEV_CLOUD_BUCKET": bucket.bucket_name,
                "CONTROL_PLANE_LOG_GROUP": api_fn.log_group.log_group_name,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )
        table.grant_read_write_data(api_fn)
        bucket.grant_read_write(api_fn)
        api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=["*"],
            )
        )
        api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:DescribeLogGroups",
                ],
                resources=["*"],
            )
        )

        http_api = apigwv2.HttpApi(
            self,
            "DevCloudHttpApi",
            api_name="dev-cloud",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["Content-Type", "Authorization"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PUT,
                    apigwv2.CorsHttpMethod.DELETE,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_origins=["*"],
            ),
        )

        jwt_authorizer = apigwv2_auth.HttpJwtAuthorizer(
            "CognitoJwtAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[user_pool_client.user_pool_client_id],
        )

        integration = apigwv2_integrations.HttpLambdaIntegration("LambdaIntegration", api_fn)
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
            authorizer=jwt_authorizer,
        )
        http_api.add_routes(
            path="/worker/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
        )

        # True SSE requires REST API response streaming (HTTP APIs buffer only).
        # Node.js supports native Lambda response streaming; Python does not without LWA.
        stream_fn = lambda_.Function(
            self,
            "DevCloudStreamApi",
            runtime=lambda_.Runtime.NODEJS_20_X,
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "dist", "stream-lambda"),
            ),
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={"DEV_CLOUD_TABLE": table.table_name},
        )
        table.grant_read_data(stream_fn)

        stream_rest_api = apigateway.RestApi(
            self,
            "DevCloudStreamRestApi",
            rest_api_name="dev-cloud-stream",
            deploy_options=apigateway.StageOptions(stage_name="prod"),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=["GET", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"],
            ),
        )
        stream_authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self,
            "StreamRestAuthorizer",
            cognito_user_pools=[user_pool],
        )
        stream_integration = apigateway.LambdaIntegration(
            stream_fn,
            proxy=True,
            response_transfer_mode=apigateway.ResponseTransferMode.STREAM,
        )
        stream_rest_api.root.add_resource("tasks").add_resource("{task_name}").add_resource("stream").add_method(
            "GET",
            stream_integration,
            authorizer=stream_authorizer,
            authorization_type=apigateway.AuthorizationType.COGNITO,
        )

        spa_bucket = s3.Bucket(
            self,
            "DevCloudSpaBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        api_domain = http_api.url or ""
        api_origin = origins.HttpOrigin(
            api_domain.replace("https://", "").rstrip("/"),
            origin_path="/",
        )
        stream_origin = origins.HttpOrigin(
            f"{stream_rest_api.rest_api_id}.execute-api.{self.region}.amazonaws.com",
            origin_path="/prod",
            read_timeout=Duration.seconds(30),
            response_completion_timeout=Duration.seconds(180),
            origin_id="DevCloudStreamRestApi",
        )
        api_rewrite_fn = cloudfront.Function(
            self,
            "ApiStripPrefixFunction",
            code=cloudfront.FunctionCode.from_inline(
                """
function handler(event) {
    var request = event.request;
    if (request.uri.startsWith('/api/')) {
        request.uri = request.uri.substring(4);
    } else if (request.uri === '/api') {
        request.uri = '/';
    }
    return request;
}
"""
            ),
        )
        oac = cloudfront.S3OriginAccessControl(self, "SpaOAC")
        spa_origin = origins.S3BucketOrigin.with_origin_access_control(spa_bucket, origin_access_control=oac)

        distribution = cloudfront.Distribution(
            self,
            "DevCloudDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=spa_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/tasks/*/stream": cloudfront.BehaviorOptions(
                    origin=stream_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    function_associations=[
                        cloudfront.FunctionAssociation(
                            function=api_rewrite_fn,
                            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                        )
                    ],
                ),
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    function_associations=[
                        cloudfront.FunctionAssociation(
                            function=api_rewrite_fn,
                            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                        )
                    ],
                ),
            },
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                # S3 OAC returns 403 for missing keys; SPA client routes need index.html.
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        worker_role = iam.Role(
            self,
            "DevCloudWorkerRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="EC2 environment worker role for dev-cloud",
        )
        worker_role.add_to_policy(
            iam.PolicyStatement(
                actions=["execute-api:Invoke"],
                resources=[f"arn:aws:execute-api:{self.region}:{self.account}:{http_api.api_id}/*/worker/*"],
            )
        )

        cursor_api_secret = secretsmanager.Secret(
            self,
            "CursorApiKeySecret",
            secret_name="dev-cloud/cursor-api-key",
            description="Shared personal Cursor API key for environment workers",
            secret_string_value=SecretValue.unsafe_plain_text("REPLACE_IN_CONSOLE"),
            removal_policy=RemovalPolicy.RETAIN,
        )
        cursor_api_secret.grant_read(worker_role)

        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "ApiUrl", value=http_api.url or "")
        CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "CloudFrontDistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SpaBucketName", value=spa_bucket.bucket_name)
        CfnOutput(self, "WorkerRoleArn", value=worker_role.role_arn)
        CfnOutput(self, "DataBucketName", value=bucket.bucket_name)
        CfnOutput(self, "CursorApiKeySecretArn", value=cursor_api_secret.secret_arn)
        CfnOutput(self, "CursorApiKeySecretName", value=cursor_api_secret.secret_name)


def main() -> None:
    app = cdk.App()
    DevCloudStack(app, "DevCloudStack", env=cdk.Environment(region="us-east-1"))
    app.synth()


if __name__ == "__main__":
    main()
