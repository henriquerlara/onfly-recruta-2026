"""Exercita o processo real, inclusive stderr e os códigos de saída."""

import csv
import json
import os
import subprocess
import sys

import pytest
from helpers import BASE, COLUMNS, PROJECT_ROOT

from onfly_report.cli import main


@pytest.fixture
def cli_files(tmp_path):
    reservations = tmp_path / "reservas.csv"
    rates = tmp_path / "taxas.csv"
    with reservations.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerow(BASE)
    rates.write_text("currency,rate_to_brl\nBRL,1\n", encoding="utf-8")
    return reservations, rates, tmp_path / "nested/report.json"


def invoke(files, *extra, output=True, cwd=PROJECT_ROOT):
    reservations, rates, destination = files
    args = ["--input", str(reservations), "--rates", str(rates)]
    if output:
        args += ["--output", str(destination)]
    return subprocess.run(
        [sys.executable, "-m", "onfly_report", *args, *extra],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )


def rewrite_row(files, **changes):
    with files[0].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerow({**BASE, **changes})


def assert_input_error(process, files, message):
    assert process.returncode == 2, process.stderr
    assert message in process.stderr
    assert "Traceback" not in process.stderr
    assert process.stdout == ""
    assert not files[2].exists()


def test_creates_output_parent_and_prints_summary(cli_files):
    process = invoke(cli_files)
    assert process.returncode == 0, process.stderr
    assert process.stderr == ""
    assert process.stdout == "Reservas: 1 | Confirmadas: 1 | Noites: 1 | Total BRL: 100.00\n"
    assert json.loads(cli_files[2].read_text())["summary"]["total_amount_brl"] == "100.00"


def test_default_output_path(cli_files, tmp_path):
    process = invoke(cli_files, output=False, cwd=tmp_path)
    assert process.returncode == 0, process.stderr
    assert (tmp_path / "output/report.json").is_file()


@pytest.mark.parametrize("top", ["0", "-1", "abc", "1.5"])
def test_invalid_top(cli_files, top):
    assert_input_error(invoke(cli_files, "--top", top), cli_files, "--top")


def test_required_arguments():
    process = subprocess.run(
        [sys.executable, "-m", "onfly_report"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 2
    assert "--input" in process.stderr and "--rates" in process.stderr


@pytest.mark.parametrize("index", [0, 1])
def test_missing_file(cli_files, index):
    cli_files[index].unlink()
    assert_input_error(invoke(cli_files), cli_files, "não encontrad")


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("checkin_date", "2025-02-30", "linha 2"),
        ("checkin_date", "20250110", "YYYY-MM-DD"),
        ("checkout_date", "2025-01-09", "checkout_date"),
        ("rooms", "0", "rooms"),
        ("rooms", "-1", "rooms"),
        ("rooms", "1.5", "linha 2"),
        ("status", "PENDING", "status"),
        ("amount", "texto", "linha 2"),
        ("amount", "-0.01", "amount"),
        ("amount", "NaN", "amount"),
        ("amount", "sNaN", "amount"),
        ("amount", "Infinity", "amount"),
        ("currency", "JPY", "moeda sem taxa"),
        ("hotel_id", "", "hotel_id"),
        ("hotel_name", " ", "hotel_name"),
        ("reservation_id", "", "reservation_id"),
    ],
)
def test_invalid_reservation(cli_files, column, value, message):
    rewrite_row(cli_files, **{column: value})
    assert_input_error(invoke(cli_files), cli_files, message)


def test_non_billable_rows_are_parsed_before_filtering(cli_files):
    rewrite_row(cli_files, status="CANCELLED", rooms="invalido")
    assert_input_error(invoke(cli_files), cli_files, "linha 2")


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "sNaN", "Infinity", "abc"])
def test_invalid_rate(cli_files, rate):
    cli_files[1].write_text(f"currency,rate_to_brl\nBRL,{rate}\n", encoding="utf-8")
    assert_input_error(invoke(cli_files), cli_files, "taxa")


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("currency,rate_to_brl\n", "vazia"),
        ("currency,rate_to_brl\nBRL,1\nBRL,2\n", "duplicada"),
        ("currency,rate_to_brl\n,1\n", "incompleta"),
        ("currency,rate_to_brl\nBRL,1,2\n", "campos"),
        ("currency,rate_to_brl\nBRL\n", "campos"),
    ],
)
def test_malformed_rates(cli_files, contents, message):
    cli_files[1].write_text(contents, encoding="utf-8")
    assert_input_error(invoke(cli_files), cli_files, message)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("header", "colunas obrigatórias"),
        ("duplicate", "duplicad"),
        ("encoding", "falha ao ler"),
        ("quote", "falha ao ler"),
    ],
)
def test_invalid_csv(cli_files, index, problem, message):
    path = cli_files[index]
    lines = path.read_text().splitlines()
    if problem == "header":
        path.write_text("coluna_errada\nvalor\n", encoding="utf-8")
    elif problem == "duplicate":
        path.write_text(lines[0] + "," + lines[0].split(",")[0] + "\n", encoding="utf-8")
    elif problem == "encoding":
        path.write_bytes(b"\xff\xfe\xff")
    else:
        path.write_text(lines[0] + '\n"aspas sem fechamento\n', encoding="utf-8")
    assert_input_error(invoke(cli_files), cli_files, message)


@pytest.mark.parametrize("suffix", [",extra", "missing"])
def test_inconsistent_reservation_width(cli_files, suffix):
    lines = cli_files[0].read_text().splitlines()
    row = lines[1] + suffix if suffix != "missing" else lines[1].rsplit(",", 1)[0]
    cli_files[0].write_text(lines[0] + "\n" + row + "\n", encoding="utf-8")
    assert_input_error(invoke(cli_files), cli_files, "campos")


