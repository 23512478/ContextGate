# ContextGate

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

- **调用链追踪**：`POST /orders/my` → Controller → Service → Mapper → SQL 全文，含 `@Transactional` 事务边界标记
- **SQL 反查**：按 Mapper 方法名 / 表名 / 列名片段搜 SQL，给出 SQL 全文、涉及表、触碰列、上游调用者和路由
- **变更影响面**：改实体/字段前查出波及的自定义 SQL、MyBatis-Plus 内置 CRUD 调用点（`selectById`=SELECT * 全列触碰）、上游路由
- **一键刷新**：代码改完让 AI 调 `refresh_map`，秒级重跑分析器

已覆盖的解析规则：路由注解（`@GetMapping` 等）、`@Autowired` 注入、`@Transactional` 闭包传播、注解 SQL（`@Select/@Update/...`）与 XML mapper（`<resultMap>`/`<sql>`+`<include>`/`<set>`/`<if>`）、`@TableName/@TableField` 实体映射、MyBatis-Plus `BaseMapper` 内置方法、全限定类型字段（`java.math.BigDecimal`）、裸 `SELECT *` 与别名星号 `o.*` 展开、跨表 JOIN 列的别名限定精确归因。仓库自带的 `examples/demo-project` 是一个 12 个 Java 文件 + XML 的迷你项目，以上每种规则都有对应夹具和回归断言。

## 目录结构

```
analyzer/      零依赖静态分析器（纯标准库 Python），产出 framework_map.md / .json
mcp-server/    MCP Server（FastMCP），暴露 trace_call / find_sql / impact / refresh_map
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

Trae：在你的 Spring Boot 项目根目录放 `.trae/mcp.json`；Cursor：写进全局 `~/.cursor/mcp.json`。

```json
{
  "mcpServers": {
    "contextgate": {
      "command": "python",
      "args": ["<本仓库绝对路径>/mcp-server/mcp_server.py"],
      "env": {
        "CONTEXTGATE_PROJECT": "<你的 Spring Boot 项目根目录>",
        "CONTEXTGATE_MAP": "<分析产出的 framework_map.json 绝对路径>"
      }
    }
  }
}
```

> Windows 下 `command` 填你的 python.exe 完整路径更稳。不配置 env 也能跑：server 默认用仓库自带的 demo 地图（`examples/demo-framework-map.json`），零配置即可体验。

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
- **MyBatis-Plus 内置方法给的是实体级上界**：`selectById` 标"触碰全部列"是安全的过近似（宁多报不漏报），不区分业务实际读了哪几列
- **Wrapper / JdbcTemplate 是语句级识别**：Wrapper 拆成变量后跨语句链式调用（`var w = new LambdaQueryWrapper<>(); w.eq(...)`）只识别构造语句；JdbcTemplate 的 SQL 常量抽成类级 `static final` 字段目前不追踪（方法内局部 `String sql = ...` 支持）
- **XML 复杂结构未覆盖**：`<association>`/`<collection>` 嵌套映射、`<foreach>` 批量、resultMap `extends` 继承目前不解析（demo 夹具覆盖了 resultMap/sql/include/set/if 这些主流写法）
- 目前一份地图对应一个项目；多项目切换靠 env 配置

## 参与进来

这个工具的每条解析规则几乎都是被真实项目"逼"出来的：全限定类型字段漏解析、裸 `SELECT *` 不算触碰列、别名星号 `o.*`、跨表 JOIN 列归属、XML `<include>`……规则覆盖率随真实项目增长，**你的项目就是最好的测试用例**。

三种参与方式，按难度排序：

1. **拿你的项目跑一把，报漏报**（最有价值）：`python analyzer/framework_map.py <你的项目>`，对照 `framework_map.md` 找"这条链路/这个字段明明用了却没出现"的地方，提 issue 附一小段 Java/XML 源码即可。
2. **补解析规则**：已知排队中的规则——Wrapper 跨语句链式调用与 `.select()` 子查询、类级 SQL 常量、XML `<association>`/`<collection>`/`<foreach>`/resultMap `extends`、多模块 Maven 路径。方法见 [CONTRIBUTING.md](CONTRIBUTING.md)，流程是"demo 夹具 + 断言 + 全绿"。
3. **适配更多 AI 工具 / 语言**：MCP 是标准协议，接入新工具基本零成本；分析器目前只覆盖 Java 。

