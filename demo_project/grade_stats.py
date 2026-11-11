"""
成绩统计模块（课堂演示项目）

功能：读取成绩 CSV，计算平均分、及格率、前 N 名和等级。
说明：这个模块里藏着几个 bug，还有一个没写完的函数。
     你的任务是在 AI / Agent 的帮助下把它们找出来、修好，并让 tests 全部通过。
"""
import csv

PASS_LINE = 60  # 及格线


def load_scores(path):
    """
    读取 CSV 文件（表头：name,score），返回 [{"name": 姓名, "score": 分数}, ...]。
    分数无法解析的行（如"缺考"）要跳过，并打印一条提示，不能让程序崩溃。
    """
    records = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                score=float(row["score"])
            except ValueError:
                print(f"跳过无法解析的分数：{row['score']}")
                continue
            records.append({"name": row["name"], "score": float(row["score"])})
    return records


def average(records):
    """平均分，保留 2 位小数；没有任何记录时返回 0.0。"""
    if not records:
        return 0.0
    total = sum(r["score"] for r in records)
    return round(total / len(records), 2)


def pass_rate(records):
    """及格率（0~1 之间的小数，保留 4 位）。分数 >= 60 算及格；没有记录时返回 0.0。"""
    if not records:
        return 0.0
    passed = [r for r in records if r["score"] >= PASS_LINE]
    return round(len(passed) / len(records), 4)


def top_n(records, n=3):
    """返回分数最高的 n 条记录，按分数从高到低排列。"""
    return sorted(records,reverse=True,key=lambda r: r["score"])[:n]


def grade_level(score):
    """
    【本周要完成的小功能】把分数换算成等级：
        90 <= 分数 <= 100 → "A"      80 <= 分数 < 90 → "B"      70 <= 分数 < 80 → "C"
        60 <= 分数 < 70   → "D"      0 <= 分数 < 60  → "F"
    分数不在 0~100 范围内时，抛出 ValueError。
    """
    if score<0 or score>100:
        raise ValueError("分数必须在 0 到 100 之间")
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"
    
    raise NotImplementedError("grade_level 还没有实现")