def test_bom_quoted_commas_accents_and_multiline_field(cli_files):
    rewrite_row(cli_files, hotel_name="Hotel São Paulo, Centro\nAla Norte")
    for path in cli_files[:2]:
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    process = invoke(cli_files)
    assert process.returncode == 0, process.stderr
    report = json.loads(cli_files[2].read_text(encoding="utf-8"))
    assert report["top_hotels"][0]["hotel_name"] == "Hotel São Paulo, Centro\nAla Norte"


def test_unwritable_output_returns_one(cli_files):
    cli_files[2].parent.write_text("arquivo impede criar diretório", encoding="utf-8")
    process = invoke(cli_files)
    assert process.returncode == 1
    assert "falha ao escrever" in process.stderr
    assert process.stdout == ""


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("link", ["same_path", "symlink", "hardlink"])
def test_output_cannot_overwrite_inputs(cli_files, index, link):
    original = cli_files[index].read_bytes()
    if link == "same_path":
        destination = cli_files[index]
    else:
        destination = cli_files[0].parent / "alias.csv"
        if link == "symlink":
            destination.symlink_to(cli_files[index])
        else:
            destination.hardlink_to(cli_files[index])
    process = invoke(cli_files, "--output", str(destination))
    assert_input_error(process, cli_files, "diferente dos arquivos de entrada")
    assert cli_files[index].read_bytes() == original


def test_unexpected_error_returns_one(cli_files, monkeypatch, caplog, capsys):
    def fail(_self):
        raise RuntimeError("falha inesperada de teste")

    monkeypatch.setattr("onfly_report.cli.ReportBuilder.build", fail)
    assert main(["--input", str(cli_files[0]), "--rates", str(cli_files[1])]) == 1
    assert "erro inesperado" in caplog.text
    assert capsys.readouterr().out == ""
    assert not cli_files[2].exists()


def test_unknown_argument_is_rejected(cli_files):
    assert_input_error(invoke(cli_files, "--argumento-inexistente"), cli_files, "unrecognized arguments")


def test_help_succeeds_without_writing_report(cli_files):
    process = invoke(cli_files, "--help")
    assert process.returncode == 0
    assert process.stderr == ""
    for argument in ("--input", "--rates", "--output", "--top"):
        assert argument in process.stdout
    assert not cli_files[2].exists()


@pytest.mark.parametrize("index", [0, 1])
def test_directory_as_input_is_rejected(cli_files, index):
    cli_files[index].unlink()
    cli_files[index].mkdir()
    assert_input_error(invoke(cli_files), cli_files, "falha ao ler")


def test_directory_as_output_returns_one(cli_files):
    cli_files[2].mkdir(parents=True)
    process = invoke(cli_files)
    assert process.returncode == 1
    assert "falha ao escrever" in process.stderr
    assert process.stdout == ""


@pytest.mark.parametrize("problem", ["reservation", "rates", "argument"])
def test_invalid_input_keeps_existing_report_intact(cli_files, problem):
    cli_files[2].parent.mkdir()
    original = b'{"relatorio_anterior": true}\n'
    cli_files[2].write_bytes(original)
    extra = []
    if problem == "reservation":
        rewrite_row(cli_files, amount="invalido")
    elif problem == "rates":
        cli_files[1].write_bytes(b"\xff")
    else:
        extra = ["--top", "0"]
    process = invoke(cli_files, *extra)
    assert process.returncode == 2
    assert process.stdout == ""
    assert cli_files[2].read_bytes() == original


def test_valid_run_replaces_existing_report(cli_files):
    cli_files[2].parent.mkdir()
    cli_files[2].write_text("conteúdo antigo", encoding="utf-8")
    process = invoke(cli_files)
    assert process.returncode == 0, process.stderr
    assert json.loads(cli_files[2].read_text())["summary"]["total_reservations"] == 1


@pytest.mark.parametrize("tz", ["UTC", "Pacific/Auckland", "America/Los_Angeles"])
def test_process_timezone_does_not_change_report_offset(cli_files, monkeypatch, tz):
    monkeypatch.setenv("TZ", tz)
    process = invoke(cli_files)
    assert process.returncode == 0, process.stderr
    report = json.loads(cli_files[2].read_text())
    assert report["generated_at"].endswith("-03:00")


def test_error_reports_physical_csv_line_after_multiline_record(cli_files):
    with cli_files[0].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerow({**BASE, "hotel_name": "Hotel\nAla Norte"})
        writer.writerow({**BASE, "amount": "invalido"})
    assert_input_error(invoke(cli_files), cli_files, "linha 4")


@pytest.mark.parametrize("index", [0, 1])
def test_input_symlink_loop_is_an_input_error(cli_files, index):
    cli_files[index].unlink()
    cli_files[index].symlink_to(cli_files[index].name)
    assert_input_error(invoke(cli_files), cli_files, "falha ao ler")


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="requer permissões POSIX sem privilégios de root")
@pytest.mark.parametrize("index", [0, 1])
def test_read_permission_denied_is_an_input_error(cli_files, index):
    cli_files[index].chmod(0)
    try:
        assert_input_error(invoke(cli_files), cli_files, "falha ao ler")
    finally:
        cli_files[index].chmod(0o600)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="requer permissões POSIX sem privilégios de root")
def test_write_permission_denied_returns_one(cli_files):
    cli_files[2].parent.mkdir(mode=0o500)
    try:
        process = invoke(cli_files)
        assert process.returncode == 1
        assert "falha ao escrever" in process.stderr
        assert process.stdout == ""
    finally:
        cli_files[2].parent.chmod(0o700)
