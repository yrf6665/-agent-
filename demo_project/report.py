"""
成绩报告脚本：python report.py students.csv
（第一次运行会报错——这正是"AI 辅助排错"练习的素材）
"""
import sys

from grade_stats import average, load_scores, pass_rate, top_n


def main(path):
    records = load_scores(path)
    print(f"共 {len(records)} 人")
    print(f"平均分：{average(records)}")
    print(f"及格率：{pass_rate(records):.1%}")
    print("前三名：", "、".join(f"{r['name']}({r['score']:g})" for r in top_n(records)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "students.csv")
