import boto3
import os
from botocore.exceptions import ClientError
import logging

s3_client = boto3.client("s3")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

URL_EXPIRATION_SECONDS = 3600


def lambda_handler(event, context):
    logger.info(f"Received event: {event}")

    bucket_name = None
    object_key = None

    if "source" in event and "info" in event:
        logger.info("Handling detailed request from listMemoryImageMetadata.")
        source = event["source"]
        field_name = event["info"]["fieldName"]

        bucket_name = source.get("SourceBucket")
        if field_name == "OriginalPresignedUrl":
            object_key = source.get("OriginalKey")
        elif field_name == "ProcessedPresignedUrl":
            object_key = source.get("ProcessedKey")

    elif "objectKey" in event:
        logger.info("Handling simple request from getSortedImagesForUser.")
        original_key = event.get("objectKey")
        if not original_key:
            return None

        original_bucket = os.environ.get("ORIGINAL_IMAGES_BUCKET")
        processed_bucket = os.environ.get("PROCESSED_IMAGES_BUCKET")

        if not original_bucket or not processed_bucket:
            logger.error("Bucket name environment variables are not set.")
            return None

        try:
            path_parts = original_key.split("/")
            filename = path_parts.pop()
            base_filename, _ = os.path.splitext(filename)
            processed_filename = f"{base_filename}.avif"
            path_parts.append("processed")
            path_parts.append(processed_filename)
            processed_key = "/".join(path_parts)
        except Exception:
            processed_key = None

        final_bucket = original_bucket
        final_key = original_key
        if processed_key:
            try:
                s3_client.head_object(Bucket=processed_bucket, Key=processed_key)
                final_bucket = processed_bucket
                final_key = processed_key
            except ClientError:
                logger.info(f"Processed file not found. Falling back to original.")

        bucket_name = final_bucket
        object_key = final_key

    else:
        logger.error("Invalid event structure received.")
        return None

    if not bucket_name or not object_key:
        logger.warning("Bucket name or object key could not be determined.")
        return None

    try:
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=URL_EXPIRATION_SECONDS,
        )
        return presigned_url
    except ClientError as e:
        logger.error(
            f"Error generating presigned URL for {bucket_name}/{object_key}: {e}"
        )
        return None
