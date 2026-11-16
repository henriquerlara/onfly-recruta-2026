"""Confere relatórios inteiros contra um cálculo independente com frações exatas."""

import csv
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, getcontext, localcontext
from fractions import Fraction

import pytest
from helpers import BASE, COLUMNS, run_cli

from onfly_report.repositories.csv_rate_repository import CsvRateRepository
from onfly_report.repositories.csv_reservation_repository import CsvReservationRepository
from onfly_report.services.currency_converter import convert_to_brl
from onfly_report.services.report_builder import ReportBuilder


def fraction_money(value):
    quotient, remainder = divmod(value.numerator * 100, value.denominator)
    cents = quotient + (2 * remainder >= value.denominator)
    return f"{cents // 100}.{cents % 100:02d}"


def reference_report(rows, rates, top):
    statuses = Counter(row["status"] for row in rows)
    monthly = defaultdict(lambda: [0, 0, Fraction(0)])
    hotels = {}
    total = Fraction(0)
    nights = 0
    for row in rows:
        if row["status"] != "CONFIRMED":
            continue
        stay = (date.fromisoformat(row["checkout_date"]) - date.fromisoformat(row["checkin_date"])).days
        room_nights = stay * int(row["rooms"])
        amount = Fraction(row["amount"]) * Fraction(rates[row["currency"]])
        nights += room_nights
        total += amount
        month = monthly[row["checkin_date"][:7]]
        month[0] += 1
        month[1] += room_nights
        month[2] += amount
        hotel = hotels.setdefault(row["hotel_id"], [row["hotel_name"], 0, Fraction(0)])
        hotel[1] += room_nights
        hotel[2] += amount
    return {
        "report_version": "1.0",
        "summary": {
            "total_reservations": len(rows),
            "confirmed_reservations": statuses["CONFIRMED"],
            "cancelled_reservations": statuses["CANCELLED"],
            "no_show_reservations": statuses["NO_SHOW"],
            "total_room_nights": nights,
            "total_amount_brl": fraction_money(total),
            "average_nightly_rate_brl": fraction_money(total / nights if nights else Fraction(0)),
        },
        "by_month": [
            {"month": key, "reservations": value[0], "room_nights": value[1], "total_brl": fraction_money(value[2])}
            for key, value in sorted(monthly.items())
        ],
        "top_hotels": [
            {"hotel_id": key, "hotel_name": value[0], "room_nights": value[1], "total_brl": fraction_money(value[2])}
            for key, value in sorted(hotels.items(), key=lambda item: (-item[1][2], item[0]))[:top]
        ],
    }


def write_dataset(tmp_path, rows, rates):
    input_path, rates_path = tmp_path / "input.csv", tmp_path / "rates.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with rates_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["currency", "rate_to_brl"])
        writer.writerows(rates.items())
    return CsvReservationRepository(input_path), CsvRateRepository(rates_path)


@pytest.mark.parametrize("seed", range(20))
def test_generated_complete_reports_against_exact_reference(tmp_path, seed):
    rng = random.Random(seed)
    rates = {"BRL": "1", "USD": "5.42123789", "EUR": "5.88981723"}
    count = (0, 1, 2, 7, 50, 199, 200, 201, 313, 1000)[seed % 10]
    rows = []
    for index in range(count):
        checkin = date(2023, 1, 1) + timedelta(days=rng.randrange(1100))
        hotel_id = f"H{rng.randrange(17):02d}"
        coefficient = rng.randrange(10**12)
        rows.append(
            {
                **BASE,
                "reservation_id": f"R-{index}",
                "hotel_id": hotel_id,
                "hotel_name": f"Hotel {hotel_id}, São Paulo",
                "checkin_date": checkin.isoformat(),
                "checkout_date": (checkin + timedelta(days=rng.randrange(16))).isoformat(),
                "rooms": str(rng.randrange(1, 6)),
                "status": rng.choice(["CONFIRMED", "CONFIRMED", "CANCELLED", "NO_SHOW"]),
                "currency": rng.choice(list(rates)),
                "amount": f"{coefficient // 10**7}.{coefficient % 10**7:07d}",
            }
        )
    top = (1, 5, 50)[seed % 3]
    report = ReportBuilder(*write_dataset(tmp_path, rows, rates), top_n=top).build()
    assert datetime.fromisoformat(report.pop("generated_at")).utcoffset() == timedelta(hours=-3)
    assert report == reference_report(rows, rates, top)


