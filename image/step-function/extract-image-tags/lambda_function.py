import base64
import json
import re
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


s3_client = boto3.client("s3")
ssm_client = boto3.client("ssm")

PROMPT = os.environ.get("PROMPT_PARAM")

config = Config(retries={"max_attempts": 100, "mode": "adaptive"})

bedrock_runtime = boto3.client(
    service_name="bedrock-runtime", region_name="ap-northeast-2", config=config
)


model_id = "apac.amazon.nova-lite-v1:0"


def lambda_handler(event, context):
    try:
        source_bucket = event["s3Bucket"]

        original_key = event.get("s3Key", "NONE")
        original_key = event.get("originalKey", original_key)
        processed_key = event.get("newKey", original_key)

    except KeyError as e:
        print(f"오류: 입력 이벤트에 필수 키(s3Bucket 또는 originalKey)가 없습니다: {e}")
        raise e
    print(f"분석할 이미지: s3://{source_bucket}/{processed_key}")

    try:
        prompt_param = ssm_client.get_parameter(Name=PROMPT, WithDecryption=True)
        prompt = prompt_param["Parameter"]["Value"]

    except ClientError as e:
        return {
            "statusCode": 500,
            "body": json.dumps(
                "SSM에서 프롬프트 재정의 값을 가져오는 데 실패했습니다."
            ),
        }

    try:
        response = s3_client.get_object(Bucket=source_bucket, Key=processed_key)
        image_bytes = response["Body"].read()

        image_format = None
        lower_key = processed_key.lower()
        if lower_key.endswith((".jpg", ".jpeg")):
            image_format = "jpeg"
        elif lower_key.endswith(".png"):
            image_format = "png"
        elif lower_key.endswith(".webp"):
            image_format = "webp"

        if not image_format:
            print("오류: 지원하지 않는 이미지 형식입니다 (jpg, png, webp만 지원).")
            return {"statusCode": 400, "body": json.dumps("Unsupported image format")}

        print(f"감지된 이미지 형식: {image_format}")
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        print("이미지를 성공적으로 가져와 Base64로 인코딩했습니다.")
    except ClientError as e:
        print(f"오류: S3에서 이미지를 가져오는 데 실패했습니다. {e}")
        return {"statusCode": 500, "body": json.dumps("Error getting image from S3")}

    message_list = [
        {
            "role": "user",
            "content": [
                {
                    "image": {
                        "format": image_format,
                        "source": {"bytes": base64_image},
                    }
                },
                {"text": prompt},
            ],
        }
    ]

    native_request = {
        "schemaVersion": "messages-v1",
        "messages": message_list,
        "inferenceConfig": {"maxTokens": 2048, "temperature": 0},
    }

    try:
        response = bedrock_runtime.invoke_model(
            modelId=model_id, body=json.dumps(native_request)
        )
        model_response = json.loads(response["body"].read())
        result_text = model_response["output"]["message"]["content"][0]["text"]
        print(f"Bedrock 분석 결과 (Raw):\n{result_text}")

        match = re.search(r"\{.*}", result_text, re.DOTALL)
        if match:
            json_str = match.group(0)
            analysis_result = json.loads(json_str)
            print("Bedrock의 JSON 응답을 성공적으로 파싱했습니다.")
        else:
            print("오류: 응답에서 유효한 JSON 객체를 찾을 수 없습니다.")
            raise ValueError(
                "Could not find a valid JSON object in the Bedrock response"
            )

    except (ClientError, json.JSONDecodeError, ValueError) as e:
        print(f"오류: Bedrock 분석 또는 파싱에 실패했습니다. {e}")
        raise e

    final_output = {
        "source_info": {
            "sourceBucket": source_bucket,
            "sourceKey": original_key,
            "processed_key": processed_key,
        },
        "bedrock_analysis": analysis_result,
    }

    return final_output
