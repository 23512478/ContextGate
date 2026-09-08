# ContextGate

[![Release](https://img.shields.io/github/v/release/23512478/ContextGate)](https://github.com/23512478/ContextGate/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

> 给 Spring Boot + MyBatis(-Plus) 项目做一份「框架感知代码地图」，再通过 MCP 协议喂给 AI 编程工具（Trae / Cursor / Claude Code 等）。

AI 编程工具改后端代码时，通常靠全文搜索去猜"这个接口调了谁、这条 SQL 碰了哪些表、改这个字段会炸哪条链路"——费 token、还容易幻觉。ContextGate 的思路是**离线预编译框架约定**：把 Spring 的隐式约定（路由注解、依赖注入、事务边界）和 MyBatis 的映射关系（Mapper → SQL → 表/列 → 实体）静态解析成结构化地图，AI 只需要调一个工具就能拿到压缩后的调用链和影响面。

## 为什么需要它

Spring Boot + MyBatis 项目的调用关系大量是**隐式约定**：一个 HTTP 请求要经过 `@RequestMapping` → Controller → `@Autowired` 注入的 Service → `BaseMapper` → SQL，中间没有任何一处显式 import 能把它们串起来。AI 每次都得翻七八个文件才能拼出一条链。

而通用代码索引看不懂这些"框架黑话"。三个最直接的痛点：

1. **改字段不知道会炸哪**：改一个实体字段（如 `walletBalance`）前，要人工找出所有读写它的 SQL 和接口——显式注解 SQL 好查，MyBatis-Plus 的 `selectById`/`insert` 这种隐式全行读写最容易漏。ContextGate 在真实项目上的实测：工具找出的波及路由比人工排查多出约一半，多出来的全是走 MP 内置 CRUD 的链路。
2. **事务边界靠脑补**：`@Transactional` 闭包里调了哪些写操作、回滚影响什么，工具直接标在调用链上。
3. **AI 会幻觉**：工具返回的是从源码数出来的事实（路由、Mapper 方法、SQL 全文、触碰列都有出处），AI 没法编造不存在的方法或路径。

**定位是"窄而深"**：不做通用代码 RAG，只做 Spring Boot + MyBatis 这一个垂直，但把框架语义做到列级（`o.*` 星号展开、JOIN 列精确归因、MP 内置方法全列触碰）。框架约定越重的项目，通用工具越吃力，这个垂直线索的价值越大。

### 和现有方案的差异

| 方案 | 强在哪 | ContextGate 的不同 |
|---|---|---|
| 全量代码 RAG（embedding） | 语言无关、什么代码都能塞 | 召回靠相似度，不懂事务边界、SQL 触碰列、MP 隐式 CRUD——这些框架语义完全不知道 |
| LSP 符号索引（定义跳转/引用） | 显式调用关系精确 | 注解注入、`BaseMapper` 内置方法、`SELECT *`/XML SQL 都是"字符串/约定"，不在符号层，全部盲区 |
| AI 编码工具自带的代码搜索 | 零配置 | 每次对话全量 grep，token 贵、结果靠 AI 临场推理，同一个问题每次重新推 |

不是替代关系：工具给主干（调用链、影响面），AI 再用源码搜索补边角（如 JdbcTemplate 裸 SQL）。

## 它能做什么

- **调用链追踪**：`GET /api/v1/orders/my` → Controller → Service → Mapper → SQL 全文，含 `@Transactional` 事务边界标记
- **SQL 反查**：按 Mapper 方法名 / 表名 / 列名片段搜 SQL，给出 SQL 全文、涉及表、触碰列、上游调用者和路由
- **变更影响面**：改实体/字段前查出波及的自定义 SQL、MyBatis-Plus 内置 CRUD 调用点（`selectById`=SELECT * 全列触碰）、上游路由
- **一键刷新**：代码改完让 AI 调 `refresh_map`，秒级重跑分析器
- **多项目**：配置 `CODECONTEXT_MAPS_DIR` 后一个 server 管多个项目——`refresh_map` 自动注册、查询工具 `project` 参数切换、`list_maps` 列出全部项目和地图新鲜度

已覆盖的解析规则：路由注解（`@GetMapping` 等）、`@Autowired` 注入（含包私有字段）、`@Transactional` 闭包传播（**支持标在接口方法上**，自动传播到 impl）、注解 SQL（`@Select/@Update/...`）、XML mapper（`<resultMap>`（含 `extends` 继承、`<association>`/`<collection>` 嵌套映射与 `select=` 懒加载子查询链接）/`<sql>`+`<include>`/`<set>`/`<if>`/`<foreach>`，XML 可在 resources 或 java 源码目录）、**内嵌 SQL**（JdbcTemplate 裸 SQL 含局部变量传参、类级 `static final` 常量及**同类常量互拼折叠**、MyBatis-Plus `LambdaQueryWrapper`/`lambdaQuery()` 动态链、**Wrapper 拆变量跨语句链式调用**含拷贝别名、方法参数、**helper 方法条件归并**与 Mapper default 方法 `this.lambda()` 链）、实体映射（`@TableName/@TableField` **或** model/domain/entity 等包下裸 POJO 自动推断表名）、MyBatis-Plus `BaseMapper` 内置方法（count 族标 0 列）、**MyBatis Generator `Example` 动态条件**（`andXxxEqualTo` 链 + `selectByExample` 消费合成 WHERE）、全限定类型字段、裸 `SELECT *` 与别名星号 `o.*` 展开、跨表 JOIN 列精确归因、**多模块 Maven**（自动扫描所有 `src/main/java`）。仓库自带 `examples/demo-project`（21 个 Java 文件 + XML），每种规则都有夹具和回归断言。

## 目录结构

```
analyzer/      零依赖静态分析器（纯标准库 Python），产出 framework_map.md / .json
mcp-server/    MCP Server（FastMCP），暴露 trace_call / find_sql / impact / list_maps / refresh_map
examples/
  demo-project/         迷你 Spring Boot 项目（测试夹具，覆盖各种 SQL 形态）
  demo-framework-map.*  分析 demo 项目产出的示例地图
```

## 快速开始

需要 Python 3.10+。

### 1. 分析你自己的项目（分析器零依赖）

```bash
python analyzer/framework_map.py /path/to/your-spring-boot-project
```

默认输出到 `analyzer/framework_map.md` 和 `.json`。也可以指定输出路径：

```bash
python analyzer/framework_map.py /path/to/project /path/to/output.md
```

### 2. 启动 MCP Server

```bash
pip install -r mcp-server/requirements.txt   # 只需要 mcp<2
python mcp-server/mcp_server.py              # 直接跑是 stdio 模式，由 AI 工具拉起
```

### 3. 在 AI 工具里配置

Trae：在你的 Spring Boot 项目根目录放 `.trae/mcp.json`；Cursor：写进全局 `~/.cursor/mcp.json`；Claude Code：项目根目录放 `.mcp.json`（格式相同），或执行 `claude mcp add contextgate -- python <本仓库绝对路径>/mcp-server/mcp_server.py`。

```json
{
  "mcpServers": {
    "contextgate": {
      "command": "python",
      "args": ["<本仓库绝对路径>/mcp-server/mcp_server.py"],
      "env": {
        "CODECONTEXT_PROJECT": "<你的 Spring Boot 项目根目录>",
        "CODECONTEXT_MAP": "<分析产出的 framework_map.json 绝对路径>"
      }
    }
  }
}
```

> Windows 下 `command` 填你的 python.exe 完整路径更稳。不配置 env 也能跑：server 默认用仓库自带的 demo 地图（`examples/demo-framework-map.json`），零配置即可体验。

### 多项目模式（可选）

默认一个 server 服务一个项目。要同时管多个项目，给 env 加一个 `CODECONTEXT_MAPS_DIR` 指向地图目录：

```json
"env": { "CODECONTEXT_MAPS_DIR": "<放地图的目录，如 ~/.contextgate/maps>" }
```

之后对 AI 说"刷新一下 xxx 项目"（`refresh_map` 传项目路径），地图就按项目目录名落盘 `<项目名>.json` 并注册；查询时说"在 mall 项目里查这条 SQL"（查询工具带 `project` 参数）即可切换，`list_maps` 列出全部项目和地图新鲜度。

不想动配置也可以一个项目起一个 server 实例（各配各的 env），工具名会带实例前缀，AI 按项目选用——个人两三个项目够用。

### 4. 零配置体验 / 跑测试

```bash
python mcp-server/test_mcp.py
```

会自动分析 `examples/demo-project`、走一遍 MCP 握手和四个工具的调用并做断言。

接入后在 AI 对话框里直接说人话即可，比如：

- "追踪 `GET /api/v1/orders/my` 的完整调用链"
- "wallet_balance 被哪些 SQL 触碰？改这个字段影响哪些接口？"
- "改 User 实体会影响什么？"
- "刷新框架地图"

## 已知边界（诚实清单）

- **正则级解析，不是真 Java AST**：复杂语法（内部类、Lombok 生成方法等）可能漏，遇到再补规则
- **MyBatis-Plus 内置方法：行读取标全列、count 族标 0 列**——`selectById`/`selectList` 底层就是取整行，标"触碰全部列"是语义事实而非近似；`selectCount`/`count`/`exists`/`countByExample` 是 COUNT，不触碰业务列
- **Wrapper 跨语句/跨方法/跨类**：定义/续链/消费点分离、if/for 分支内续链（保守计入，宁多报不漏）、拷贝别名（`w2 = w`）、Wrapper 作方法参数、本类/跨类 helper 构建（`lqw = buildXxx(...)` / `lqw = Other.buildXxx(...)`，含 helper 套 helper）都可解析；调用方拼的条件经参数传播归并，**沿调用链不动点收敛——多跳、跨类可追**（实测 Controller → Service A → Service B → Mapper 三跳，条件不丢）。前提：每跳目标方法有方法体、接收者类型可解析（注入字段或类名）；接收者解析不出类型的调用（链式返回值 `getService().x(w)`、方法内 `new` 出来的对象）不追
- **SQL 常量支持字面量拼接、同类互拼折叠与跨类互拼**（`SQL_A = "..." + Other.SQL_B`，全局不动点折叠）；运行期拼参（`"..." + variable`）静态拿不到
- **MBG `Example` 动态条件**：criteria 分组语义已还原——`createCriteria()` 开 AND 组、`or()` 开 OR 组（含 `example.or().andXxx()` 匿名组），多组时带括号、组间按连接词连接；Example 作方法参数传入时调用方条件经传播归并（方法名不限，按 Example 参数类型识别；Example 参数传播追一跳，Wrapper 参数传播多跳）

## 参与进来

这个工具的每条解析规则几乎都是被真实项目"逼"出来的：全限定类型字段漏解析、裸 `SELECT *` 不算触碰列、别名星号 `o.*`、跨表 JOIN 列归属、XML `<include>`……规则覆盖率随真实项目增长，**你的项目就是最好的测试用例**。

三种参与方式，按难度排序：

1. **拿你的项目跑一把，报漏报**（最有价值）：`python analyzer/framework_map.py <你的项目>`，对照 `framework_map.md` 找"这条链路/这个字段明明用了却没出现"的地方，提 issue 附一小段 Java/XML 源码即可。
2. **补解析规则**：已知排队中的规则——Wrapper `.select()` 子查询列裁剪、Example 参数多跳传播（目前追一跳）、接收者类型不可解析的调用链（详见上文「已知边界」）。方法见 [CONTRIBUTING.md](CONTRIBUTING.md)，流程是"demo 夹具 + 断言 + 全绿"。
3. **适配更多 AI 工具 / 语言**：MCP 是标准协议，接入新工具基本零成本；分析器目前只覆盖 Java 侧。

## License

MIT