def test_row_order_and_irrelevant_columns_do_not_change_report(tmp_path):
    rows = [
        {"reservation_id": "R1", "amount": "0.005", "hotel_id": "H02"},
        {"reservation_id": "R2", "amount": "0.004", "hotel_id": "H01"},
        {"reservation_id": "R3", "amount": "200", "status": "NO_SHOW"},
        {"reservation_id": "R4", "amount": "300", "status": "CANCELLED"},
    ]
    first = run_cli(tmp_path, rows)
    second = run_cli(
        tmp_path,
        [
            {**row, "traveler_name": "Outra pessoa", "company_id": "Outra empresa", "booked_at": "sem efeito"}
            for row in reversed(rows)
        ],
    )
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


@pytest.mark.parametrize(
    "clock",
    [
        datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 12, 31, 17, tzinfo=timezone(timedelta(hours=-8))),
    ],
)
def test_fixed_timezone_can_change_calendar_date(tmp_path, clock):
    report = ReportBuilder(*write_dataset(tmp_path, [], {"BRL": "1"}), now=clock).build()
    assert report["generated_at"] == "2024-12-31T22:00:00-03:00"


@pytest.mark.parametrize(
    "amount",
    [
        "0.0049999999999999999999999999999",
        "90071992547409931234567890.005",
    ],
)
def test_money_with_more_than_28_digits_is_not_rounded_before_serialization(tmp_path, amount):
    rows = [{**BASE, "amount": amount}]
    rates = {"BRL": "1"}
    report = ReportBuilder(*write_dataset(tmp_path, rows, rates)).build()
    report.pop("generated_at")
    assert report == reference_report(rows, rates, 5)


def test_large_amount_and_fractional_cent_are_summed_exactly(tmp_path):
    rows = [{**BASE, "amount": "100000000000000000000000000"}, {**BASE, "amount": "0.005"}]
    rates = {"BRL": "1"}
    report = ReportBuilder(*write_dataset(tmp_path, rows, rates)).build()
    report.pop("generated_at")
    assert report == reference_report(rows, rates, 5)


@pytest.mark.parametrize("seed", range(10))
def test_wide_decimal_scales_against_exact_reference(tmp_path, seed):
    rng = random.Random(seed)
    rates = {"BRL": "1", "USD": "5.123456789123456789123456789123456789"}
    rows = []
    for index in range(80):
        hotel_id = f"H{rng.randrange(7)}"
        coefficient = rng.randrange(10**40)
        exponent = rng.randrange(-65, 10)
        rows.append(
            {
                **BASE,
                "reservation_id": f"R{index}",
                "hotel_id": hotel_id,
                "hotel_name": hotel_id,
                "amount": f"{coefficient}e{exponent}",
                "rooms": str(rng.randrange(1, 100)),
                "currency": rng.choice(list(rates)),
            }
        )
    report = ReportBuilder(*write_dataset(tmp_path, rows, rates)).build()
    report.pop("generated_at")
    assert report == reference_report(rows, rates, 5)


@pytest.mark.parametrize(
    "amount",
    [
        "0.01499999999999999999999999999999999999999999999999",
        "0.015",
        "0.01500000000000000000000000000000000000000000000001",
    ],
)
def test_average_around_half_cent_boundary(tmp_path, amount):
    rows = [{**BASE, "amount": amount, "rooms": "3"}]
    rates = {"BRL": "1"}
    report = ReportBuilder(*write_dataset(tmp_path, rows, rates)).build()
    report.pop("generated_at")
    assert report == reference_report(rows, rates, 5)


def test_caller_decimal_precision_is_preserved_and_does_not_change_report(tmp_path):
    rows = [{**BASE, "amount": "123456789.015", "rooms": "3"}]
    rates = {"BRL": "1"}
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        report = ReportBuilder(*write_dataset(tmp_path, rows, rates)).build()
        assert getcontext().prec == 6
        assert getcontext().rounding == ROUND_DOWN
    report.pop("generated_at")
    assert report == reference_report(rows, rates, 5)


def test_currency_multiplication_preserves_all_input_digits():
    amount = "123456789123456789.123456789"
    rate = "5.123456789123456789"
    converted = convert_to_brl(Decimal(amount), "USD", {"USD": Decimal(rate)})
    assert Fraction(converted) == Fraction(amount) * Fraction(rate)


@pytest.mark.parametrize("amount", ["0.0049999999999999999999999999999", "100000000000000000000000000.005"])
def test_high_precision_amounts_through_real_cli(tmp_path, amount):
    rows = [{**BASE, "amount": amount}]
    report = run_cli(tmp_path, rows)
    report.pop("generated_at")
    assert report == reference_report(rows, {"BRL": "1"}, 5)
