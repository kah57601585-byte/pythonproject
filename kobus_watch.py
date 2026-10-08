"""고속버스(KOBUS) 취소표 감시 + 알림 스크립트.

고속버스 잔여석을 알려주는 공식 Open API는 없다.
(공공데이터포털 TAGO 고속버스정보 API는 시간표·요금만 주고 잔여석은 없음)
그래서 고속버스통합예매(kobus.co.kr) 웹이 내부적으로 쓰는 요청을 그대로 흉내 내서
원하는 노선/날짜/시간대의 잔여석을 주기적으로 확인하고, 자리가 생기면 알림을 보낸다.

흐름
  1. GET  /main.do               : 세션 쿠키 발급
  2. POST /mrs/alcnSrch.do       : 배차 조회(HTML) -> fnSatsChc('...') 인자로 배차 목록 파싱
  3. POST /mrs/satschc.do        : 배차별 좌석 선택 화면 -> rmnSatsNum(잔여석) 확인
  4. 잔여석이 0 -> 1 이상으로 바뀐 배차가 있으면 텔레그램 / ntfy 로 알림

예매(좌석 선점·결제)는 하지 않는다. 알림 받으면 앱/웹에서 직접 예매할 것.
요청 간격은 기본 60초 이상으로 두고, 개인 용도로만 사용하자.

사용 예
  # 터미널 코드 찾기
  python kobus_watch.py terminals 부산
  # 서울경부(010) -> 부산(700), 10/10 17~21시 출발 감시
  python kobus_watch.py watch --depart 010 --arrive 700 --date 20261010 --from 17 --to 21

알림 설정(환경변수, 둘 중 하나 이상)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID : 텔레그램 봇
  NTFY_TOPIC                           : ntfy.sh 토픽 (폰에 ntfy 앱 설치 후 같은 토픽 구독)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import requests

BASE_URL = "https://www.kobus.co.kr"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
TIMEOUT = 20
MIN_INTERVAL = 30  # 초. 이보다 짧게 두드리면 차단당하기 쉽다.

# 실제 호출만 잡도록 '(' 바로 뒤에 따옴표가 오는 것만 매칭.
# (응답 HTML 주석 안에 fnSatsChc(deprTime, ...) 형태의 템플릿이 있음)
FN_SATS_RE = re.compile(r"fnSatsChc\(\s*('.*?)\)", re.DOTALL)
ARG_RE = re.compile(r"'([^']*)'")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FORM_RE = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.DOTALL | re.IGNORECASE)
INPUT_RE = re.compile(r"<input\b([^>]+)>", re.DOTALL | re.IGNORECASE)
ATTR_RE = re.compile(r"([\w:-]+)=[\"']([^\"']*)[\"']")
TAG_RE = re.compile(r"<[^>]+>")
MIN_SATS_ARGS = 14  # 인자 개수가 이보다 적으면 템플릿/불완전한 호출


@dataclass
class Schedule:
    depr_time: str  # HHMMSS
    args: list[str]
    bus_class: str | None = None
    company: str | None = None
    remaining: int | None = None
    total: int | None = None

    @property
    def key(self) -> str:
        # 같은 시간에 여러 회사/등급 배차가 있을 수 있어서 인자 전체를 키로 쓴다
        return "|".join(self.args[1:8])

    @property
    def hhmm(self) -> str:
        return f"{self.depr_time[:2]}:{self.depr_time[2:4]}"


# ---- HTML 파싱 ----

def _attrs(fragment: str) -> dict[str, str]:
    return {k.lower(): html.unescape(v) for k, v in ATTR_RE.findall(fragment)}


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s))).strip()


def parse_form(body: str, form_id: str) -> list[tuple[str, str]]:
    """id 또는 name 이 form_id 인 <form> 의 input (name, value) 목록."""
    for attr_text, form_body in FORM_RE.findall(body):
        a = _attrs(attr_text)
        if form_id in (a.get("id"), a.get("name")):
            return [
                (ia["name"], ia.get("value", ""))
                for ia in map(_attrs, INPUT_RE.findall(form_body))
                if ia.get("name")
            ]
    return []


def parse_schedules(body: str) -> list[Schedule]:
    """배차 조회 HTML에서 좌석 선택 가능한 배차 목록을 뽑는다.

    매진 배차는 fnSatsChc 링크가 없으므로 여기 안 나온다.
    즉 취소표가 생기면 이 목록에 새로 나타난다.
    """
    visible = HTML_COMMENT_RE.sub(" ", body)
    matches = list(FN_SATS_RE.finditer(visible))
    schedules: list[Schedule] = []
    for i, m in enumerate(matches):
        args = ARG_RE.findall(m.group(1))
        if len(args) < MIN_SATS_ARGS:
            continue
        # 회사/등급 텍스트는 표시용(best-effort). 링크 뒤쪽(다음 배차 전까지)을 먼저 보고 없으면 앞쪽을 본다.
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(visible)
        after = _strip_tags(visible[m.end() : min(next_start, m.end() + 400)])
        before = _strip_tags(visible[max(0, m.start() - 400) : m.start()])
        schedules.append(
            Schedule(
                depr_time=args[1],
                args=args,
                bus_class=_find(r"심야프리미엄|심야우등|프리미엄|우등|일반", after, before),
                company=_find(r"[가-힣]+고속|[가-힣]+여객|[가-힣]+버스", after, before),
            )
        )
    return schedules


def _find(pattern: str, after: str, before: str) -> str | None:
    if m := re.search(pattern, after):
        return m.group(0)
    found = re.findall(pattern, before)
    return found[-1] if found else None


def parse_seat_counts(body: str) -> tuple[int | None, int | None]:
    """좌석 선택 화면에서 (잔여석, 전체석)."""
    fields = dict(parse_form(body, "satsChcFrm"))

    def to_int(v: str | None) -> int | None:
        return int(v) if v and v.strip().isdigit() else None

    return to_int(fields.get("rmnSatsNum")), to_int(fields.get("totSatsNum"))


def in_time_window(hhmmss: str, start_hour: int, end_hour: int) -> bool:
    """start_hour 시 00분 ~ end_hour 시 59분 사이 출발인지."""
    hour = int(hhmmss[:2])
    return start_hour <= hour <= end_hour


# ---- KOBUS 요청 ----

class Kobus:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})

    def _post(self, path: str, data, referer: str) -> requests.Response:
        r = self.s.post(f"{BASE_URL}{path}", data=data, headers={"Referer": referer}, timeout=TIMEOUT)
        r.raise_for_status()
        return r

    def start(self) -> None:
        self.s.get(f"{BASE_URL}/main.do", timeout=TIMEOUT).raise_for_status()

    def routes(self) -> list[dict]:
        r = self._post("/mrs/readRotLinInf.ajax", {}, f"{BASE_URL}/mrs/rotinf.do")
        return r.json().get("rotInfList", [])

    def search(self, depart: str, arrive: str, date: str) -> tuple[str, list[Schedule]]:
        body = self._post(
            "/mrs/alcnSrch.do",
            {
                "deprCd": depart,
                "arvlCd": arrive,
                "pathDvs": "sngl",
                "pathStep": "1",
                "deprDtm": date,
                "busClsCd": "0",  # 전체 등급
                "rtrpChc": "1",
                "timeLinkMin": "00",
                "timeLinkMax": "23",
            },
            f"{BASE_URL}/main.do",
        ).text
        return body, parse_schedules(body)

    def seat_counts(self, search_body: str, sch: Schedule) -> tuple[int | None, int | None]:
        a = sch.args
        overrides = {
            "deprTime": a[1],
            "alcnDeprTime": a[2],
            "alcnDeprTrmlNo": a[3],
            "alcnArvlTrmlNo": a[4],
            "indVBusClsCd": a[5],
            "cacmCd": a[6],
            "dcDvsCd": a[7],
            "prvtBbizEmpAcmtRt": a[8],
            "chldSftySatsYn": a[12],
            "dsprSatsYn": a[13],
        }
        form = [(k, overrides.get(k, v)) for k, v in parse_form(search_body, "alcnSrchFrm")]
        body = self._post("/mrs/satschc.do", form, f"{BASE_URL}/mrs/alcnSrch.do").text
        return parse_seat_counts(body)


# ---- 알림 ----

def notify(title: str, message: str) -> None:
    sent = False
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": f"{title}\n{message}"},
                timeout=10,
            ).raise_for_status()
            sent = True
        except requests.RequestException as e:
            print(f"[warn] 텔레그램 전송 실패: {e}", file=sys.stderr)
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        try:
            # JSON 으로 보내야 제목에 한글을 넣을 수 있다
            requests.post(
                "https://ntfy.sh/",
                json={
                    "topic": topic,
                    "title": title,
                    "message": message,
                    "priority": 5,
                    "click": "https://www.kobus.co.kr",
                },
                timeout=10,
            ).raise_for_status()
            sent = True
        except requests.RequestException as e:
            print(f"[warn] ntfy 전송 실패: {e}", file=sys.stderr)
    if not sent:
        print("\a", end="")  # 알림 설정이 없으면 터미널 벨이라도
    print(f"[알림] {title} - {message}")


# ---- 명령 ----

def cmd_terminals(args: argparse.Namespace) -> None:
    kobus = Kobus()
    kobus.start()
    for route in kobus.routes():
        line = json.dumps(route, ensure_ascii=False)
        if args.keyword in line:
            print(line)


def check_once(kobus: Kobus, args: argparse.Namespace) -> list[Schedule]:
    body, schedules = kobus.search(args.depart, args.arrive, args.date)
    available = []
    for sch in schedules:
        if not in_time_window(sch.depr_time, args.start_hour, args.end_hour):
            continue
        if args.bus_class and (sch.bus_class or "") not in args.bus_class:
            continue
        sch.remaining, sch.total = kobus.seat_counts(body, sch)
        time.sleep(1)  # 배차별 조회 사이에도 살짝 쉬기
        if sch.remaining:
            available.append(sch)
    return available


def cmd_watch(args: argparse.Namespace) -> None:
    interval = max(args.interval, MIN_INTERVAL)
    kobus = Kobus()
    kobus.start()
    # 시작 시점에 이미 자리 있는 배차도 알리고, 이후엔 '새로 생긴' 자리만 알린다
    known: dict[str, int] = {}
    fails = 0
    print(
        f"감시 시작: {args.depart} -> {args.arrive}, {args.date} "
        f"{args.start_hour:02d}~{args.end_hour:02d}시, {interval}초 간격 (Ctrl+C 로 종료)"
    )
    while True:
        try:
            available = check_once(kobus, args)
            fails = 0
        except requests.RequestException as e:
            fails += 1
            print(f"[{datetime.now().astimezone():%H:%M:%S}] 조회 실패({fails}): {e}", file=sys.stderr)
            if fails >= 5:
                notify("고속버스 감시 오류", f"연속 {fails}회 조회 실패: {e}")
                fails = 0
            kobus = Kobus()  # 세션 새로 시작
            try:
                kobus.start()
            except requests.RequestException:
                pass
            time.sleep(interval)
            continue

        now = {s.key: s.remaining or 0 for s in available}
        new = [s for s in available if s.key not in known]
        summary = ", ".join(f"{s.hhmm}({s.remaining})" for s in available) or "없음"
        print(f"[{datetime.now().astimezone():%H:%M:%S}] 잔여석 있는 배차: {summary}")
        if new:
            lines = [
                f"{s.hhmm} {s.company or ''} {s.bus_class or ''} 잔여 {s.remaining}"
                + (f"/{s.total}" if s.total else "")
                for s in new
            ]
            notify(
                f"고속버스 취소표! {args.date[4:6]}/{args.date[6:]}",
                f"{args.depart}->{args.arrive}\n" + "\n".join(lines),
            )
            if args.once_found:
                return
        known = now
        time.sleep(interval + random.uniform(0, interval * 0.3))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="고속버스(KOBUS) 취소표 감시")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("terminals", help="노선/터미널 코드 검색")
    t.add_argument("keyword", help="터미널 이름 일부 (예: 부산, 센트럴)")
    t.set_defaults(func=cmd_terminals)

    w = sub.add_parser("watch", help="잔여석 감시")
    w.add_argument("--depart", required=True, help="출발 터미널 코드 (예: 010 서울경부)")
    w.add_argument("--arrive", required=True, help="도착 터미널 코드 (예: 700 부산)")
    w.add_argument("--date", required=True, help="출발일 YYYYMMDD")
    w.add_argument("--from", dest="start_hour", type=int, default=0, help="이 시(時) 이후 출발 (기본 0)")
    w.add_argument("--to", dest="end_hour", type=int, default=23, help="이 시(時) 까지 출발 (기본 23)")
    w.add_argument("--class", dest="bus_class", nargs="*", help="등급 필터 (예: 우등 프리미엄)")
    w.add_argument("--interval", type=int, default=60, help=f"조회 간격 초 (최소 {MIN_INTERVAL})")
    w.add_argument("--once-found", action="store_true", help="한 번 알림 보내면 종료")
    w.set_defaults(func=cmd_watch)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
