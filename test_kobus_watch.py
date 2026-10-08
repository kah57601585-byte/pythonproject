"""kobus_watch.py 의 HTML 파싱 테스트 (네트워크 없이 가짜 HTML 로 확인)."""

from kobus_watch import in_time_window, parse_form, parse_schedules, parse_seat_counts

SEARCH_HTML = """
<form id="alcnSrchFrm" name="alcnSrchFrm" method="post">
  <input type="hidden" name="deprCd" value="010">
  <input type="hidden" name="arvlCd" value="700">
  <input type="hidden" name="deprTime" value="">
</form>
<!-- fnSatsChc(deprTime,alcnDeprTime,alcnDeprTrmlNo) -->
<p class="bus_time"><a href="javascript:void(0)"
  onclick="fnSatsChc('20261010','173000','173000','010','700','1','07','0','N','N','010','700','N','N','N','N')">
  <span>17:30</span><span>천일고속</span><span>우등</span><span>잔여 3석</span></a></p>
<p class="bus_time"><span>18:00</span><span>중앙고속</span><span>프리미엄</span><span>매진</span></p>
<p class="bus_time"><a onclick="fnSatsChc('20261010','220000','220000','010','700','3','02','0','N','N','010','700','N','N','N','N')">
  <span>22:00</span><span>동양고속</span><span>심야우등</span></a></p>
"""


def test_parse_schedules_skips_template_and_sold_out():
    schedules = parse_schedules(SEARCH_HTML)
    assert [s.depr_time for s in schedules] == ["173000", "220000"]
    assert schedules[0].hhmm == "17:30"
    assert schedules[0].company == "천일고속"
    assert schedules[0].bus_class == "우등"
    assert schedules[1].bus_class == "심야우등"


def test_schedule_key_differs_by_company():
    a, b = parse_schedules(SEARCH_HTML)
    assert a.key != b.key


def test_parse_form():
    assert parse_form(SEARCH_HTML, "alcnSrchFrm") == [("deprCd", "010"), ("arvlCd", "700"), ("deprTime", "")]
    assert parse_form(SEARCH_HTML, "nope") == []


def test_parse_seat_counts():
    body = """<form id="satsChcFrm">
      <input type="hidden" name="rmnSatsNum" value="2">
      <input type="hidden" name="totSatsNum" value="28">
    </form>"""
    assert parse_seat_counts(body) == (2, 28)
    assert parse_seat_counts("<html></html>") == (None, None)


def test_in_time_window():
    assert in_time_window("170000", 17, 21)
    assert in_time_window("215900", 17, 21)
    assert not in_time_window("220000", 17, 21)
    assert not in_time_window("165900", 17, 21)
