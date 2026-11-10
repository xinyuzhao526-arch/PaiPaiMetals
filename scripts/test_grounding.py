#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用落地检查的回归测试：用 2026-11-10 已人工核过的 11 条草稿当测试集。

每条给出「草稿原文」与「人工结论」：True = 与原文一致，False = 与原文冲突。
需要联网抓原文；抓不到时该条记 SKIP，不影响其余用例。
"""
import sys
from ground_check import fetch_article, check

CASES = [
    ('codelco-overstate', True,
     'Codelco 高报铜产量 4.21 万吨，Andina 尾矿泄漏停产',
     'Codelco 披露铜产量高报合计 4.21 万吨（2024 年 2.4 万吨、上一年净 1.81 万吨）；同日 Andina 选厂因尾矿沟堵塞外泄停产。',
     'https://www.northernminer.com/news/codelco-faces-production-scandal-tailings-probe/1003897486/'),
    ('andina-halt', True,
     'Codelco 因尾矿泄漏关停 Andina 选厂',
     'Andina 选厂与尾矿输送在尾矿沟检出堵塞后停止运行，监管机构已介入调查。',
     'https://www.mining.com/codelco-halts-andina-mine-as-tailings-spill-threaten-river/'),
    ('sibanye-pgm', True,
     'Sibanye cuts US output forecast after five-week strike',
     'A prolonged labour dispute disrupted platinum group metals output as the miner weighs its next move at a Finnish lithium project.',
     'https://www.mining.com/sibanye-cuts-us-output-forecast-after-five-week-strike/'),
    ('andes-norte', True,
     'El Teniente 的 Andes Norte 扩建因地震风险停工',
     'Codelco 8 月起暂停 El Teniente 的 Andes Norte 扩建段；2,460 名相关人员中 1,817 人（约 74%）已转岗。',
     'https://www.mining.com/codelco-relocates-74-of-workers-as-andes-norte-remains-halted/'),
    ('pls-record', True,
     'Pilgangoora 9 月季度精矿产量创纪录',
     'PLS 的 Pilgangoora 在 9 月季度产锂辉石精矿 267,600 吨，环比增 25%，主因 Ngungaju 选厂复产。',
     'https://www.australianmining.com.au/pls-delivers-record-pilgangoora-lithium-production/'),
    ('highland-valley', True,
     '泰克 Highland Valley 铜矿因罢工降负荷运行',
     '加拿大最大铜矿 Highland Valley 在工人周六罢工后以降负荷状态运行。',
     'https://www.northernminer.com/news/strike-curbs-output-at-canadas-largest-copper-mine/1003896047/'),
    ('escondida-avert', True,
     '必和必拓与 Escondida 监工工会达成初步协议，避免罢工',
     '必和必拓与 Escondida 监工工会达成初步协议，避免全球最大铜矿发生罢工。',
     'https://www.northernminer.com/news/bhp-averts-strike-at-worlds-biggest-copper-mine-2/1003895736/'),
    ('el-teniente', True,
     'El Teniente 南坑滑坡致 2 死，部分停产',
     'El Teniente 南坑露天区发生滑坡，承包方 3 名作业人员中 2 人死亡、1 人获救；公司归因强降雨，已部分暂停作业。',
     'https://www.mining-technology.com/news/codelco-partially-halts-el-teniente-mine/'),
    ('centinela-strike', True,
     'Antofagasta 旗下 Centinela 罢工，运营受限',
     'Centinela 700 余名工人罢工，占直接用工约 22%，此前与劳工局的调解未果。',
     'https://www.mining.com/antofagastas-centinela-strike-adds-copper-supply-risk/'),
    ('sigma-court', True,
     '巴西法院暂停 Sigma 锂矿环境许可，矿区全面停产',
     '巴西联邦法院 9 月 4 日应社区诉讼暂停 Grota do Cirilo 的环境许可与采矿，Sigma 已停止采矿与加工。',
     'https://www.northernminer.com/news/brazil-court-order-idles-sigma-lithium-mine/1003895373/'),
    # 反例：原文只写死亡事故与调查，没有停产
    ('radomiro-claim', False,
     '智利国家铜业 Radomiro Tomic 事故致一人死亡',
     'Codelco 已暂停 Radomiro Tomic 铜矿破碎与物料处理区域的作业。',
     'https://www.mining.com/worker-dies-in-accident-at-codelcos-radomiro-tomic/'),
]


def main():
    bad = 0
    for name, expect, title, desc, url in CASES:
        art = fetch_article(url)
        got, missing, _ = check(title, desc, art)
        status = 'SKIP' if got is None else ('PASS' if got == expect else 'FAIL')
        if status == 'FAIL':
            bad += 1
        print('%-4s %-18s expect=%-5s got=%-5s %s' % (status, name, expect, got, '; '.join(missing)[:90]))
    print('\n失败 %d 条' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
