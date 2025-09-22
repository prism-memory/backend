import json
import os
import boto3
from botocore.exceptions import ClientError
import datetime

dynamodb = boto3.resource("dynamodb")

STATS_TABLE_NAME = os.environ.get("DYNAMODB_STATS_TABLE_NAME")
if not STATS_TABLE_NAME:
    raise ValueError("Environment 'DYNAMODB_STATS_TABLE_NAME' is not set")

stats_table = dynamodb.Table(STATS_TABLE_NAME)


def lambda_handler(event, context):
    print(f"정렬 필요 여부 확인 이벤트 수신: {json.dumps(event, indent=2)}")

    try:
        body_string = event["body"]
        data = json.loads(body_string)
        user_id = data["userID"]
        response = stats_table.get_item(Key={"UserID": user_id})
        item = response.get("Item")

        if not item:
            print(f"경고: 사용자 '{user_id}'의 통계 정보를 찾을 수 없습니다.")
            return {
                "statusCode": 404,
                "body": json.dumps(
                    {"status": "ERROR", "reason": "User stats not found"}
                ),
            }

        image_count = item.get("ImageCount", 0)

        if image_count < 20:
            print(
                f"사용자 '{user_id}'의 이미지 개수({image_count})가 20개 이하이므로 정렬을 건너뜁니다."
            )
            return {
                "statusCode": 200,
                "body": {"status": "SKIPPED", "reason": "Image count is not over 30"},
            }

        response = stats_table.get_item(Key={"UserID": user_id})

        item = response.get("Item")
        if not item:
            print(f"경고: 사용자 '{user_id}'의 통계 정보를 찾을 수 없습니다.")
            return {
                "statusCode": 404,
                "body": {"status": "ERROR", "reason": "User stats not found"},
            }

        sort_status = item.get("SortStatus", "NEEDS_UPDATE")

        if sort_status != "NEEDS_UPDATE":
            print(
                f"사용자 '{user_id}'의 앨범은 이미 최신 상태({sort_status})이므로 정렬을 건너뜁니다."
            )
            return {
                "statusCode": 200,
                "body": {
                    "status": "SKIPPED",
                    "reason": "Sort status is already up-to-date",
                },
            }

        last_sorted_at_str = item.get('LastSortedAt')
        if last_sorted_at_str:
            try:
                last_sorted_at_dt = datetime.datetime.fromisoformat(last_sorted_at_str)
                current_time = datetime.datetime.now(datetime.timezone.utc)
                time_difference = current_time - last_sorted_at_dt

                if time_difference < datetime.timedelta(hours=1):
                    print(f"사용자 '{user_id}'는 최근 1시간 이내에 정렬을 실행했으므로 건너뜁니다.")
                    return {
                        'statusCode': 200,
                        'body': {'status': 'SKIPPED', 'reason': 'Sorted within the last hour'}
                    }
            except ValueError:
                print(f"경고: 사용자 '{user_id}'의 LastSortedAt 속성 형식이 올바르지 않습니다: {last_sorted_at_str}")

        print(f"사용자 '{user_id}'의 정렬이 필요합니다. Step Function을 실행합니다.")
        return {
            "statusCode": 200,
            "body": {
                "status": "TRIGGERED",
                "message": f"Sorting process initiated for user {user_id}",
                "userID": user_id,
                "imageCount": image_count,
            },
        }

    except (ClientError, KeyError, ValueError) as e:
        print(f"오류: 정렬 필요 여부 확인에 실패했습니다. {e}")
        return {"statusCode": 500, "body": {"status": "ERROR", "reason": str(e)}}
