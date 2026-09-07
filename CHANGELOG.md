# Changelog

本仓库的所有重要变更都会记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [v0.1.0] — 2026-09-08

首个公开发布版本。经过 campus-job（私有项目）、mall、vhr 三个真实 Spring Boot + MyBatis 项目验证，核心链路可用。

### 核心能力

- **静态分析器**（`analyzer/framework_map.py`，零依赖）：扫描 Java 源码，输出结构化 JSON 地图——路由表、调用图、SQL 索引（表/列触碰）、事务闭包、实体↔表映射
- **MCP Server**（`mcp-server/mcp_server.py`）：4 个工具，可被 Trae / Cursor / Claude Code 等支持 MCP 协议的 AI 工具调用
  - `trace_call`：输入路由或方法名，输出 Controller→Service→Mapper→SQL 完整调用链，标注事务边界
  - `find_sql`：按 Mapper 方法名 / 表名 / 列名反查 SQL，给出 SQL 全文、触碰列、上游路由
  - `impact`：改实体/字段前查影响面——波及的自定义 SQL、MP 内置 CRUD 调用点、内嵌 SQL、路由清单
  - `refresh_map`：代码改完一键重跑分析器，秒级刷新
- **demo 项目**（`examples/demo-project`，20 个 Java 文件 + XML）：覆盖所有解析规则的测试靶场，clone 后零配置可跑 `test_mcp.py`

### 已覆盖的解析规则

- 路由注解（`@GetMapping` / `@PostMapping` / `@RequestMapping` 等）
- `@Autowired` 依赖注入（含包私有字段）
- `@Transactional` 事务闭包传播（**支持标在接口方法上**，自动传播到 impl）
- 注解 SQL（`@Select` / `@Update` / `@Insert` / `@Delete`）
- XML mapper（`<resultMap>` / `<sql>`+`<include>` / `<set>` / `<if>`，XML 可在 resources 或 java 源码目录）
- **内嵌 SQL**：JdbcTemplate 裸 SQL（支持字符串拼接和方法内局部变量传参）、MyBatis-Plus `LambdaQueryWrapper` / `lambdaQuery()` 动态链（`.eq` / `.like` / `.in` / `.set` / `.orderBy` 方法引用还原为 SQL）
- 实体映射：`@TableName` / `@TableField` **或** model/domain/entity 包下裸 POJO 自动推断表名
- MyBatis-Plus `BaseMapper` 内置方法（`selectById` 合成 `SELECT *` 触碰全列）
- 全限定类型字段（`java.math.BigDecimal`）、原生类型、泛型、数组
- 裸 `SELECT *` 与别名星号 `o.*` / `g.*` 展开
- 跨表 JOIN 列的别名限定精确归因
- **多模块 Maven**：自动扫描所有 `src/main/java`
- `@PostConstruct` / `@Scheduled` / `@KafkaListener` 等隐藏入口识别

### 工程保障

- 分析器用线性扫描器替代大正则，避免灾难性回溯（87 文件秒级出图）
- `test_mcp.py` 端到端测试（走真实 MCP 握手），20+ 断言覆盖每种规则
- 已知边界诚实标注在 README

### 已知限制

- 正则级解析，内部类 / Lombok 生成方法 / 复杂泛型可能漏
- MyBatis-Plus 内置方法给的是"全列触碰"的保守上界
- Wrapper 拆成变量跨语句链式调用（`var w = new LambdaQueryWrapper<>(); w.eq(...)`）只识别构造语句
- JdbcTemplate 的 SQL 抽成类级 `static final` 常量暂不追踪
- MyBatis Generator 的 `Example` 动态条件暂未解析
- XML `<association>` / `<collection>` / `<foreach>` / resultMap `extends` 暂未解析
