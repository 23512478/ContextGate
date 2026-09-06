# ContextGate

> 给 Spring Boot + MyBatis(-Plus) 项目做一份「框架感知代码地图」，再通过 MCP 协议喂给 AI 编程工具（Trae / Cursor / Claude Code 等）。

AI 编程工具改后端代码时，通常靠全文搜索去猜"这个接口调了谁、这条 SQL 碰了哪些表、改这个字段会炸哪条链路"——费 token、还容易幻觉。ContextGate 的思路是**离线预编译框架约定**：把 Spring 的隐式约定（路由注解、依赖注入、事务边界）和 MyBatis 的映射关系（Mapper → SQL → 表/列 → 实体）静态解析成结构化地图，AI 只需要调一个工具就能拿到压缩后的调用链和影响面。

## 它能做什么

- **调用链追踪**：`POST /orders/my` → Controller → Service → Mapper → SQL 全文，含 `@Transactional` 事务边界标记
- **SQL 反查**：按 Mapper 方法名 / 表名 / 列名片段搜 SQL，给出 SQL 全文、涉及表、触碰列、上游调用者和路由
- **变更影响面**：改实体/字段前查出波及的自定义 SQL、MyBatis-Plus 内置 CRUD 调用点（`selectById`=SELECT * 全列触碰）、上游路由
- **一键刷新**：代码改完让 AI 调 `refresh_map`，秒级重跑分析器

已覆盖的解析规则：路由注解（`@GetMapping` 等）、`@Autowired` 注入、`@Transactional` 闭包传播、`@Select/@Update/...` 注解 SQL、`@TableName/@TableField` 实体映射、MyBatis-Plus `BaseMapper` 内置方法、全限定类型字段（`java.math.BigDecimal`）、裸 `SELECT *` 与别名星号 `o.*` 展开、跨表 JOIN 列归属；XML mapper（`<resultMap>`/`<sql>`/`<include>`）解析脚手架已就位。

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
- **不解析 JdbcTemplate 裸 SQL、MyBatis-Plus Wrapper（`lambdaQuery().eq(...)`）动态拼接**
- **XML mapper 解析脚手架尚未在真实 XML 项目上检验**
- 目前一份地图对应一个项目；多项目切换靠 env 配置

## 贡献

欢迎一起补解析规则——这个工具的每条规则几乎都是被真实项目"逼"出来的（全限定类型字段、`SELECT *`、别名星号、跨表 JOIN……）。加规则的方法见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MIT
