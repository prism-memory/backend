import boto3
import os
import json
import urllib.parse
from botocore.exceptions import ClientError

s3_client = boto3.client("s3")
rekognition_client = boto3.client("rekognition")

# KEY: 차단할 Rekognition 레이블 이름
# VALUE: 해당 레이블을 차단할 최소 신뢰도(Confidence) 점수 (0-100)
MODERATION_POLICY = {
    "Explicit Nudity": 80.0,
    "Suggestive": 95.0,
    "Violence": 90.0,
    # "Drugs & Tobacco": 85.0,
    # "Smoking": 85.0,
    "Hate Symbols": 95.0,
    "Rude Gestures": 95.0,
}
# ---------------------------------------------


def lambda_handler(event, context):
    try:
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(
            event["Records"][0]["s3"]["object"]["key"], encoding="utf-8"
        )
    except (KeyError, IndexError):
        print("S3 이벤트 파싱 오류")
        return {"statusCode": 400, "body": "Invalid S3 event format"}

    print(f"처리 시작: s3://{bucket}/{key}")

    try:
        response = rekognition_client.detect_moderation_labels(
            Image={"S3Object": {"Bucket": bucket, "Name": key}}, MinConfidence=80.0
        )

        detected_labels = []
        if "ModerationLabels" in response:
            for label in response["ModerationLabels"]:
                label_name = label["Name"]
                parent_name = label.get("ParentName")
                confidence = label["Confidence"]

                if label_name in MODERATION_POLICY:
                    if confidence >= MODERATION_POLICY[label_name]:
                        detected_labels.append(
                            {"Name": label_name, "Confidence": f"{confidence:.2f}%"}
                        )
                elif parent_name and parent_name in MODERATION_POLICY:
                    if confidence >= MODERATION_POLICY[parent_name]:
                        detected_labels.append(
                            {
                                "Name": label_name,
                                "ParentName": parent_name,
                                "Confidence": f"{confidence:.2f}%",
                            }
                        )

        if detected_labels:
            unique_detected_labels = [
                dict(t) for t in {tuple(d.items()) for d in detected_labels}
            ]
            print(f"부적절한 콘텐츠 감지: {unique_detected_labels}")
            s3_client.delete_object(Bucket=bucket, Key=key)

        else:
            print("이미지가 정상입니다. 다른 버킷으로 이동합니다.")
            destination_bucket = os.environ.get("DESTINATION_BUCKET")
            if not destination_bucket:
                print(
                    "DESTINATION_BUCKET 환경 변수가 설정되지 않아 파일을 이동할 수 없습니다."
                )
                return

            copy_source = {"Bucket": bucket, "Key": key}
            s3_client.copy_object(
                CopySource=copy_source, Bucket=destination_bucket, Key=key
            )
            s3_client.delete_object(Bucket=bucket, Key=key)
            print(
                f"파일 이동 완료: s3://{bucket}/{key} -> s3://{destination_bucket}/{key}"
            )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print(f"AWS ClientError 발생: {error_code}")
        return {"statusCode": 500, "body": f"AWS ClientError: {error_code}"}

    except Exception as e:
        print(f"처리 중 알 수 없는 오류 발생: {e}")
        return {"statusCode": 500, "body": f"An unexpected error occurred: {str(e)}"}

    return {"statusCode": 200, "body": f"Successfully processed {key}."}
