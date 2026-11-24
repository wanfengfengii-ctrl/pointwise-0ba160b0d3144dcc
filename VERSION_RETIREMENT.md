# 换算版退役办理

港区版管员要停用一份换算版。区域班批可以早已实收并制成预检，是否已在现账引用该版取决于正式首发及冲销。

## 登记和查询

继续使用 README 中的版库和仓库初始化、打开入口。扩展 `energy.versions.publish.publish_version(versions, draft, *, retirable=False)`。`retirable` 是布尔值，只有版号首次登记时可选择。沿用原返回值与冻结规则的同参复领，改变已登记版的规则或退役选项报 `DomainError` 的 `conflict`。既有登记都视为普通版。

在 `energy.versions.retirement` 提供这两个入口：

- `retire_version(versions, retirement_number, version_number, exchange)` 受理或推进办件。
- `get_retirement(versions, retirement_number)` 读取版库已保存的办件。无此号返回 `None`，查单本身无需联络仓端。

结果提供 `retirement_number`、`version_number`、`status` 和 `blocker` 属性。`status` 为 `pending`、`blocked` 或 `retired`。仅 `blocked` 的 `blocker` 为 `(region, fact_number)`，其余为 `None`。编号为非空文本。同号同版推进待办或复领首个终态，改绑报 `conflict`。未知版报 `unknown_version`，普通版报 `not_retirable`。同一版有待办时，另号报 `retirement_in_progress`，已成功退役后另号报 `version_retired`。同一次办理可包含多次调用。联络恢复并继续原办件后须能结清。

## 首发与退役的结果

- 东仓和西仓都须纳入同一次退役裁决，覆盖该确切版的所有经营日。已正式提交且未冲销的事实算引用，即使其合计为零或全为缺测。实收、预检、未提交的首发和已冲销的事实均无活动引用。阻挡依据须在该办件受理到结清期间确实有效，满足条件的事实有多笔时任选一笔。
- `retired` 时两仓均无该版活动引用，此后也不能首次发布该版事实。`blocked` 返回后，两仓具备继续按该版首发的资格，包括同号同参继续此前未成的首发。后续冲销不改原 `blocked` 结果。消息迟到或重投不得改变已结清结果或影响另一次退役的资格。
- 继续以 `energy.facts.posting.post_usage(warehouse, region, request_number, preview_number, *, exchange=None)` 办首发。成功仍返回原 `FactReceipt`。可退役版首发尚不能判定时可报 `retirement_pending`，恢复联络后同号同参可续办。退役先成时，随后带可用交接的首次提交报 `version_retired`。省略 `exchange` 也不能绕过资格。已有同参首执照常本地复领，即使事实已冲销、版本已退役或交接暂不可用。V1 的错仓、改绑及预检唯一首发规则继续适用。
- 保留换算规则、实收、预检、冲销、现账和按号领取的原日报。由现账新冻的日报只计其读取时的有效事实。普通版维持原用法。

## 可信交接与重开

版库、东仓和西仓各自提交，互不读库。测试和演示用 `exchange(target, message)` 传递可信请求和应答，`target` 为 `catalog`、`east` 或 `west`。需要接收消息的一侧提供 `energy.versions.retirement.handle_catalog_message(versions, message)` 或 `energy.facts.posting.handle_warehouse_message(warehouse, message)` 供转发。消息形状由实现确定，调用方只作传送。公开入口可用 `energy.versions.retirement.DeliveryUnavailable` 区分本次未能得到应答。请求可以尚未送达、已经送达但失答，或在之后重新送达。验证可串行安排这些交错，无需实际网络。重送的消息须按其原身份解释，错版、错仓或错办件的应答不能推动本次裁决。

提交失败保留该库上次成功的状态。事实和首执仍在同一个本地事务中落定。失答后的重开只使用各库已落定的状态和之后收到的可信消息。不得以待办或失败当作成功首执。

## 样例及运行入口

`samples.retirement_fixture` 提供 `DRAFT` 和 `prepare_one`。V7 中 M1 每一原单位换成 7 kWh。`python3 -B -m samples.retirement_fixture` 跑普通版对照，显示预检后东西仓都无事实，随后东仓正常首发 7 kWh，冲销及重开后旧日报仍保有原量和出处。开发场景可以另开三库，以 `retirable=True` 首登记该草案。原 `tests/support.py` 的 `LocalMessages` 可在交付或回包时插入动作，`CommitControl` 可在本仓 `post` 提交前抛错。

- 无引用路径中，先为东仓备好 7 kWh，再办理 V7 退役。重开后重领退役终态并用旧预检首发，应拒绝且无新事实或首执。让已经排队的请求晚到，结论一致。
- 遇阻路径中，先在西仓另一经营日发布 V7 事实并冻结日报，东仓备好 7 kWh。退役须返回西仓和该事实号。东仓原尚未首发的请求随后可正式入账。冲销两笔事实后另号退役成功，旧号仍为遇阻。重开后原首执和西仓日报原版、原序、出处及合计照领。
- 将联络暂停在退役办理中，重开并恢复交付后同号结清，复领不改结论。分别让首发提交前失败和提交后失答，核对前者未产生事实或首执，后者是可复领且能阻挡退役的真实事实。重放旧请求或应答不得解除之后的有效约束。

沿用 `.pointwise-runtime.json` 的 v1 命令行运行约定。`setup` 为命令参数数组的列表，可为空。交付时让 `verify` 执行全部原回归和退役业务核验，失败时以非零码退出。`demo` 实际办理并展示上述无引用和遇阻两条路径。两项均以命令参数数组配置。README 中的 V1 回归与示例入口继续可运行。
