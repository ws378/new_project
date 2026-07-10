# 仓库级工具说明

本目录承载仓库级共享工具，不承载正式算法实现、GUI 产品逻辑或测试集真值资产。

当前工具域：

- `coverage_planning/`
  - 标准覆盖规划 case 的运行与查看工具
  - 入口文档：`coverage_planning/README.md`
- `audit_large_assets.py`
  - 仓库级大文件与重复资产审计脚本
  - 用于盘点 fixture、example、dataset、baseline 的体量和重复副本

边界约束：

- `tools/` 放调用、检查、查看、批处理类工具
- 正式算法实现应留在 `algorithms/`
- 地图编辑器产品逻辑应留在 `maptools/`
- case 组织、模板展开和报告治理应留在 `coverage_dataset/`

长期约束：

- 新工具若只服务某个单独算法工程，优先评估是否应放回该算法工程的 `support/` 或同级工具目录
- 只有确实跨子工程复用、且属于仓库级支持能力时，才放到根层 `tools/`
