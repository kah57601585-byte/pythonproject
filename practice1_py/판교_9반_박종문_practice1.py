# Python_Practice1_Data.json 의 Data 불러오기
import json

with open('practice1_py/Python_Practice1_Data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# TODO:
# 1. 리스트/딕셔너리 컴프리헨션
## Python_Practice1.Data.json(Sales) 리스트에서
## 1) amount >= 1000 인 거래만 필터링
## 2) 지역별 총매출 dict를 컴프리헨션으로 계산

filtered_sales = [sale for sale in data["Sales"] if sale["amount"] >= 1000]
print("Filtered Sales (amount >= 1000):", filtered_sales)

regions = {sale["region"] for sale in data["Sales"]}
print(regions)

region_total = {region: sum(sale["amount"] for sale in data["Sales"] if sale["region"] == region) for region in regions}
print("지역별 총매출:", region_total)

# TODO:
# 2. Counter + defaultdict
## Counter로 지역별 거래 건수를, defaultdict로 카테고리별 amount 리스트

from collections import Counter, defaultdict

region_counter = Counter(sale["region"] for sale in data["Sales"])
print("지역별 거래 건수:", region_counter)

category_amounts = defaultdict(list)
for sale in data["Sales"]:
    category_amounts[sale["category"]].append(sale["amount"])
print("카테고리별 amount 리스트:", dict(category_amounts))

# TODO:
# 3. 제네레이터-메모리 비교
## amount > 1000 인 행만 yield 하는 제네레이터를 작성하고 리스트 버전과 메모리 크기를 비교

import sys


def high_amount_generator(sales):
    for sale in sales:
        if sale["amount"] > 1000:
            yield sale


high_amount_list = [sale for sale in data["Sales"] if sale["amount"] > 1000]
high_amount_gen = high_amount_generator(data["Sales"])

print("리스트 메모리 크기:", sys.getsizeof(high_amount_list), "bytes")
print("제네레이터 메모리 크기:", sys.getsizeof(high_amount_gen), "bytes")

# TODO:
# 4. 종합 - 월별 카테고리 매출 집계
## sales 데이터를 month, category 기준으로 그룹핑해 총매출 dict를 완성 (컴프리헨션 + defaultdict)

month_category_amounts = defaultdict(list)
for sale in data["Sales"]:
    month_category_amounts[(sale["month"], sale["category"])].append(sale["amount"])

monthly_category_total = {key: sum(amounts) for key, amounts in month_category_amounts.items()}
print("월별 카테고리 매출 집계:", monthly_category_total)
