"""pipeline.py의 Pydantic 스키마 검증 테스트.

각 모델마다 정상 케이스 1개와, 범위(range)/타입(type) 위반을 각각 유발하는
비정상 케이스가 ValidationError를 발생시키는지 확인한다.
"""

import pytest
from pydantic import ValidationError

from pipeline import (
    CombinedRecord,
    CountryInfo,
    Currency,
    HourlyForecast,
    IPLocation,
    WeatherForecast,
)

# ---- WeatherForecast / HourlyForecast ----

def test_weather_forecast_valid():
    weather = WeatherForecast(
        latitude=37.5665,
        longitude=126.9780,
        timezone="Asia/Seoul",
        hourly=HourlyForecast(time=["2026-08-06T00:00"], temperature_2m=[28.3], precipitation_probability=[18]),
    )
    assert weather.latitude == 37.5665
    assert weather.hourly.temperature_2m == [28.3]


def test_weather_forecast_latitude_out_of_range():
    with pytest.raises(ValidationError):
        WeatherForecast(
            latitude=999,  # 범위(-90~90) 초과
            longitude=126.9780,
            timezone="Asia/Seoul",
            hourly=HourlyForecast(time=["t"], temperature_2m=[20.0], precipitation_probability=[10]),
        )


def test_hourly_forecast_precipitation_probability_out_of_range():
    with pytest.raises(ValidationError):
        HourlyForecast(time=["t"], temperature_2m=[20.0], precipitation_probability=[150])  # 0~100 초과


def test_hourly_forecast_temperature_type_error():
    with pytest.raises(ValidationError):
        HourlyForecast(time=["t"], temperature_2m=["not-a-number"], precipitation_probability=[10])


# ---- CountryInfo / Currency ----

def test_country_info_valid():
    country = CountryInfo(
        name="Korea (Republic of)",
        capital="Seoul",
        region="Asia",
        population=51780579,
        currencies=[Currency(code="KRW", name="South Korean won", symbol="₩")],
    )
    assert country.population == 51780579
    assert country.currencies[0].code == "KRW"


def test_country_info_population_not_positive():
    with pytest.raises(ValidationError):
        CountryInfo(name="X", capital="Y", region="Asia", population=0, currencies=[])


def test_country_info_empty_name_rejected():
    with pytest.raises(ValidationError):
        CountryInfo(name="", capital="Y", region="Asia", population=100, currencies=[])


# ---- IPLocation ----

def test_ip_location_valid():
    ip = IPLocation(
        status="success", country="United States", city="Ashburn", lat=39.03, lon=-77.5, isp="Google LLC", query="8.8.8.8"
    )
    assert ip.status == "success"


def test_ip_location_invalid_status_literal():
    with pytest.raises(ValidationError):
        IPLocation(status="unknown", country="US", city="Ashburn", lat=0, lon=0, isp="Google", query="8.8.8.8")


def test_ip_location_longitude_out_of_range():
    with pytest.raises(ValidationError):
        IPLocation(status="success", country="US", city="Ashburn", lat=0, lon=200, isp="Google", query="8.8.8.8")


# ---- CombinedRecord ----

def test_combined_record_valid():
    record = CombinedRecord(
        time="2026-08-06T00:00",
        temperature_2m=28.3,
        precipitation_probability=18,
        country_name="Korea",
        capital="Seoul",
        population=51780579,
        ip_query="8.8.8.8",
        ip_country="United States",
        isp="Google LLC",
    )
    assert record.precipitation_probability == 18


def test_combined_record_population_not_positive():
    with pytest.raises(ValidationError):
        CombinedRecord(
            time="t",
            temperature_2m=20.0,
            precipitation_probability=10,
            country_name="Korea",
            capital="Seoul",
            population=-1,
            ip_query="8.8.8.8",
            ip_country="US",
            isp="Google",
        )


def test_combined_record_temperature_type_error():
    with pytest.raises(ValidationError):
        CombinedRecord(
            time="t",
            temperature_2m="hot",  # 타입 오류
            precipitation_probability=10,
            country_name="Korea",
            capital="Seoul",
            population=100,
            ip_query="8.8.8.8",
            ip_country="US",
            isp="Google",
        )
