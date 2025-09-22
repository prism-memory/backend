import json
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):

    messages = event.get("Messages", [])
    if not messages:
        logger.info("처리할 메시지가 없습니다.")
        return {"successful_jobs": [], "failed_messages": [], "messages_to_delete": []}

    logger.info(f"총 {len(messages)}개의 메시지 처리를 시작합니다.")

    successful_jobs = []
    failed_messages = []
    messages_to_delete = []

    for message in messages:
        message_id = message.get("MessageId", "N/A")
        receipt_handle = message.get("ReceiptHandle", "N/A")

        try:

            body_str = message.get("Body")
            if not body_str:
                raise ValueError("메시지 'body'가 비어있습니다.")

            body_data = json.loads(body_str)

            job_info = body_data.get("MessageBody", body_data)

            if (
                not isinstance(job_info, dict)
                or "sourceKey" not in job_info
                or "avifEncoding" not in job_info
            ):
                raise ValueError(
                    "'sourceKey' 또는 'avifEncoding' 필드가 누락되었습니다."
                )

            encoding_dict = job_info["avifEncoding"]

            job_info["avifEncoding"] = {
                key: str(value) for key, value in encoding_dict.items()
            }

            successful_jobs.append(job_info)

            messages_to_delete.append(
                {"Id": message_id, "ReceiptHandle": receipt_handle}
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:

            logger.error(f"메시지(ID: {message_id}) 처리 중 오류 발생: {e}")
            failed_messages.append(
                {
                    "message_id": message_id,
                    "error": str(e),
                    "original_message_body": message.get("body"),
                }
            )

    logger.info(f"성공: {len(successful_jobs)}개, 실패: {len(failed_messages)}개")

    return {
        "successful_jobs": successful_jobs,
        "failed_messages": failed_messages,
        "messages_to_delete": messages_to_delete,
    }
