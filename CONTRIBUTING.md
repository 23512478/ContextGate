# 贡献指南：怎么加一条解析规则

ContextGate 的分析器是「正则级静态分析」——不追求 100% 语法正确，目标是**地图够准、够用、秒级出结果**。它的规则几乎都是被真实项目里的漏报逼出来的，所以加规则的标准流程是：

1. 用真实项目复现漏报（哪条调用链/哪个字段没被识别）
2. 写最小修复（优先复用现有函数，别急着造新轮子）
3. 加回归断言（`mcp-server/test_mcp.py`）或 demo 夹具
4. 跑 `python mcp-server/test_mcp.py` 全绿

## 代码地图

### analyzer/framework_map.py（全部解析逻辑都在这一个文件）

| 位置 | 干什么 |
|---|---|
| `MAPPING_ANN` / `HIDDEN_ANN` / `SQL_ANN` | 路由注解、隐藏入口（@Scheduled 等）、SQL 注解映射表 |
| `MP_BUILTIN` / `MP_WRITE` | MyBatis-Plus 内置方法名单（读/写分类） |
| `FIELD_RE` / `TABLE_FIELD_RE` / `simple_type()` | 实体字段解析（支持全限定类型、泛型、数组） |
| `extract_sql()` | 从 @Select/@Update 等注解里抠 SQL 文本 |
| `resolve_sql_columns()` | **列触碰解析的核心**：字面列名 + 裸 `SELECT *` + 别名星号 `o.*` 展开 |
| `mp_builtin_sql_record()` | 给 MP 内置方法造合成 SQL 记录（全列触碰） |
| `parse_xml_mappers()` | XML mapper 解析（resultMap 含 extends/association/collection、sql 片段 + include、foreach、懒加载子查询链接） |
| `scan_inline_sql()` / `_wrapper_record()` | 内嵌 SQL：JdbcTemplate 裸 SQL（含局部 String 变量）、MP Wrapper 动态链（方法引用→列） |
| `scan_methods()` | 线性扫描方法声明（**不要改回大正则**，会灾难性回溯） |
| `reverse_index()` | 逆向索引：Mapper 方法 → 调用者 → 上游路由 |
| `main()` | 主流程：扫文件 → 建图 → 出 markdown + JSON |

### mcp-server/mcp_server.py

- `mapper_sql_map()`：把 JSON 里的 mapper 方法拍平成 `Mapper#方法 → {sql, reverse}`
- `trace_call()` / `find_sql()` / `impact()` / `refresh_map()`：四个 MCP 工具
- 合成 SQL（MP 内置、XML 补全）和真实 SQL 用 `sql["mp_builtin"]` 标志区分，**新增展示逻辑时注意这个标志**（`find_sql` 要排除它，`trace_call` 要换标签）

## 加规则的三种典型场景

**新注解/新框架约定**（比如想支持 `@KafkaListener` 之外的 MQ 注解）：往 `HIDDEN_ANN` 或相应映射表加名字；如果涉及新的调用边类型，在 `parse_java()` 建边处补逻辑。

**新的 SQL 形态**（比如 `WITH ... CTE`、`INSERT ... SELECT`）：优先在 `resolve_sql_columns()` 里补，别在调用方各写各的；表名提取走 `SQL_TABLE_RE`，别名映射已经在函数里建好。

**新的实体字段形态**（比如 `@TableField(exist=false)`、record 类）：改 `FIELD_RE` 或 `parse_java()` 的实体段，记得全限定类型/泛型/数组已经在 `_TYPE` 模式里覆盖。

## 硬性要求

- **零外部依赖**（analyzer 只用标准库；mcp-server 只用 `mcp`）
- **不许引入灾难性回溯正则**：方法级解析用线性扫描（见 `scan_methods`），新增正则避免嵌套量词；87 个文件的项目必须在几秒内跑完
- **边界情况不许崩**：实体没 `@TableName`、XML 损坏、namespace 缺失、resultMap type 找不到实体——全部降级跳过，不抛异常
- **注释用白话中文**（说人话，别写"本方法旨在……"这种）
- 改完跑两件事：
  ```bash
  python analyzer/framework_map.py examples/demo-project examples/demo-framework-map.md
  python mcp-server/test_mcp.py
  ```

## 提交 PR 时

- 说清楚：哪个真实项目的什么写法导致了漏报（最好附一小段 Java 源码）
- 规则补丁 + 回归断言放同一个 PR
- 如果 demo-project 里加了新夹具文件，确保它能体现规则（比如为新 SQL 形态在 demo mapper 里加一条对应方法）
