#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_events.py 事件类型过滤的回归测试。

用途：调整 INCLUDE / EXCLUDE 关键词后，先跑这个脚本确认判定没有回退。
  python3 scripts/test_screen.py

覆盖三类用例：
  A. 应保留——真实的供给事件（6 条，取自 2026-09-24 人工核验结果）
  B. 应剔除——估值可研 / 融资 / 设备订单 / 价格行情（11 条，同批被剔除的候选）
  C. 强信号覆盖——停产减产类与政策类事件，即便稿子里出现「成本」「价格」等
     软性排除词，也必须保留（这两条是回归测试实际抓出来的 bug）
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fe", os.path.join(HERE, "fetch_events.py"))
fe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fe)

KEEP = [
    ("Nth Cycle signs $1bn recycled minerals supply deal with Glencore",
     "Nth Cycle has entered into a $1bn offtake agreement with Glencore to supply lithium and other critical minerals recovered from recycled batteries, reported Reuters."),
    ("Global Lithium signs $237m SID with Titan Australia Mining",
     "Global Lithium Resources and Titan Australia Mining have signed a binding scheme implementation deed (SID) for a proposed acquisition valued at approximately A$333m ($237m)."),
    ("BHP halts operations at Escondida following fatal accident",
     "Chile's Sernageomin confirmed the fatal accident, and deployed a regional team to investigate."),
    ("Bridge Green, Hartree sign eight-year lithium agreement",
     "Bridge Green Upcycle and Hartree Partners have signed an eight-year commercial agreement for the purchase and marketing of lithium carbonate produced from recycled batteries, with a value between $500m and $1bn."),
    ("Vale buys Ligga iron ore stake for $190M",
     "Vale confirmed it is acquiring a 30% interest in Ligga to increase iron ore production."),
    ("Capstone sells Mexican mine to Luca for up to $385M",
     "Capstone Copper is selling its Cozamin copper-silver-zinc-lead mine in Mexico to Luca Mining for up to $385 million (C$540 million)."),
]

DROP = [
    ("Higher Santa Cruz costs weigh on Ivanhoe Electric",
     "A new prefeasibility study (PFS) shows the Santa Cruz copper project has become more expensive to build while its economics improved modestly."),
    ("BHP, Amazon establish pilot for lower emissions copper market",
     "BHP and Amazon have established an industry-first copper pilot to buy and sell credits for lower greenhouse gas emissions associated with copper concentrate and cathodes produced at Escondida."),
    ("Savannah raises $30M to advance Barroso lithium project",
     "Fresh funding will push Barroso through engineering, permitting and early works."),
    ("Global Lithium soars 50% on A$333M Titan takeover",
     "Global Lithium Resources shares jumped on the Titan takeover."),
    ("Meridian's Cabacal value doubles on higher prices",
     "Meridian Mining has more than doubled the estimated value of its Cabacal gold-copper project in Brazil in a new feasibility study."),
    ("Selkirk Copper's Minto posts $494M value, nearly triple its build costs",
     "The Minto mine study shows a value nearly triple its build costs."),
    ("Ok Tedi introduces world's first ArcSAR Neo radar systems from IDS GeoRadar",
     "Ok Tedi has introduced radar systems for slope monitoring."),
    ("Metso banks largest LCS analyser order to date",
     "Metso has received its largest order for LCS analysers."),
    ("Wabtec wins plus-$700 million services order for Simandou",
     "Wabtec has won a services order for the Simandou iron ore project."),
    ("Copper price closes in on new record as Shanghai, London warehouses empty out",
     "Copper prices approached a record as inventories fell."),
    ("Copper prices bounce as US runs out of warehouse space",
     "Copper prices bounced as US warehouse space ran out."),
]

OVERRIDE = [
    ("Codelco cuts 2026 output guidance as costs rise at El Teniente", "停产/减产 + 成本词"),
    ("Chile raises copper royalty after mining law reform", "政策 + 融资词误伤"),
    ("Indonesia nickel export ban tightens amid falling prices", "政策 + 价格词"),
]


def main():
    fail = 0
    print("== A. 应保留（6）==")
    for t, d in KEEP:
        ok, tag, why = fe.screen(t + " " + d)
        m = fe.classify(t + " " + d)
        print(f"  {'OK  ' if ok else 'FAIL'} [{tag}] {m} | {t[:52]}")
        if not ok:
            fail += 1
            print("         为什么:", why)

    print("== B. 应剔除（11）==")
    for t, d in DROP:
        ok, tag, why = fe.screen(t + " " + d)
        print(f"  {'OK  ' if not ok else 'FAIL'} ({why}) {t[:52]}")
        if ok:
            fail += 1

    print("== C. 强信号覆盖（3，必须保留）==")
    for t, note in OVERRIDE:
        ok, tag, why = fe.screen(t)
        print(f"  {'OK  ' if ok else 'FAIL'} [{tag}] {note} | {t[:52]}")
        if not ok:
            fail += 1
            print("         为什么:", why)

    print()
    print(f"失败项：{fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
