import boto3
import os
import logging
import json
from datetime import datetime, timezone, timedelta


s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

PROCESSED_BUCKET = os.environ.get("PROCESSED_BUCKET", "memory-images-processed-dev")
TABLE_NAME = os.environ.get("DDB_TABLE_NAME", "MemoryImageMetadata-dev")
INDEX_NAME = "byOriginalKey"

table = dynamodb.Table(TABLE_NAME)
KST = timezone(timedelta(hours=9))

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def generate_dynamic_fields(item, thumbnail_format="jpg"):
    if not item:
        return None

    original_key = item.get("OriginalKey")
    source_bucket = item.get("SourceBucket")
    created_at_iso = item.get("CreatedAt")

    if not original_key:
        return item

    directory = os.path.dirname(original_key)
    filename = os.path.basename(original_key)
    file_base, _ = os.path.splitext(filename)

    if "Tags" in item and isinstance(item["Tags"], set):
        item["Tags"] = list(item["Tags"])

    item["ImageName"] = filename

    if created_at_iso:
        try:
            dt_object = datetime.fromisoformat(created_at_iso)
            item["FormattedCreatedAt"] = dt_object.astimezone(KST).strftime(
                "%Y년 %m월 %d일 %p %I:%M"
            )
        except:
            item["FormattedCreatedAt"] = created_at_iso

    display_bucket, display_key = (source_bucket, original_key)
    if thumbnail_format == "avif":
        processed_key = f"{directory}/transcoded/{file_base}.avif"
        try:
            s3_client.head_object(Bucket=PROCESSED_BUCKET, Key=processed_key)
            display_bucket, display_key = (PROCESSED_BUCKET, processed_key)
        except Exception:
            pass

    try:
        item["DisplayUrl"] = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": display_bucket, "Key": display_key},
            ExpiresIn=900,
        )
    except Exception as e:
        logger.error(f"Error generating DisplayUrl: {e}")
        item["DisplayUrl"] = None

    thumbnail_key = f"{directory}/thumbnail/{file_base}.{thumbnail_format}"
    try:
        item["ThumbnailUrl"] = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": PROCESSED_BUCKET, "Key": thumbnail_key},
            ExpiresIn=900,
        )
    except Exception as e:
        logger.error(f"Error generating ThumbnailUrl: {e}")
        item["ThumbnailUrl"] = None

    try:
        item["presignedUrl"] = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": source_bucket, "Key": original_key},
            ExpiresIn=900,
        )
    except Exception as e:
        logger.error(f"Error generating presignedUrl: {e}")
        item["presignedUrl"] = None

    return item


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event, indent=2)}")

    source_data = event.get("source", {})
    info = event.get("info", {})
    arguments = event.get("arguments", {})

    field_name = info.get("fieldName")

    if "OriginalKey" in arguments:
        original_key = arguments["OriginalKey"]
        logger.info(f"Handling top-level query for OriginalKey: {original_key}")

        try:
            response = table.query(
                IndexName=INDEX_NAME,
                KeyConditionExpression="OriginalKey = :ok",
                ExpressionAttributeValues={":ok": original_key},
            )
            if not response.get("Items"):
                return None

            item = response["Items"][0]
            thumbnail_format = arguments.get("thumbnailFormat", "jpg")
            return generate_dynamic_fields(item, thumbnail_format)
        except Exception as e:
            logger.error(f"Error in top-level query: {e}")
            raise e

    elif "imageKey" in source_data:
        original_key = source_data["imageKey"]
        logger.info(
            f"Handling field resolver for imageKey: {original_key}, field: {field_name}"
        )

        try:
            response = table.query(
                IndexName=INDEX_NAME,
                KeyConditionExpression="OriginalKey = :ok",
                ExpressionAttributeValues={":ok": original_key},
            )
            if not response.get("Items"):
                return None

            item = response["Items"][0]

            thumbnail_format = arguments.get("thumbnailFormat", "jpg")
            enhanced_item = generate_dynamic_fields(item, thumbnail_format)

            return enhanced_item.get(field_name)
        except Exception as e:
            logger.error(f"Error in field resolver query: {e}")
            raise e

    else:
        logger.info(f"Handling generic field resolver for field: {field_name}")
        if not source_data:
            return None

        if field_name not in source_data:
            generate_dynamic_fields(
                source_data, arguments.get("thumbnailFormat", "jpg")
            )

        return source_data.get(field_name)
