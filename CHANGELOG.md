# Changelog

本仓库的所有重要变更都会记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增

- XML mapper 解析增强：`<foreach>` 批量条件重建（保留 `IN (…)` 形状与参数占位）、resultMap `extends` 继承合并（父映射流入子映射）、`<association>`/`<collection>` 嵌套映射的列归因到 javaType/ofType 对应实体
- JdbcTemplate 的 SQL 抽成类级 `static final` String 常量可解析（支持字面量拼接与 `Foo.SQL_X` 跨类引用；常量互拼不追）
- MyBatis-Plus Wrapper 拆变量跨语句链式调用：定义/续链/消费点分离的写法可拼出完整合成 SQL，if 分支内续链保守计入（单变量直链）
- 常量互拼折叠：类级 SQL 常量支持引用同类常量（`SQL_A + "字面量"`，不动点折叠；环/未知标识符放弃）
- Wrapper 拷贝别名：`w2 = w` 共享底层链，任一变量后续续链都计入同一查询
- MP 内置 count 族（`selectCount`/`count`/`exists`/`countByExample`）不再虚报全列，标 0 列；行读取方法维持全列（语义事实：取整行）
- MyBatis Generator `Example` 动态条件解析（v1）：`andXxxEqualTo` 等条件方法解码列名/操作符，`selectByExample`/`countByExample`/`deleteByExample`/`updateByExample` 消费合成 WHERE；`*ByExample` 方法纳入内置方法合成
- Wrapper 作方法参数：方法签名带 `XxxWrapper<Entity>` 参数时按已定义变量分析方法内续链与消费，合成 SQL 标注在消费方法（方法外拼的条件不跨方法追）
- XML 懒加载子查询链接：`<association select=...>`/`<collection select=...>` 记录为 `sub_selects`，trace_call / find_sql 标注 N+1 子查询；无 Java 接口方法声明的 XML 语句也纳入地图
- Wrapper 条件构建 helper：`lqw = buildXxx(...)` 调用本类返回 Wrapper 的方法时，helper 方法体里的条件链归并进消费点；helper 结果直接作为参数传参（`mapper.method(buildXxx(...))`）同样支持。消费点判定放宽为「接收者是本类字段 / this / baseMapper」，自定义 mapper 方法名（如 `selectDeptList(wrapper)`）不再要求标准动词（RuoYi-Vue-Plus 实测：内嵌 SQL 识别 0 → 46 条）
- Mapper 接口 default 方法的 `this.lambda()` 动态链（实体取 Mapper 泛型）；`BaseMapperPlus<T, V>` 等扩展泛型的实体识别
- MCP Server 多项目模式：新增 `CODECONTEXT_MAPS_DIR` 地图目录，`refresh_map` 按项目目录名自动注册，三个查询工具新增 `project` 参数，新增 `list_maps` 工具

### 修复

- XML 语句列清单的逗号清理会误伤 `order_id` 这类列名（`order` 前缀被误当 ORDER 关键字），补词边界
- 类注解名改从去注释文本抽取：javadoc/注释里提及 `@Mapper`、`@param` 等，或 `@MapperScan` 含 `@Mapper` 子串，会把启动类误判成 Mapper、`@RestControllerAdvice` 异常处理器误判成 Controller（litemall/RuoYi 真实项目实测踩中）

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

### 修复

- 字段扫描会把方法体里的 `return x;` 语句误判为 `return` 类型的伪字段，导致调用树出现 `return#setXxx` 这类假节点（也会混进事务闭包）；已按语句关键字排除
- `impact` 的事务标记歧义：MP CRUD 调用点的 🔒 改为逐调用者标注（只有从事务路径调进来的才带锁），读操作只标「🔒事务内」不再误标「写」
- 分析器 stdout 输出粘连缺换行；顺带移除漂移的 `framework_map.py:NNNN` 调试残留

### 已知限制

- 正则级解析，内部类 / Lombok 生成方法 / 复杂泛型可能漏
- MyBatis-Plus 内置方法给的是"全列触碰"的保守上界
- Wrapper 拆成变量跨语句链式调用（`var w = new LambdaQueryWrapper<>(); w.eq(...)`）只识别构造语句
- JdbcTemplate 的 SQL 抽成类级 `static final` 常量暂不追踪
- MyBatis Generator 的 `Example` 动态条件暂未解析
- XML `<association>` / `<collection>` / `<foreach>` / resultMap `extends` 暂未解析
