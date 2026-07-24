from utils import date_utils


def test_parse_m_d_yy_accepts_2_digit_year():
    date_obj = date_utils.parse_m_d_yy("11/7/25")
    assert date_obj["disp_time"] == "07-Nov-2025"


def test_parse_m_d_yy_accepts_4_digit_year():
    # Regression test: Schwab has been seen exporting this format too (not
    # just the 2-digit year), which used to raise
    # "ValueError: unconverted data remains: <last 2 digits>".
    date_obj = date_utils.parse_m_d_yy("07/08/2026")
    assert date_obj["disp_time"] == "08-Jul-2026"


def test_parse_m_d_yy_same_calendar_day_regardless_of_year_format():
    assert (
        date_utils.parse_m_d_yy("7/8/26")["time_in_millis"]
        == date_utils.parse_m_d_yy("07/08/2026")["time_in_millis"]
    )
