"""Regressões adicionais do contrato financeiro e da agregação."""

from datetime import datetime, timedelta, timezone

import pytest
from helpers import PROJECT_ROOT, run_cli

from onfly_report.repositories.csv_rate_repository import CsvRateRepository
from onfly_report.repositories.csv_reservation_repository import CsvReservationRepository
from onfly_report.services.report_builder import ReportBuilder


def test_empty_input_has_zero_summary_and_empty_groups(tmp_path):
    report = run_cli(tmp_path, [])
    assert report["summary"] == {
        "total_reservations": 0,
        "confirmed_reservations": 0,
        "cancelled_reservations": 0,
        "no_show_reservations": 0,
        "total_room_nights": 0,
        "total_amount_brl": "0.00",
        "average_nightly_rate_brl": "0.00",
    }
    assert report["by_month"] == report["top_hotels"] == []


def test_non_billable_rows_never_create_months_or_hotels(tmp_path):
    report = run_cli(tmp_path, [{"status": "CANCELLED"}, {"status": "NO_SHOW"}])
    assert report["summary"]["total_reservations"] == 2
    assert report["summary"]["total_amount_brl"] == "0.00"
    assert report["summary"]["average_nightly_rate_brl"] == "0.00"
    assert report["by_month"] == report["top_hotels"] == []


@pytest.mark.parametrize(
    ("checkin", "checkout", "rooms", "nights"),
    [("2024-12-30", "2025-01-02", "2", 6), ("2024-02-28", "2024-03-01", "3", 6), ("0001-01-01", "0001-01-02", "1", 1)],
)
def test_calendar_boundaries_and_multiple_rooms(tmp_path, checkin, checkout, rooms, nights):
    report = run_cli(tmp_path, [{"checkin_date": checkin, "checkout_date": checkout, "rooms": rooms}])
    assert report["summary"]["total_room_nights"] == nights
    assert report["by_month"][0]["month"] == checkin[:7]
    assert report["by_month"][0]["room_nights"] == nights


def test_zero_nights_does_not_divide_by_zero(tmp_path):
    report = run_cli(tmp_path, [{"checkout_date": "2025-01-10"}])
    assert report["summary"]["total_room_nights"] == 0
    assert report["summary"]["average_nightly_rate_brl"] == "0.00"
    assert report["summary"]["total_amount_brl"] == "100.00"


def test_amounts_are_summed_before_rounding_and_average_uses_exact_total(tmp_path):
    report = run_cli(tmp_path, [{"currency": "USD", "amount": "0.01"}] * 3)
    assert report["summary"]["total_amount_brl"] == "0.16"  # 0.0542 * 3
    assert report["summary"]["average_nightly_rate_brl"] == "0.05"
    assert report["by_month"][0]["total_brl"] == "0.16"
    assert report["top_hotels"][0]["total_brl"] == "0.16"


def test_half_up_and_average_not_from_serialized_total(tmp_path):
    report = run_cli(tmp_path, [{"amount": "0.005", "rooms": "2"}])
    assert report["summary"]["total_amount_brl"] == "0.01"
    assert report["summary"]["average_nightly_rate_brl"] == "0.00"  # 0.0025


def test_money_never_passes_through_float(tmp_path):
    report = run_cli(tmp_path, [{"amount": "9007199254740993.01"}])
    assert report["summary"]["total_amount_brl"] == "9007199254740993.01"


def test_ranking_tie_break_and_top_larger_than_number_of_hotels(tmp_path):
    report = run_cli(
        tmp_path,
        [
            {"hotel_id": "H02", "amount": "100.00"},
            {"hotel_id": "H01", "amount": "100.00"},
        ],
        top=20,
    )
    assert [h["hotel_id"] for h in report["top_hotels"]] == ["H01", "H02"]


def test_ranking_uses_exact_totals_before_rounding(tmp_path):
    report = run_cli(
        tmp_path,
        [
            {"hotel_id": "H01", "amount": "1.001"},
            {"hotel_id": "H02", "amount": "1.002"},
        ],
        top=1,
    )
    assert report["top_hotels"][0]["hotel_id"] == "H02"
    assert report["top_hotels"][0]["total_brl"] == "1.00"


def test_month_order_checkin_attribution_and_hotel_aggregation(tmp_path):
    report = run_cli(
        tmp_path,
        [
            {"checkin_date": "2025-02-01", "checkout_date": "2025-02-02", "amount": "10"},
            {"checkin_date": "2024-12-31", "checkout_date": "2025-01-02", "amount": "20"},
        ],
    )
    assert report["by_month"] == [
        {"month": "2024-12", "reservations": 1, "room_nights": 2, "total_brl": "20.00"},
        {"month": "2025-02", "reservations": 1, "room_nights": 1, "total_brl": "10.00"},
    ]
    assert report["top_hotels"] == [
        {"hotel_id": "H01", "hotel_name": "Hotel Teste", "room_nights": 3, "total_brl": "30.00"},
    ]


