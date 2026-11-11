"""
grade_stats 的测试。运行：python -m pytest -q
测试就是"验收标准"写成的代码：全部通过，才算功能真正完成。
"""
import pytest

from grade_stats import average, grade_level, load_scores, pass_rate, top_n

SAMPLE = [
    {"name": "甲", "score": 90},
    {"name": "乙", "score": 60},
    {"name": "丙", "score": 45},
    {"name": "丁", "score": 75},
]


def test_average():
    assert average(SAMPLE) == 67.5


def test_average_empty():
    assert average([]) == 0.0


def test_pass_rate_includes_60():
    # 60 分是及格的：甲、乙、丁三人及格
    assert pass_rate(SAMPLE) == 0.75


def test_pass_rate_empty():
    assert pass_rate([]) == 0.0


def test_top_n_descending():
    names = [r["name"] for r in top_n(SAMPLE, 2)]
    assert names == ["甲", "丁"]


def test_load_scores_skips_bad_rows(tmp_path):
    csv_file = tmp_path / "s.csv"
    csv_file.write_text("name,score\n张三,88\n李四,缺考\n王五,61.5\n", encoding="utf-8")
    records = load_scores(csv_file)
    assert [r["name"] for r in records] == ["张三", "王五"]
    assert records[1]["score"] == 61.5


@pytest.mark.parametrize("score, level", [
    (100, "A"), (90, "A"), (89.5, "B"), (80, "B"), (79, "C"),
    (70, "C"), (69.9, "D"), (60, "D"), (59.9, "F"), (0, "F"),
])
def test_grade_level(score, level):
    assert grade_level(score) == level


@pytest.mark.parametrize("bad", [-1, 100.5, 120])
def test_grade_level_out_of_range(bad):
    with pytest.raises(ValueError):
        grade_level(bad)
