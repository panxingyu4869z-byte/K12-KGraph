物理内容：结构化关系、模型与单位
================================

五批处理了固定来源版本中的全部 236 个含 `formula` 字段的记录：合并 1 个重复记录，235 个规范记录都有明确内容链接。当前有 176 条计算规则和 24 条单位、常量或量声明。`pending.json` 为空表示这些公式字段已分类与转换；不表示所有原始中文描述都已重新编写，也不表示所有物理问题都能自动求解。

来源版本和 SHA-256 见 `source.json`；数据许可证沿用原仓库。原始数据保留在被 Git 忽略的 `data/raw/physics/physics.json`，没有覆盖。`cleaned/graph.json` 是来源图谱，`cleaned/content_links.json` 把每个规范公式记录链接到结构化内容。

程序读取的内容
--------------

- `rules.json`：对象模型、量及其标量/向量类型、量纲、单位、适用条件、初始条件、力的依赖、数学关系、步骤和结论。每一步引用实际使用的原理 ID。
- `catalog.json`：单位等式、精度明确的常量、只有名称/符号的量声明。数量声明没有被伪造成计算规则。
- `display`：中文名称、原公式和说明，仅展示与溯源；修改这些文本不影响计算。

表达树使用闭合的 `op` 语法。支持变量、数值、带单位字面量、四则运算、整数幂、平方根、绝对值、三角函数、`atan2`、对数、向量构造、点积、叉积、模长、有限列表求和以及等式/不等式。未知操作、额外字段和错误元数被拒绝；没有字符串公式求值。

`schemas/physics_rule.schema.json` 与 `schemas/physics_catalog.schema.json` 只检查结构。`physics.engine` 另查符号、标量/向量、量纲、坐标系、数值定义域、模型条件、代数变形和核反应守恒；`physics.catalog` 用精确有理数另查单位等式。量纲次序是质量、长度、时间、电流、温度、物质的量、发光强度。

单位输入不可省略。角度可由度换为弧度，角速度输出使用 `rad/s`。绝对温度与温差分别登记；摄氏读数先换为开尔文，再检查绝对温度定义域。运行器返回 SI 数值和逐步原理记录；一般数值求值使用浮点数，独立复核使用精确有理数和符号式。

模型与条件
----------

牛顿第二定律要求经典、定质量质点和惯性系。先对外力矢量求和，再除以正质量；除法变形单独校验。给定时刻的变力可带 `position`、`time`、`velocity` 依赖，不据此推断整段匀加速轨迹。

匀加速、平抛和简谐运动有显式初值和初始时刻；振幅/相位形式先计算初始位置与速度。终端边界由调用方明确给定并检查。不能把定质量、变合力同时当成恒加速度。任意变力微分方程、非惯性系和通用变质量运动不在本运行器范围内；理想火箭只在专门列出的条件下使用对数关系。

新增适用范围单独建规则并用 `variant_of` 引用相关关系。同一知识的后续教材出现只作 `source_nodes` 引用。例如路程/时间是初中标量速率，位移/时间是高中矢量速度；同向恒力做功和一般点积做功各有适用条件。静摩擦可为零；静电空腔零场要求腔内无电荷；有限磁通差商是平均感应电动势；光电效应要求达到阈值。

核衰变保存完整产物和无量纲核子数、电荷数、电子轻子数。β负衰变包含电子反中微子。守恒数校验不代替衰变道能量许可、半衰期或核质量数据。

归档与复核
----------

`cleaned/curriculum/primary.json`、`middle.json`、`high.json` 保存规范节点引用，每个知识节点归档一次；后续出现保留为引用。本来源没有小学物理记录，故小学为空。最早位置只指当前九本教材数据中最早可观察位置，不能还原所有历史教材版本。

2,025 个来源节点和 4,092 条关系均已检查。清洗图保留 2,024 节点、4,079 条关系；13 条端点类型异常关系在 `quarantine.json` 中完整保留。重复记录原文与边映射保存在 `provenance.json`；模型、精度和原文问题的处理记录见 `review.json`。

每批验证见 `cleaned/batchN_review.json` 与 `cleaned/batches.json`。最终 20 项测试通过；独立复核程序不导入生产解释器，核对 176 个算例、13 个单位等式、2 个核反应的守恒数、量纲和运动学导数。另用 LIE-1 原生 Quantity 运算交叉检查量纲；这是独立算术证据，不代表完整 LIE 求解器集成验收。

复现
----

```bash
python -m pip install -r requirements-physics.txt
PYTHONPATH=src python -m physics.fetch_source
PYTHONPATH=src python -m physics.clean --input data/raw/physics/physics.json --source knowledge/physics/source.json
PYTHONPATH=src python -m unittest discover -s tests -v
python tests/review_physics_batches.py --output knowledge/physics/cleaned/independent_review.json
```

调用示例均在 `examples.json` 中：

```python
from physics.engine import CompiledRules, read_json
engine = CompiledRules(read_json('knowledge/physics/rules.json'))
case = next(x for x in read_json('knowledge/physics/examples.json')
            if x['rule_id'] == 'newton2_point_mass')
result = engine.run(case['rule_id'], case['bindings'], case['context'],
                    case['boundary_conditions'])
```