def test_repository_reads_past_200_rows(tmp_path):
    rows = [{"reservation_id": f"R-{i}", "amount": "1"} for i in range(201)]
    report = run_cli(tmp_path, rows)
    assert report["summary"]["total_reservations"] == 201
    assert report["summary"]["total_room_nights"] == 201
    assert report["summary"]["total_amount_brl"] == "201.00"


def build_official_report(filename, now=None):
    return ReportBuilder(
        CsvReservationRepository(PROJECT_ROOT / "data" / filename),
        CsvRateRepository(PROJECT_ROOT / "data/taxas_cambio.csv"),
        now=now,
    ).build()


def test_complete_official_validation_sample():
    report = build_official_report("exemplo-validacao.csv")
    assert report["summary"] == {
        "total_reservations": 12,
        "confirmed_reservations": 9,
        "cancelled_reservations": 2,
        "no_show_reservations": 1,
        "total_room_nights": 28,
        "total_amount_brl": "7566.00",
        "average_nightly_rate_brl": "270.21",
    }
    assert report["by_month"] == [
        {"month": "2025-01", "reservations": 8, "room_nights": 25, "total_brl": "6684.00"},
        {"month": "2025-02", "reservations": 1, "room_nights": 3, "total_brl": "882.00"},
    ]
    assert report["top_hotels"] == [
        {"hotel_id": "H01", "hotel_name": "Hotel Aurora Paulista", "room_nights": 3, "total_brl": "1200.00"},
        {"hotel_id": "H02", "hotel_name": "Hotel Mirante", "room_nights": 2, "total_brl": "1084.00"},
        {"hotel_id": "H12", "hotel_name": "Hotel Miami Beach", "room_nights": 1, "total_brl": "1000.00"},
        {"hotel_id": "H10", "hotel_name": "Hotel Madrid, Gran Vía", "room_nights": 4, "total_brl": "900.00"},
        {"hotel_id": "H09", "hotel_name": "Hotel Lisboa, Centro", "room_nights": 3, "total_brl": "882.00"},
    ]


def test_full_dataset_regression():
    report = build_official_report("reservas_hoteis.csv")
    assert report["summary"] == {
        "total_reservations": 300,
        "confirmed_reservations": 235,
        "cancelled_reservations": 31,
        "no_show_reservations": 34,
        "total_room_nights": 1347,
        "total_amount_brl": "396170.00",
        "average_nightly_rate_brl": "294.11",
    }
    assert report["by_month"] == [
        {"month": "2024-12", "reservations": 35, "room_nights": 174, "total_brl": "61335.80"},
        {"month": "2025-01", "reservations": 37, "room_nights": 235, "total_brl": "64662.89"},
        {"month": "2025-02", "reservations": 26, "room_nights": 138, "total_brl": "45991.09"},
        {"month": "2025-03", "reservations": 39, "room_nights": 215, "total_brl": "65984.99"},
        {"month": "2025-04", "reservations": 21, "room_nights": 146, "total_brl": "31335.97"},
        {"month": "2025-05", "reservations": 39, "room_nights": 196, "total_brl": "63507.98"},
        {"month": "2025-06", "reservations": 38, "room_nights": 243, "total_brl": "63351.29"},
    ]
    assert [(h["hotel_id"], h["room_nights"], h["total_brl"]) for h in report["top_hotels"]] == [
        ("H06", 160, "45165.46"),
        ("H10", 120, "45041.69"),
        ("H12", 106, "41647.69"),
        ("H07", 148, "39920.52"),
        ("H11", 102, "37455.69"),
    ]


@pytest.mark.parametrize(
    "clock",
    [
        datetime(2025, 7, 1, 13, tzinfo=timezone.utc),
        datetime(2025, 7, 1, 10),
    ],
)
def test_schema_and_fixed_timezone(clock):
    report = build_official_report("exemplo-validacao.csv", now=clock)
    assert set(report) == {"report_version", "generated_at", "summary", "by_month", "top_hotels"}
    assert report["report_version"] == "1.0"
    assert report["generated_at"] == "2025-07-01T10:00:00-03:00"
    assert datetime.fromisoformat(report["generated_at"]).utcoffset() == timedelta(hours=-3)
