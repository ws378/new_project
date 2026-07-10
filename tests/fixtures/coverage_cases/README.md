# 覆盖规划 case 夹具

## 职责

`coverage_cases/` 保存可以在 clean checkout 中复现实验、smoke 和 baseline compare 的固定输入 case。

## 当前 case

- `case_demo/` - 标准覆盖规划与 `channel_topology_graph` 支撑工具共用的轻量验证输入。

## 目录边界

- 这里保存输入真值，不保存运行输出。
- `runs/` 和 `latest` 由 `tools/coverage_planning/run_case.py` 运行时生成，必须保持 ignored。
- 新增 case 时需要同步说明它服务于测试、smoke 还是 benchmark，不能把临时调参输出提交进来。
