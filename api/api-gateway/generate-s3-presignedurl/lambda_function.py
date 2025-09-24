import boto3
import json
import os
import logging
import datetime
from zoneinfo import ZoneInfo
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
s3_client = boto3.client("s3")


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    seoul_date = datetime.datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%y-%m-%d")

    try:
        uuid = event["requestContext"]["authorizer"]["claims"]["sub"]
        body = json.loads(event["body"])
        file_name = body.get("fileName")
        content_type = body.get("contentType", "application/octet-stream")

        if not file_name:
            return {
                "statusCode": 400,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "fileName is required"}),
            }

        object_key = f"album/{uuid}/{seoul_date}/{file_name}"

        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": S3_BUCKET_NAME,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=300,
        )

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"uploadUrl": presigned_url, "objectKey": object_key}),
        }

    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Could not generate the presigned URL"}),
        }
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "An internal error occurred"}),
        }
