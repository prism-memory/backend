import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):

    map_result = event.get("mapResult", [])
    logger.info(f"Map 결과: {json.dumps(map_result, ensure_ascii=False)}")

    lambda_output = event.get("lamdaOutput", {})
    logger.info(f"원본 메시지: {json.dumps(lambda_output, ensure_ascii=False)}")

    logger.info(f"총 {len(map_result)}개의 작업 결과를 필터링합니다.")

    messages_to_delete_list = lambda_output.get("messages_to_delete", [])

    logger.info(
        f"삭제할 원본 메시지 후보: {json.dumps(messages_to_delete_list, ensure_ascii=False)}"
    )
    logger.info(f"총 {len(map_result)}개의 작업 결과를 필터링합니다.")

    successful_entries = []

    for index, job_summary in enumerate(map_result):
        if job_summary.get("Status") == "SUCCEEDED":
            try:
                message_to_delete = messages_to_delete_list[index]

                successful_entries.append(
                    {
                        "Id": message_to_delete["Id"],
                        "ReceiptHandle": message_to_delete["ReceiptHandle"],
                    }
                )
                logger.info(
                    f"성공 작업(JobId: {job_summary.get('JobId', 'N/A')})에 해당하는 메시지(Id: {message_to_delete['Id']})를 삭제 목록에 추가했습니다."
                )
            except IndexError:
                logger.error(
                    f"오류: Map 결과 인덱스 {index}에 해당하는 원본 메시지가 없습니다."
                )
            except KeyError:
                logger.error(
                    f"오류: 메시지 객체에 'Id' 또는 'ReceiptHandle' 키가 없습니다. 메시지: {message_to_delete}"
                )

    logger.info(f"최종 삭제 목록: {json.dumps(successful_entries, ensure_ascii=False)}")

    return successful_entries
