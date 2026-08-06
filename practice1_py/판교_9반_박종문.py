#Python_Practice1_Data.json 활용
#파일 I/O, 예외 처리, Pydantic 검증 파이프라인

# Python_Practice1_Data.json 의 Data 불러오기
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, 'Python_Practice1_Data.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

## 1) 예외 처리 + 파일 읽기
### 함수명 : safe_load_csv()
### 완성파일 없으면 None 반환, logger.error, 성공 시 dict 리스트 반환,
### logger.info, finally에서 '로딩 종료' 출력
### try-except : 기본예외처리 // try-except-as e : 예외 메시지 출력
### try-except-finally : 예외 여부와 상관없이 실행해, raise를 통해 개발자가 예외 작성가능

import csv, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_load_csv(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            data = list(reader)
    except FileNotFoundError as e:
        logger.error(f"파일을 찾을 수 없습니다: {filepath} ({e})")
        return None
    except Exception as e:
        logger.error(f"CSV 로딩 중 예외가 발생했습니다: {e}")
        return None
    else:
        logger.info(f"'{filepath}' 로딩 성공 - {len(data)}개의 행을 읽었습니다.")
        return data
    finally:
        logger.info("로딩 종료")


## 2) Pydantic v2 스키마 정의
### SalesRecord 모델을 완성
### month region: 비어있으면 안됨, amoutn: 0 초과, category: 없어도 됨

from typing import Optional
from pydantic import BaseModel, Field, ValidationError


class SalesRecord(BaseModel):
    region: str = Field(min_length=1)
    month: str = Field(min_length=1)
    amount: int = Field(gt=0)
    category: Optional[str] = None


## 3) 검증 파이프라인 (valid / errors 분리)
### raw_data를 순회하며 SalesRecord로 변환
### 성공->valid, 실패->errors({row,error}) 리스트

def validate_sales(raw_data):
    valid, errors = [], []
    for row in raw_data:
        try:
            record = SalesRecord(
                region=row["region"],
                category=row["category"] or None,
                amount=row["amount"],
                month=row["month"],
            )
        except ValidationError as e:
            logger.error(f"검증 실패: {row} -> {e}")
            errors.append({"row": row, "error": str(e)})
        else:
            valid.append(record)
    return valid, errors


## 4) 결과 파일 저장 + 재로딩 확인
### valid 레코드를 CSV로, errors를 JSON으로 저장하고 다시 읽어 건수를 검증

FIELDNAMES = ["region", "category", "amount", "month"]
SAMPLE_CSV_PATH = os.path.join(BASE_DIR, "sales_sample.csv")
VALID_CSV_PATH = os.path.join(BASE_DIR, "sales_valid.csv")
ERRORS_JSON_PATH = os.path.join(BASE_DIR, "sales_errors.json")


def build_sample_rows(sales):
    """Python_Practice1_Data.json의 Sales 중 앞 4건은 그대로(정상), 이어지는 3건은
    필드 하나씩 비우거나 음수로 바꿔 검증 파이프라인 테스트용 표본을 만든다."""
    valid_samples = sales[:4]
    invalid_samples = [
        {**sales[4], "region": ""},     # region 비어있음 -> invalid
        {**sales[5], "amount": -100},   # amount <= 0 -> invalid
        {**sales[6], "month": ""},      # month 비어있음 -> invalid
    ]
    return valid_samples + invalid_samples


def write_csv(filepath, rows):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main():
    # 존재하지 않는 파일 -> None 반환 확인
    assert safe_load_csv(os.path.join(BASE_DIR, "존재하지않는파일.csv")) is None
    logger.info("safe_load_csv: 없는 파일에 대해 None 반환 확인 완료")

    # 검증 파이프라인 테스트용 샘플 CSV 생성 (4건 valid + 3건 invalid) 후 로드
    write_csv(SAMPLE_CSV_PATH, build_sample_rows(data["Sales"]))
    raw_data = safe_load_csv(SAMPLE_CSV_PATH)
    assert raw_data is not None

    valid, errors = validate_sales(raw_data)
    assert len(valid) == 4, f"valid 4건 예상, 실제 {len(valid)}건"
    assert len(errors) == 3, f"errors 3건 예상, 실제 {len(errors)}건"
    logger.info(f"검증 결과 - valid: {len(valid)}건, errors: {len(errors)}건")

    write_csv(VALID_CSV_PATH, [record.model_dump() for record in valid])
    with open(ERRORS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    reloaded = safe_load_csv(VALID_CSV_PATH)
    assert reloaded is not None
    assert len(reloaded) == 4, f"재로딩 4건 예상, 실제 {len(reloaded)}건"
    logger.info(f"재로딩 확인 완료 - {len(reloaded)}건")


if __name__ == "__main__":
    main()
