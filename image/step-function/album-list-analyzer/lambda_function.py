import json
import os
from collections import defaultdict
import boto3
from boto3.dynamodb.conditions import Key
import datetime
import re
from botocore.exceptions import ClientError
from botocore.config import Config

config = Config(retries={"max_attempts": 100, "mode": "adaptive"})


dynamodb = boto3.resource("dynamodb")
bedrock_runtime = boto3.client(service_name="bedrock-runtime", config=config)


STATS_TABLE_NAME = os.environ.get("DYNAMODB_STATS_TABLE_NAME")
METADATA_TABLE_NAME = os.environ.get("DYNAMODB_METADATA_TABLE_NAME")

if not STATS_TABLE_NAME or not METADATA_TABLE_NAME:
    raise ValueError("환경 변수가 올바르게 설정되지 않았습니다.")

stats_table = dynamodb.Table(STATS_TABLE_NAME)
metadata_table = dynamodb.Table(METADATA_TABLE_NAME)


MODEL_ID = "apac.amazon.nova-lite-v1:0"


def get_image_metadata(image_keys):

    if not image_keys:
        return {}

    albums_to_query = defaultdict(set)
    for key in image_keys:
        album_id = os.path.dirname(key)
        albums_to_query[album_id].add(key)

    all_found_items = {}

    for album_id, original_keys_set in albums_to_query.items():
        print(f"파티션 키 '{album_id}'에 대한 메타데이터를 쿼리합니다...")
        try:

            response = metadata_table.query(
                KeyConditionExpression=Key("AlbumID").eq(album_id)
            )

            items_from_db = response.get("Items", [])

            for item in items_from_db:

                if item.get("OriginalKey") in original_keys_set:
                    all_found_items[item["OriginalKey"]] = item

        except ClientError as e:
            print(f"오류: '{album_id}' 쿼리 실패. {e.response['Error']['Message']}")

    return all_found_items


def generate_bedrock_prompt(is_initial, image_metadata, existing_data=None):
    """
    Generates a dynamic Bedrock prompt in English to reduce token usage,
    while ensuring the output remains in Korean.
    The number of categories is flexible based on the image count.
    """

    image_info_text = ""
    for key, meta in image_metadata.items():
        summary = meta.get("ImageSummary", "No summary")
        tags = ", ".join(meta.get("Tags", []))
        image_info_text += (
            f"- Image Key: {key}\n  Summary: {summary}\n  Tags: [{tags}]\n"
        )

    base_prompt = f"""You are an expert AI specializing in intelligently organizing photo albums. Your task is to group images into meaningful categories based on their provided metadata (key, summary, tags).

Follow these rules:
1.  **Dynamic Categories**: Create a suitable number of categories based on the images.
2.  **Categorization Principles**: Group images by specific events (birthdays, holidays), travel/location, or recurring subjects (pets, food).
3.  **Handling Outliers**: If an image doesn't fit any specific theme, place it in a general category named '일상의 순간들' (Daily Moments).
4.  **JSON Output Only**: Strictly adhere to the JSON format. Do not add explanations.
5.  **Korean Language Output**: All text values (`categoryName`, `description`) MUST be in Korean.

JSON Output Structure:
{{
  "categories": [
    {{
      "categoryName": "카테고리 이름",
      "description": "A warm, summary-style sentence for the category, like an album title. (e.g., '2025년 여름, 친구들과 함께한 바다 여행의 추억입니다.' or '우리 강아지의 사랑스러운 성장 기록이에요.')",
      "imageKeys": ["image_key_1.jpg", "image_key_2.png"]
    }}
  ]
}}
---
"""

    if is_initial:
        prompt = f"""{base_prompt}
Analyze the following list of images and group them into optimal new categories.

[Image List to Analyze]
{image_info_text}
"""
    else:
        existing_categories_text = json.dumps(
            existing_data, indent=2, ensure_ascii=False
        )

        incremental_rules = """
**Special Instructions for this Update**:
a. **Prioritize Existing Categories**: First, try to place new images into an existing category if the theme strongly matches.
b. **Threshold for New Categories**: Only create a new category if a group of new images (at least 2-3) shares a strong, distinct theme. Do not create a new category for a single outlier image.
c. **Final Output**: The final output must be a single, complete JSON object that includes all images (both old and new) organized into the final, updated category structure.
---
"""

        prompt = f"""{base_prompt}
{incremental_rules} 
Here is the existing category structure. Please review it before proceeding.
[Existing Categories]
{existing_categories_text}

Now, analyze the new images below and integrate them into the structure according to the rules.

[New Images to Add]
{image_info_text}
"""
    return prompt


def lambda_handler(event, context):
    print(f"이벤트 수신: {json.dumps(event, indent=2)}")

    try:

        input_data = event["body"]
        user_id = input_data["userID"]
        is_initial_sort = input_data["isInitialSort"]

        image_keys_to_process = []
        if is_initial_sort:
            image_keys_to_process = input_data["imageList"]
            existing_sorted_data = None
        else:
            image_keys_to_process = input_data["newImageList"]
            existing_sorted_data = input_data["existingSortData"]

        print(
            f"사용자 '{user_id}'의 정렬 시작. 최초 정렬: {is_initial_sort}, 처리할 이미지 수: {len(image_keys_to_process)}"
        )

        image_metadata = get_image_metadata(image_keys_to_process)
        if not image_metadata:

            print("처리할 이미지 메타데이터가 없습니다. 프로세스를 종료합니다.")

            stats_table.update_item(
                Key={"UserID": user_id},
                UpdateExpression="SET SortStatus = :status REMOVE NewImageKeys",
                ExpressionAttributeValues={":status": "UPDATED"},
            )
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "No new images to process."}),
            }

        prompt = generate_bedrock_prompt(
            is_initial_sort, image_metadata, existing_sorted_data
        )

        native_request = {
            "schemaVersion": "messages-v1",
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 4096, "temperature": 0.3},
        }

        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID, body=json.dumps(native_request)
        )
        model_response = json.loads(response["body"].read())
        result_text = model_response["output"]["message"]["content"][0]["text"]
        print(f"Bedrock 분석 결과 (Raw):\n{result_text}")

        match = re.search(r"\{.*\}", result_text, re.DOTALL)
        if not match:
            raise ValueError("Bedrock 응답에서 유효한 JSON 객체를 찾을 수 없습니다.")

        sorted_result = json.loads(match.group(0))
        print("Bedrock의 JSON 응답을 성공적으로 파싱했습니다.")

        completion_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        stats_table.update_item(
            Key={"UserID": user_id},
            UpdateExpression="SET SortedData = :data, SortStatus = :status, LastSortedAt = :time REMOVE NewImageKeys",
            ExpressionAttributeValues={
                ":data": sorted_result,
                ":status": "UPDATED",
                ":time": completion_time,
            },
        )
        print(f"성공: 사용자 '{user_id}'의 정렬 데이터를 DynamoDB에 저장했습니다.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": f"Successfully sorted and saved data for user {user_id}"}
            ),
        }

    except (ClientError, KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"오류: 정렬 프로세스 중단. {e}")
        raise e
