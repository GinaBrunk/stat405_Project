# Aircraft Delay Propagation (2015–2024) Slides Reference

这份文档是给你做 presentation 的“配图 + 讲稿骨架”。  
你可以按这个结构直接做 6–7 页 slides。

## 0. 项目一句话（开场可直接读）
我们用 2015–2024 年美国 BTS 航班数据，按同一架飞机（`TAIL_NUM`）连接相邻航班，发现前序航班晚到与下一段“严重晚点（>15 分钟）”风险显著相关，而且这种传播在短过站（turnaround）场景下更强。

## 1. 我们做了什么（方法页）
- 数据范围：2015–2024（10 年，120 个月度文件）。
- 配对规则：同一 `TAIL_NUM`，且 `prev_DEST == current_ORIGIN`，并限制 `scheduled_turnaround_minutes` 在 `[20, 600]`。
- 并行流程：
  - monthly cleaning：120 jobs
  - tail partitions：100 buckets
  - pair building：100 jobs
  - yearly modeling：10 jobs（主模型）
  - 2024 heterogeneity：1 job（航司 + 过站交互）
- 最终可用建模 pairs：`53,268,469`。

建议配图：
- [fig04_pipeline_parallel_flow.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig04_pipeline_parallel_flow.png)
- [fig08_pairs_by_year_2015_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig08_pairs_by_year_2015_2024.png)

## 2. 主问题与主结果（logistic）
模型核心解释变量是 `prev_ARR_DELAY`，因变量是 `current_dep_delayed_15`。  
主要口径：每增加 10 分钟前序晚到，下一段严重晚点的 odds 增加多少（OR per 10 min）。

关键结果（2015–2024）：
- 年均 OR(10min) ≈ `1.451`
- 2015: OR(10min) ≈ `1.525`
- 2024: OR(10min) ≈ `1.403`

一句话结论（可直接放页底）：
`Previous arrival delay is consistently associated with higher risk of next-leg departure delay > 15 min.`

建议配图：
- [fig06_yearly_or10_trend_2015_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig06_yearly_or10_trend_2015_2024.png)
- [fig01_delay_rate_by_prev_delay_bin_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig01_delay_rate_by_prev_delay_bin_2024.png)

## 3. 辅助可解释结果（linear，翻译成分钟）
线性模型用于“分钟解释”：
- 年均线性系数 ≈ `0.5107`
- 对应解释：前序晚到 10 分钟，下一段平均多晚出发约 `5.11` 分钟。
- 2020 年较低（约 4.22 分钟），其余年份多在 5 分钟左右。

建议配图：
- [fig07_yearly_linear_minutes_trend_2015_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig07_yearly_linear_minutes_trend_2015_2024.png)
- [fig05_prev_arr_delay_vs_current_dep_delay_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig05_prev_arr_delay_vs_current_dep_delay_2024.png)

## 4. 异质性结果 A：按航司（2024）
2024 年航司间存在差异（OR per 10 min）：
- 较高：`HA 1.905`（样本较小，n=64,336）、`WN 1.571`、`9E 1.501`
- 较低：`B6 1.342`、`UA 1.320`、`AA 1.298`

讲述建议：
- 先强调“方向一致（均 >1）”
- 再强调“强度不同（运营调度/网络结构可能相关）”
- 对小样本航司加一句谨慎解释

建议配图：
- [fig02_carryover_by_airline_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig02_carryover_by_airline_2024.png)
- [fig09_airline_top_bottom_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig09_airline_top_bottom_2024.png)

## 5. 异质性结果 B：按过站时间（2024）
turnaround 越短，传播越强（OR per 10 min）：
- `20–44` 分钟：`2.859`
- `45–89` 分钟：`2.132`
- `90–179` 分钟：`1.315`
- `180–600` 分钟：`1.059`

一句话 takeaway（建议加粗）：
`Short turnaround windows are where delay propagation is strongest.`

建议配图：
- [fig03_carryover_by_turnaround_bin_2024.png](/Users/liyuang/Desktop/stat605/results/report_figures/fig03_carryover_by_turnaround_bin_2024.png)

## 6. Limitations + Takeaway（收尾页）
Limitations:
- 这是 observational association，不是严格因果识别。
- 尚未显式控制天气、ATC 流控、机械故障等外生冲击。
- 航司差异可能部分来自网络结构与时刻表策略。

Final takeaway:
- 同一飞机的前序晚到会系统性传递到下一段；
- 这种传递在短过站场景最明显；
- 对运营端有直接含义：增加关键波次 buffer、优化 turn 管理可能降低传播。

---

## 可直接粘贴到 slides 的页标题建议（6页版）
1. Question: Does Delay Carry Over on the Same Aircraft?
2. Data & Parallel Pipeline (2015–2024, 53.3M pairs)
3. Main Logistic Result: Risk Increases with Previous Arrival Delay
4. Heterogeneity by Airline (2024)
5. Heterogeneity by Turnaround Time (2024)
6. Limitations, Operational Implications, and Takeaways

## 结果数据文件（备查）
- 年度汇总表：[yearly_main_summary_2015_2024.csv](/Users/liyuang/Desktop/stat605/results/chtc_pull/yearly_main_summary_2015_2024.csv)
- 2024 异质性表：[airline_carryover_summary.csv](/Users/liyuang/Desktop/stat605/results/chtc_pull/results_2024_hetero/2024/airline_carryover_summary.csv)
- 2024 过站表：[turnaround_carryover_summary.csv](/Users/liyuang/Desktop/stat605/results/chtc_pull/results_2024_hetero/2024/turnaround_carryover_summary.csv)
