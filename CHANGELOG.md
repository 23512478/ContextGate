# Changelog

本仓库的所有重要变更都会记录在此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [未发布]

## [v0.2.0] — 2026-09-08

v0.1.0 之后经过 **4 轮、23 个真实开源项目**练兵（mall / vhr / ruoyi-vue-pro / yudao-cloud / pig / litemall / JeecgBoot / snowy / dax-pay 等），内嵌 SQL 识别从 v0.1.0 的单点规则演进为跨方法/跨类的数据流分析。

### 新增

- **跨方法/跨类数据流（第四轮，收窄三条边界）**
  - 全局 helper 注册表：跨类 helper（`lqw = Other.buildXxx(...)`）与 helper 套 helper 文本递归展开（防环）；接收者按字段类型解析（`orderQuerySupport.buildBase` → `OrderQuerySupport#buildBase`）
  - Wrapper/Example 参数传播：调用方拼的条件/语句播种给带 Wrapper 参数（含 MP 基类 `Wrapper<T>`）或带 Example 参数且有方法体的目标方法，不动点收敛；传播版落地后自动剔除同一方法的「本地降级版」记录
  - Example criteria 分组语义：`createCriteria()` 开 AND 组、`or()` 开 OR 组（含 `example.or().andXxx()` 匿名组），多组带括号、组间按连接词连接；Example 作参数跨类传播（方法名不限，按参数类型识别）
  - 跨类常量互拼：`SQL_A = "..." + Other.SQL_B` 全局不动点折叠（token 支持点号限定名）
  - 回归验证：litemall Example 123/123 恢复（`example.or()` 匿名组修复）；RuoYi-Vue-Plus 真缺失 71 → 22（`Wrapper<T>` 基类参数对接）；demo 断言 7.34-7.37 全绿
- **真实项目训练（第三轮：OneBlog / newbee-mall-cloud / renren-security / pig / yudao-cloud）**
  - 验证轮：零新增缺陷，前两轮规则全部经受住跨仓库验证——pig 5 处懒加载子查询链接正确产出；yudao-cloud（与 ruoyi-vue-pro 同源不同仓库）识别 1628 条 Wrapper 记录，helper 归并/X-Wrapper/字段值规则跨仓库一致复现
  - 残缺仅 2 个声明无实现的死代码方法（OneBlog SysLogMapper / xzs UserMapper），非分析器问题
- **真实项目训练（第二轮：snowy / xmall / favorites-web / xzs / dax-pay）**
  - ServiceImpl/BaseManager 继承式调用：`extends ServiceImpl<M, T>` / `BaseManager<M, T>` 的服务层不再要求注入 mapper 字段，`this.list()`/`remove()`/`getById()` 等 17 个继承方法映射到泛型 M 的 baseMapper 内置方法（snowy 逆向索引 4 → 200，事务闭包 339 → 480）
  - Manager 层字段值调用：BaseManager 派生类里 `this.findByField(Entity::getField, value)` 合成 WHERE（dax-pay 内嵌 SQL 2 → 52 条）；DELETE/UPDATE 语义按调用动词细分
  - favorites-web 为 JPA 项目（无 MyBatis），逆向索引 0 属正确行为
- **真实项目训练（第一轮：mall / ruoyi-vue-pro / JeecgBoot / jpetstore-6 / renren-fast）**
  - X 后缀扩展 Wrapper（`LambdaQueryWrapperX` / `QueryWrapperX` 等，yudao 系自研类）纳入 Wrapper 识别与 def-use
  - Mapper default 方法字段值便捷调用：`selectOne(Entity::getField, value)`（支持多字段对，yudao/BaseMapperPlus 风格，ruoyi-vue-pro 仓库实测 500+ 处）；count 族只触碰条件列。ruoyi-vue-pro 内嵌 SQL 识别 178 → 1631 条，无 SQL 方法覆盖率 85%
  - XML 懒加载子查询链接（`sub_selects` N+1 标注）与无接口方法的 XML 语句可见性
  - Wrapper 条件构建 helper / 方法参数 / 拷贝别名 / Mapper `this.lambda()` 链
  - 多项目模式（`CODECONTEXT_MAPS_DIR` + `project` 参数 + `list_maps`）

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

- MapStruct 的 `@Mapper` 与 MyBatis `@Mapper` 撞名误判：按 import 归属区分（ruoyi-vue-pro 数千个 `*Convert` 接口方法曾被误报为 Mapper 方法）；`extends BaseMapper` 的仍按 MyBatis 处理
- 逆向索引统计按 is_mapper 类计数，`*Dao` 命名的 mapper（renren-fast）不再被漏计
- XML 语句列清单的逗号清理会误伤 `order_id` 这类列名（`order` 前缀被误当 ORDER 关键字），补词边界
- 类注解名改从去注释文本抽取：javadoc/注释里提及 `@Mapper`、`@param` 等，或 `@MapperScan` 含 `@Mapper` 子串，会把启动类误判成 Mapper、`@RestControllerAdvice` 异常处理器误判成 Controller（litemall/RuoYi 真实项目实测踩中）
- README 快速开始的 MCP 配置示例把环境变量写成了 `CONTEXTGATE_PROJECT`/`CONTEXTGATE_MAP`，与 server 实际读取的 `CODECONTEXT_*` 不一致——照抄配置会被静默忽略并回退到内置 demo 地图；已更正，同步更新贡献指南排队规则清单与 demo 文件数

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
