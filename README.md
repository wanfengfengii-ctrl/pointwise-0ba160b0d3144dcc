# 港区能耗日仓

港区能耗资料组按东仓和西仓接收交班读数。版管员依据标定单冻结具名换算版。计量员凭首收号核对原件，区域值班员预检、首发并冲销误件，月报员按经营日冻结和领取日报。

需要 Python 3.11，仅使用标准库。以下命令从项目根目录运行。

```sh
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B -m samples.demo
python3 -B -m samples.init_sample ./sample-work
```

统一回归入口 `check_project.py` 由运行平台提供。`unittest discover` 可直接运行完整测试。`samples.demo` 在临时目录创建版库、东仓和西仓，使用 `samples/day.json` 执行实际业务，核对合计、缺测、出处、冲销和重开领取。独立初始化命令在指定目录创建库结构，重复执行保留已经登记及办理的业务数据。目录与日报组件各自提交，日报归档表位于版库文件内。两仓各自提交并只访问本地文件。

## Python 业务入口

以下模块可从项目根目录直接导入。`VersionRepository` 和 `ReportRepository` 接收数据库路径，打开后调用 `initialize()` 初始化表。仓库使用 `initialize_warehouse(path, region)` 初始化并打开，或用 `open_warehouse(path, region)` 打开已初始化的区域文件。连接使用完毕后调用 `close()`。区域标识为 `east` 和 `west`。

| 模块 | 调用及结果 |
| --- | --- |
| `energy.versions.publish` | `publish_version(versions, VersionDraft(number, rules))` 返回冻结版。每条 `DeviceRule(device, input_unit, numerator, denominator, source)` 记录所要求的原单位和标定出处。 |
| `energy.versions.lookup` | `lookup_version(versions, number)` 按确切版号查冻结版。`energy.versions.messages.handle_version_lookup` 将查询结果包装为可信应答。 |
| `energy.intake.register` | `receive_batch(warehouse, region, day, batch_number, rows)` 返回首收凭据。每条 `SourceRow(row_number, device, input_unit, reading, source)` 保留交班原序。 |
| `energy.intake.read_batch` | `read_batch(warehouse, receipt_number)` 凭本仓实收号读取原件。 |
| `energy.conversion.prepare` | `prepare_usage(warehouse, receipt_number, version_number, lookup)` 固定预检。`lookup` 接收 `VersionLookupRequest` 并返回 `VersionLookupReply`。 |
| `energy.facts.posting` | `post_usage(warehouse, region, request_number, preview_number)` 返回首执。首执含事实号、入账序及固定预检。 |
| `energy.facts.reversal` | `reverse_usage(warehouse, region, request_number, fact_number)` 返回冲销首执。 |
| `energy.facts.current` | `read_current(warehouse, region, day)` 返回有效事实元组。 |
| `energy.reports.build` | `freeze_report(reports, warehouse, report_number, region, day)` 冻结有效现账截面。 |
| `energy.reports.read` | `get_report(reports, report_number)` 从归档领取原快照。 |

经营日须为有效公历日期，格式为 `YYYY-MM-DD`。规则系数为正有理数，规则原单位须与原行严格相同。原读为整数或 `None`。按原读乘系数得到精确的 `Fraction`，输出单位为 `kWh`。空读仍须校验设备和单位，单列为缺测。零读照列；空日返回零合计。报告按入账序组织事实，事实内沿用交班原行顺序。

同版号同规范化规则、同批号同一有序原件，以及同一实收同一版均可复领。首发、冲销和冻结日报的原号同参返回原结果。首发请求号和冲销请求号各属本仓、各有自己的命名空间。每个预检至多成功首发一次，每笔事实至多冲销一次。冲销保留旧事实和首执。日报号在归档库内全局唯一，绑定区域及经营日。

公开业务拒绝使用 `energy.storage.DomainError`，其 `code` 可区分 `conflict`、`wrong_region`、`invalid_day`、`invalid_rule`、`invalid_row`、`duplicate_row`、`unknown_version`、`unknown_batch`、`missing_rule`、`unit_mismatch`、`unknown_preview`、`already_posted`、`unknown_fact`、`already_reversed` 和 `unknown_report` 等情况。SQLite 存储故障会向调用方传播。首发、冲销及归档在各自事务提交后才返回结果。临时故障后可用原号重办或重领。
