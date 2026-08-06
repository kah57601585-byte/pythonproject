"""
데이터 수집 미니 파이프라인
--------------------------
httpx.AsyncClient + asyncio.gather()로 서로 다른 3개의 공개 API(날씨 / 국가정보 / IP 위치정보)를
동시에 호출하고, 각 응답을 Pydantic 모델로 검증한 뒤 결과를 출력한다.

대상 API
    1) Open-Meteo    - 서울 3일 시간별 기온/강수확률 예보
    2) countries.dev - 대한민국(KOR) 국가 정보
    3) ip-api.com    - IP(8.8.8.8) 위치 정보

변경내역
    v1 - 최초 작성 (asyncio.gather 기반 동시 수집 + Pydantic 검증)
"""

import asyncio
import logging
import os
import time
from typing import Annotated, Literal

import httpx
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Percent = Annotated[int, Field(ge=0, le=100)]
Temperature = Annotated[float, Field(ge=-90, le=60)]  # 지구 관측 기온의 물리적 한계

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=37.5665&longitude=126.9780"
    "&hourly=temperature_2m,precipitation_probability"
    "&forecast_days=3&timezone=Asia/Seoul"
)
COUNTRY_URL = "https://countries.dev/alpha/KOR"
IP_URL = "http://ip-api.com/json/8.8.8.8"
REQUEST_TIMEOUT = 10.0


## Pydantic 스키마 - 각 API 응답에서 필요한 필드만 추출해 타입/범위를 검증
class HourlyForecast(BaseModel):
    time: list[str]
    temperature_2m: list[Temperature]
    precipitation_probability: list[Percent]


class WeatherForecast(BaseModel):
    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(min_length=1)
    hourly: HourlyForecast


