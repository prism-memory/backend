import json
import os
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


STATS_TABLE_NAME = os.environ.get("DYNAMODB_STATS_TABLE_NAME")
if not STATS_TABLE_NAME:
    raise ValueError("환경 변수 'DYNAMODB_STATS_TABLE_NAME'이 설정되지 않았습니다.")
stats_table = dynamodb.Table(STATS_TABLE_NAME)


def lambda_handler(event, context):

    source_bucket = event.get("s3Bucket")
    if not source_bucket:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "'s3Bucket' 값이 이벤트에 없습니다."}),
        }

    try:
        input_data = event["body"]
        user_id = input_data["userID"]
    except (KeyError, TypeError):
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"message": "잘못된 요청 형식입니다. 'body'에 'userID'가 필요합니다."}
            ),
        }

    try:
        response = stats_table.get_item(Key={"UserID": user_id})
        item = response.get("Item", {})
    except ClientError as e:
        print(f"DynamoDB 조회 오류: {e.response['Error']['Message']}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "사용자 정보 조회 중 오류가 발생했습니다."}),
        }

    existing_sorted_data = item.get("SortedData")

    if not existing_sorted_data:

        print(
            f"사용자 '{user_id}'의 최초 정렬을 시작합니다. S3에서 전체 이미지 목록을 가져옵니다."
        )

        all_image_keys = []

        prefix = f"album/{user_id}/"

        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=source_bucket, Prefix=prefix)

            for page in pages:

                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    if not key.endswith("/"):
                        all_image_keys.append(key)

            print(
                f"'{prefix}' 경로에서 총 {len(all_image_keys)}개의 이미지를 찾았습니다."
            )

        except ClientError as e:
            print(f"S3 목록 조회 오류: {e.response['Error']['Message']}")
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"message": "S3에서 이미지 목록을 가져오는 중 오류가 발생했습니다."}
                ),
            }

        output = {"userID": user_id, "isInitialSort": True, "imageList": all_image_keys}
    else:

        print(
            f"사용자 '{user_id}'의 추가 정렬을 시작합니다. DynamoDB에서 새 이미지 목록을 가져옵니다."
        )

        new_image_keys = list(item.get("NewImageKeys", set()))

        output = {
            "userID": user_id,
            "isInitialSort": False,
            "existingSortData": existing_sorted_data,
            "newImageList": new_image_keys,
        }

    return {"statusCode": 200, "body": output}
