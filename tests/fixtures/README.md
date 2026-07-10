# 测试夹具目录

## 职责

`tests/fixtures/` 保存顶层自动化测试需要的稳定输入数据。

这些数据可以包含小型地图、coverage repo、配置片段或其它固定输入，但不能包含测试运行产物。

## 当前子目录

- `coverage_repos/` - coverage repo 导入导出相关测试夹具。
- `coverage_cases/` - 覆盖规划 runner、CTG smoke 和 baseline compare 共用的固定输入 case。

## 长期约束

- 测试必须通过 `tests/fixtures/` 下的显式路径读取夹具。
- 测试不能依赖根目录 `sample/`、`output/` 或临时运行目录。
- case runner 产生的 `runs/` 与 `latest` 必须作为运行产物忽略，不能进入 fixture 真值。
- 新增夹具时应优先最小化，不把完整实验输出当作 fixture 提交。