class Currency(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    symbol: str = Field(min_length=1)


class CountryInfo(BaseModel):
    name: str = Field(min_length=1)
    capital: str = Field(min_length=1)
    region: str = Field(min_length=1)
    population: int = Field(gt=0)
    currencies: list[Currency]


class IPLocation(BaseModel):
    status: Literal["success", "fail"]
    country: str = Field(min_length=1)
    city: str = Field(min_length=1)
    lat: Latitude
    lon: Longitude
    isp: str = Field(min_length=1)
    query: str = Field(min_length=1)


class CombinedRecord(BaseModel):
    """3개 API 결과를 시간별 1행으로 합친 저장용 스키마 (CSV/Parquet 비교용)."""

    time: str = Field(min_length=1)
    temperature_2m: Temperature
    precipitation_probability: Percent
    country_name: str = Field(min_length=1)
    capital: str = Field(min_length=1)
    population: int = Field(gt=0)
    ip_query: str = Field(min_length=1)
    ip_country: str = Field(min_length=1)
    isp: str = Field(min_length=1)


async def fetch_json(client: httpx.AsyncClient, name: str, url: str) -> dict | None:
    """지정한 API를 호출해 JSON을 반환한다. 네트워크/HTTP 오류는 로깅 후 None을 반환한다."""
    try:
        response = await client.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except httpx.TimeoutException as e:
        logger.error(f"[{name}] 응답 시간 초과: {e}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"[{name}] HTTP 오류 {e.response.status_code}: {e}")
        return None
    except httpx.RequestError as e:
        logger.error(f"[{name}] 요청 실패: {e}")
        return None
    return response.json()


async def collect_all() -> dict:
    """3개 API를 asyncio.gather()로 동시에 호출하고, 각 결과를 Pydantic 모델로 검증한다."""
    async with httpx.AsyncClient() as client:
        weather_json, country_json, ip_json = await asyncio.gather(
            fetch_json(client, "weather", WEATHER_URL),
            fetch_json(client, "country", COUNTRY_URL),
            fetch_json(client, "ip", IP_URL),
        )

    sources = (
        ("weather", WeatherForecast, weather_json),
        ("country", CountryInfo, country_json),
        ("ip", IPLocation, ip_json),
    )

    results = {}
    for name, model, raw in sources:
        if raw is None:
            results[name] = None
            continue
        try:
            results[name] = model.model_validate(raw)
        except ValidationError as e:
            logger.error(f"[{name}] 검증 실패: {e}")
            results[name] = None
    return results


def print_results(results: dict) -> None:
    weather = results["weather"]
    if weather:
        print(
            f"[날씨] 서울({weather.latitude}, {weather.longitude}) - "
            f"첫 시간대 기온 {weather.hourly.temperature_2m[0]}°C, "
            f"강수확률 {weather.hourly.precipitation_probability[0]}%"
        )

    country = results["country"]
    if country:
        currencies = ", ".join(f"{c.name}({c.code})" for c in country.currencies)
        print(f"[국가] {country.name} - 수도 {country.capital}, 인구 {country.population:,}명, 통화 {currencies}")

    ip_location = results["ip"]
    if ip_location:
        print(
            f"[IP] {ip_location.query} - {ip_location.country} {ip_location.city} "
            f"({ip_location.lat}, {ip_location.lon}), ISP: {ip_location.isp}"
        )

    failed = [name for name, value in results.items() if value is None]
    if failed:
        logger.warning(f"수집 실패한 항목: {failed}")


def build_combined_records(
    weather: WeatherForecast, country: CountryInfo, ip_location: IPLocation
) -> list[CombinedRecord]:
    """시간별 날씨 데이터 1행마다 국가/IP 정보를 붙여 CombinedRecord로 재검증한다.

    이미 검증된 값들을 다시 조합하는 것이라 정상적으로는 실패하지 않지만,
    저장 스키마(CombinedRecord) 기준의 타입/범위 오류를 방어적으로 처리한다.
    """
    records = []
    hourly = weather.hourly
    for hour_time, temp, precip in zip(
        hourly.time, hourly.temperature_2m, hourly.precipitation_probability
    ):
        try:
            record = CombinedRecord(
                time=hour_time,
                temperature_2m=temp,
                precipitation_probability=precip,
                country_name=country.name,
                capital=country.capital,
                population=country.population,
                ip_query=ip_location.query,
                ip_country=ip_location.country,
                isp=ip_location.isp,
            )
        except ValidationError as e:
            logger.error(f"[combined] 행 검증 실패 (time={hour_time}): {e}")
            continue
        records.append(record)
    return records


def save_and_benchmark(records: list[CombinedRecord], output_dir: str) -> None:
    """동일 데이터를 CSV/Parquet로 각각 저장하고, 저장 소요 시간과 파일 크기를 비교 출력한다."""
    os.makedirs(output_dir, exist_ok=True)
    df = pd.DataFrame([record.model_dump() for record in records])

    csv_path = os.path.join(output_dir, "collected_records.csv")
    parquet_path = os.path.join(output_dir, "collected_records.parquet")

    start = time.perf_counter()
    df.to_csv(csv_path, index=False, encoding="utf-8")
    csv_elapsed_ms = (time.perf_counter() - start) * 1000
    csv_size = os.path.getsize(csv_path)

    start = time.perf_counter()
    df.to_parquet(parquet_path, index=False)
    parquet_elapsed_ms = (time.perf_counter() - start) * 1000
    parquet_size = os.path.getsize(parquet_path)

    print(f"\n[저장 성능 비교] 총 {len(records)}행")
    print(f"  CSV     - 저장 시간: {csv_elapsed_ms:.2f}ms, 파일 크기: {csv_size:,} bytes")
    print(f"  Parquet - 저장 시간: {parquet_elapsed_ms:.2f}ms, 파일 크기: {parquet_size:,} bytes")
    if csv_size:
        print(f"  Parquet 파일 크기가 CSV 대비 {(1 - parquet_size / csv_size) * 100:.1f}% 더 작음")


def main() -> None:
    results = asyncio.run(collect_all())
    print_results(results)

    weather, country, ip_location = results["weather"], results["country"], results["ip"]
    if weather and country and ip_location:
        records = build_combined_records(weather, country, ip_location)
        save_and_benchmark(records, OUTPUT_DIR)
    else:
        logger.warning("일부 API 수집/검증에 실패해 저장 단계를 건너뜁니다.")


if __name__ == "__main__":
    main()
