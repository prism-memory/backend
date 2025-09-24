import json
import os
import datetime
import boto3
from zoneinfo import ZoneInfo
from botocore.exceptions import ClientError

dynamodb_client = boto3.client("dynamodb")

METADATA_TABLE_NAME = os.environ.get("DYNAMODB_METADATA_TABLE_NAME")
STATS_TABLE_NAME = os.environ.get("DYNAMODB_STATS_TABLE_NAME")

if not METADATA_TABLE_NAME or not STATS_TABLE_NAME:
    raise ValueError(
        "환경 변수 'DYNAMODB_METADATA_TABLE_NAME'와 'DYNAMODB_STATS_TABLE_NAME'이 모두 설정되어야 합니다."
    )


def lambda_handler(event, context):
    print(f"DynamoDB에 저장할 이벤트 수신: {json.dumps(event, indent=2)}")

    try:
        source_info = event["source_info"]
        bedrock_analysis = event["bedrock_analysis"]
        original_key = event["original_key"]

        if not original_key:
            raise ValueError("'original_key' 값이 없습니다.")

        key_parts = original_key.split("/")
        if len(key_parts) < 3 or key_parts[0] != "album":
            raise ValueError(
                f"'{original_key}'에서 UserID를 추출할 수 없는 경로 형식입니다. 'album/USER_ID/...' 형식을 예상했습니다."
            )
        user_id = key_parts[1]
        album_id = os.path.dirname(original_key)

        existing_item = None
        is_update = False

        try:
            query_response = dynamodb_client.query(
                TableName=METADATA_TABLE_NAME,
                IndexName="byOriginalKey",
                KeyConditionExpression="OriginalKey = :okey",
                ExpressionAttributeValues={":okey": {"S": original_key}},
            )

            if query_response["Items"]:
                existing_item = query_response["Items"][0]
                is_update = True
                print(f"기존 아이템 발견: {existing_item}")

        except ClientError as e:
            print(f"오류: GSI 쿼리 중 에러 발생. {e}")
            raise e

        timestamp_iso = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat()

        item_to_save = {
            "UserID": {"S": user_id},
            "OriginalKey": {"S": original_key},
            "SourceBucket": {"S": source_info["sourceBucket"]},
            "ProcessedKey": {"S": source_info["processed_key"]},
            "ImageSummary": {"S": bedrock_analysis["imageSummary"]},
            "AvifEncoding": {"S": json.dumps(bedrock_analysis["avifEncoding"])},
        }

        if is_update:
            print("기존 아이템 갱신을 준비합니다.")
            item_to_save["AlbumID"] = existing_item["AlbumID"]
            item_to_save["CreatedAt"] = existing_item["CreatedAt"]
            item_to_save["UpdatedAt"] = {"S": timestamp_iso}
        else:
            print("신규 아이템 생성을 준비합니다.")
            item_to_save["AlbumID"] = {"S": album_id}
            item_to_save["CreatedAt"] = {"S": timestamp_iso}

        tags = bedrock_analysis.get("tags")
        if tags and isinstance(tags, list):
            unique_tags = {tag for tag in tags if tag}
            if unique_tags:
                item_to_save["Tags"] = {"SS": list(unique_tags)}

        print(f"메타데이터 테이블에 저장할 아이템: {json.dumps(item_to_save)}")

        transact_items = [
            {"Put": {"TableName": METADATA_TABLE_NAME, "Item": item_to_save}},
        ]

        if not is_update:
            stats_update_item = {
                "Update": {
                    "TableName": STATS_TABLE_NAME,
                    "Key": {"UserID": {"S": user_id}},
                    "UpdateExpression": "ADD ImageCount :inc SET SortStatus = :status",
                    "ExpressionAttributeValues": {
                        ":inc": {"N": "1"},
                        ":status": {"S": "NEEDS_UPDATE"},
                    },
                }
            }
            transact_items.append(stats_update_item)

        dynamodb_client.transact_write_items(TransactItems=transact_items)

        operation_type = "updated" if is_update else "created"
        print(
            f"성공: 트랜잭션이 성공적으로 완료되었습니다. (UserID: {user_id}, Operation: {operation_type})"
        )

        response_body = {
            "message": f"Successfully {operation_type} metadata and updated stats",
            "userID": user_id,
            "albumId": album_id,
            "timestamp": timestamp_iso,
            "operation": operation_type,
        }

        return {"statusCode": 200, "body": json.dumps(response_body)}

    except ClientError as e:
        print(
            f"오류: AWS Client 에러가 발생했습니다. 코드: {e.response['Error']['Code']}, 메시지: {e.response['Error']['Message']}"
        )
        raise e
    except (ValueError, KeyError) as e:
        print(f"오류: 입력 데이터에 문제가 있습니다. {e}")
        raise e
