物理清洗与结构化规则，第一批
==========================

本目录使用原仓库的数据许可证。原数据来自
[K12-KGraph 的 physics.json](https://huggingface.co/datasets/lhpku20010120/K12-KGraph/blob/d8522c2b336ee435aa51daa39ca0dd736f56fa53/K12-KGraph/subject_specific_KG/physics.json)。
版本与 SHA-256 固定在 `source.json`。原始文件保存于被 Git 忽略的 `data/raw/physics/physics.json`，清洗过程不覆盖它。

执行边界
--------

`rules.json` 是首批可执行定义；`cleaned/graph.json` 是保留原文字段的来源图谱，不是可执行规则集。
运行时只读取表达树（abstract syntax tree，AST）、量类型、单位、模型条件和原理引用。
`display` 中的中文、原公式、注释不参与求值；程序不使用 `eval`、字符串公式解析或语言模型补全。

`schemas/physics_rule.schema.json` 检查结构；`physics.engine.validate_bundle` 独立检查符号、量纲、向量类型、同一坐标系和代数等价。
`run_rule` 检查输入单位、数值定义域、物理模型、初始条件、时间顺序和给定的终端边界条件。
它返回 SI 数值、单位、量纲及每一步的原理 ID。量纲顺序固定为质量、长度、时间、电流、温度、物质的量、发光强度。

支持的运算是 `var`、`number`、`add`、`sub`、`mul`、`div`、整数幂 `pow`、点积 `dot`、有限外力列表求和 `sum`；`eq` 只用于声明关系。
向量固定为同一参考系中的三个笛卡尔分量。除数必须是标量。单位换算使用登记的比例，输入不能省略单位。

首批规则
--------

| 规则 | 归档 | 适用范围 |
|---|---|---|
| `average_speed` | 初中 | 路程／时间；输出非负标量，区别于位移／时间 |
| `bulk_average_density` | 初中 | 物体总质量／总体积；不据此假设处处均匀 |
| `work_parallel_constant_force` | 初中 | 恒力与位移同向 |
| `newton2_point_mass` | 高中 | 经典、定质量质点、惯性系；先合成外力再求加速度 |
| `constant_a_velocity` | 高中 | 已声明坐标轴的匀加速度直线运动，初速度与初始时刻明确 |
| `constant_a_position` | 高中 | 上述条件加初始位置；显式使用时间差 |
| `constant_a_speed_squared` | 高中 | 同一坐标轴、恒加速度；只输出速度平方，不臆定速度符号 |
| `work_dot_constant_force` | 高中 | 恒力与位移的点积；单独保留扩展模型，可得到负功 |

牛顿第二定律保存为 `net_force = mass × acceleration`，执行步骤为外力矢量求和、除以正质量。
第二步引用牛顿第二定律和“等式两边除以非零标量”，并以符号代数校验变形等价性。
每个规则保存来源节点和实际教材节位置；物理条件的核对链接列于 `principles`。

运动输入需要明确 `force.behavior` 与 `force.depends_on` 时，后者只允许 `position`、`time`、`velocity`。
牛顿第二定律可处理给定时刻的变力分量，不据此求整段轨迹。
匀加速规则必须另有明确的恒加速度条件；定质量加变合力与该条件冲突时拒绝运行。
此版本不实现任意变力函数的微分方程求解、旋转参考系、变质量系统、温标偏移或误差传播。

归档与保留
----------

`cleaned/curriculum/primary.json`、`middle.json`、`high.json` 只存规范节点引用。
小学为空，因为当前来源只有初中和高中物理；没有补造小学记录。
同一规范节点只归入当前九本教材数据中最早可观察到的位置，后续出现保留为引用。
上游图谱已经跨教材合并，不能据此还原所有历史版本的首次定义，也不能证明整个 K12 体系的绝对首次出现。

本批只合并人工核对为同一关系的 `physics_bx1_rjb_cpt33 → physics_bx1_rjb_cpt31`，保留较早的第二章第二节。
别名原节点及关系映射保存在 `provenance.json`。名称相同本身不触发合并。
初中同向做功与高中点积做功共享来源概念，但用不同模型记录；后者通过 `variant_of` 引用前者。

类型违反原仓库 `src/kg/prompt.txt` 定义的 13 条关系隔离到 `quarantine.json`，不猜测替换关系。
章节间 `leads_to` 依照 `src/benchmark/generate_benchmark.py` 的章节任务保留。
`pending.json` 保留 228 个尚未完成语义转换的公式节点；这些节点没有执行权限。
`review.json` 记录速度定义混用、时间定义过窄等待核对问题。中文原文保留，未自动重写。

复现
----

在仓库根目录运行：

```bash
python -m pip install -r requirements-physics.txt
PYTHONPATH=src python -m physics.fetch_source
PYTHONPATH=src python -m physics.clean --input data/raw/physics/physics.json --source knowledge/physics/source.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

调用示例存于 `examples.json`，包含单位换算、非零初始时刻、明确初始位置和边界约束。

```python
from physics.engine import read_json, run_rule
bundle = read_json('knowledge/physics/rules.json')
case = read_json('knowledge/physics/examples.json')[2]
result = run_rule(bundle, case['rule_id'], case['bindings'], case['context'])
# acceleration: [5, 0, 0] m/s^2；trace 包含 vector_sum、newton、divide_nonzero。
```
