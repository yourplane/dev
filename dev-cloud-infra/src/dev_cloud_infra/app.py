"""AWS CDK stack for cloud dev control plane."""

from __future__ import annotations

import os

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
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
)
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
        )

        api_fn = lambda_.Function(
            self,
            "DevCloudApi",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="dev_cloud_control.lambda_entry.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "dist", "lambda"),
            ),
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "DEV_CLOUD_TABLE": table.table_name,
                "DEV_CLOUD_BUCKET": bucket.bucket_name,
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
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                )
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

        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "ApiUrl", value=http_api.url or "")
        CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "CloudFrontDistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SpaBucketName", value=spa_bucket.bucket_name)
        CfnOutput(self, "WorkerRoleArn", value=worker_role.role_arn)
        CfnOutput(self, "DataBucketName", value=bucket.bucket_name)


def main() -> None:
    app = cdk.App()
    DevCloudStack(app, "DevCloudStack", env=cdk.Environment(region="us-east-1"))
    app.synth()


if __name__ == "__main__":
    main()
