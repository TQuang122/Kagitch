"""Tests for style module."""
from __future__ import annotations

import re

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kaggle_switch import style


def test_styled():
    result = style.styled("hello", "bold red")
    assert result == "[bold red]hello[/]"


def test_panel_body():
    panel = style.panel_body("Title", "Content", "green", subtitle="sub")
    assert isinstance(panel, Panel)
    assert panel.title == "Title"
    assert panel.subtitle == "sub"
    assert panel.border_style == "green"


def test_panel_body_no_subtitle():
    panel = style.panel_body("Title", "Content", "blue")
    assert isinstance(panel, Panel)
    assert panel.subtitle is None


def test_err():
    result = style.err("something broke")
    assert "something broke" in result


def test_err_with_title():
    result = style.err("something broke", title="Custom")
    assert "something broke" in result


def test_ok():
    result = style.ok("all good")
    assert "all good" in result


def test_warn():
    result = style.warn("caution")
    assert "caution" in result


def test_info():
    result = style.info("for your info")
    assert "for your info" in result


def test_rule(capsys):
    style.rule()
    captured = capsys.readouterr()
    assert captured.out != ""


def test_bordered_table():
    headers = ["#", "Name"]
    rows = [["1", "Alice"], ["2", "Bob"]]
    table = style.bordered_table(headers, rows)
    assert isinstance(table, Table)
    assert table.columns[0].header == "#"
    assert table.columns[1].header == "Name"


def test_bordered_table_with_active():
    headers = ["#", "Name"]
    rows = [["1", "Alice"], ["2", "Bob"], ["3", "Charlie"]]
    table = style.bordered_table(headers, rows, active_index=1)
    assert isinstance(table, Table)


def test_bordered_table_with_column_options():
    headers = ["#", "Name", "Score"]
    rows = [["1", "Alice", "100"]]
    table = style.bordered_table(headers, rows, column_options={0: {"justify": "right", "width": 3}})
    assert isinstance(table, Table)


def test_card():
    panel = style.card(["Line 1", "Line 2"], title="Card Title")
    assert isinstance(panel, Panel)
    assert panel.title == "Card Title"
