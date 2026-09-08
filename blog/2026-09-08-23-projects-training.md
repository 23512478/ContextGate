我做了个工具叫 [ContextGate](https://github.com/23512478/ContextGate)——把 Spring Boot + MyBatis 的框架约定（路由、注入、事务、SQL、实体映射）离线预编译成一张代码地图，通过 MCP 喂给 AI 编程工具（Trae/Cursor），让 AI 改代码前查地图而不是全文 grep。

第一版所有解析规则都是我的几个项目出来的。用着很爽，但有一个事实：**一个项目只能覆盖一个项目的写法**。换个项目大概率会漏。

两个开源项目增加"训练"：

| 项目                                         | 规模              | 技术栈                           |
| ------------------------------------------ | --------------- | ----------------------------- |
| [mall](https://github.com/macrozheng/mall) | 519 文件 / 246 路由 | Spring Boot + 原生 MyBatis（多模块） |
| [vhr](https://github.com/lenve/vhr)        | 87 文件 / 50 路由   | Spring Boot + 原生 MyBatis      |

跑一遍分析器，果然，漏报一大片。

## 修了 5 个 bug（每个都是真实项目补充的）

### Bug 1：原生 MyBatis 的实体识别不到

**现象**：mall 和 vhr 的实体全是裸 POJO，没有 `@TableName` 注解，放在 `model` 包里。分析器只认 `@TableName`，结果实体数 = 0。

**修复**：加兜底逻辑——`model`/`domain`/`entity` 包下的普通类自动视为实体，表名由类名驼峰转下划线推断（`UmsAdmin` → `ums_admin`）。排除明显不是实体的（`Example`/`Criteria`/`VO`/`DTO` 后缀）。

**结果**：mall 实体 0 → 96，vhr 27 个。

### Bug 2：接口方法上的 `@Transactional` 被忽略

**现象**：mall 把 `@Transactional` 标在 Service **接口**方法上（不是 impl）。分析器的事务闭包逻辑跳过了 interface，结果事务数 = 0。

**修复**：`tx_closure` 不再跳过 interface。收集接口方法的 `@Transactional`，通过 `impl_of` 映射找到实现类，把 impl 的同名方法标记为事务种子。

**结果**：mall 事务 0 → 24 种子（82 闭包），vhr 2 → 6。

### Bug 3：多模块 Maven 只扫一个模块

**现象**：mall 有 7 个子模块（mall-admin、mall-mbg、mall-portal...），实体在 mall-mbg、服务在 mall-admin。分析器只扫 `<root>/src/main/java`，跨模块互相看不见。

**修复**：自动扫描 ROOT 下所有 `src/main/java` 和 `src/main/resources` 目录。

**结果**：mall 从 153 文件 → 519 文件，实体和路由都全了。

### Bug 4：XML mapper 只认 `resources/mapper` 目录

**现象**：vhr 把 XML 和 Java Mapper 接口放在同一目录（`src/main/java/.../mapper/*.xml`），mall 放在 `resources/com/macro/mall/mapper/`。分析器只扫 `resources/mapper/`，结果 0 条 XML SQL。

**修复**：扫 `src/main/resources` 和 `src/main/java` 下所有 `.xml` 文件（MyBatis 两种布局都支持）。

**结果**：vhr Mapper SQL 0 → 163/164，mall 856/856。

### Bug 5：包私有字段注入识别不到

**现象**：vhr 的 `@Autowired DepartmentMapper departmentMapper;` 没写 `private`（包私有）。`FIELD_RE` 正则强制要求访问修饰符，字段检测不到，调用链断在 Service 层。

**修复**：`FIELD_RE` 加一个无修饰符的分支（包私有），分组兼容。

**结果**：vhr 逆向索引 0 → 54 个 Mapper 方法有调用者。

## 修完之后

所有修复都加了 demo 夹具 + 回归断言，全量测试通过。然后打了 **v0.1.0** tag，发了 release。

现在分析器在 mall 上的覆盖：

-   519 文件 / 246 路由 / 96 实体 / 182 事务方法
-   856 个 Mapper 方法中 856 个有 SQL
-   调用链从路由一路追到 SQL

## 5 个不够：再拉 20 个项目，三轮练兵

v0.1.0 的诚实清单里躺着：MBG `Example` 动态条件、Wrapper 拆变量跨语句、`static final` SQL 常量、XML `<association>`/`<collection>`/`<foreach>`/resultMap `extends`……一个都还没做。还是老办法：批量拉项目、盯异常信号、修、沉淀回归。这次分三轮，每轮 5 个：

### 第一轮（ruoyi-vue-pro / JeecgBoot / jpetstore-6 / renren-fast / mall 复测）：撞名与自研扩展

- **MapStruct 撞名（最隐蔽）**：ruoyi-vue-pro 报出 2058 个"无 SQL 的 Mapper 方法"。一查全是 `*Convert` 转换器接口——MapStruct 的 `@Mapper` 和 MyBatis 的 `@Mapper` 是两个世界的东西，按 import 归属区分（`org.mapstruct.Mapper` vs `org.apache.ibatis.annotations.Mapper`）。
- **X 后缀 Wrapper**：yudao 系全部使用自研 `LambdaQueryWrapperX` / `QueryWrapperX`，规则表里没有它们。
- **字段值便捷方法**：`selectOne(Entity::getField, value)` 这种 BaseMapperPlus 风格，ruoyi-vue-pro 仓库 500+ 处。现在能合成 `WHERE field = ?`。
- 效果：ruoyi-vue-pro 内嵌 SQL 识别 **178 → 1631 条**。

### 第二轮（snowy / dax-pay / xmall / xzs / favorites-web）：ServiceImpl 继承式调用全盲

- **影响面最大的一课**：snowy 的服务层 `extends ServiceImpl<SysUserMapper, SysUser>`，整层不注入 mapper 字段，查询全走 `this.list()` / `remove()` / `getById()` 这些**继承方法**。调用图对这条通道完全失明——snowy 的逆向索引只有 4 条。现在 17 个继承方法映射到泛型 M 的 baseMapper 内置方法：**snowy 逆向索引 4 → 200，事务闭包 339 → 480**。
- **Manager 层模式**：dax-pay 自研 `BaseManager<M, T>`（和 ServiceImpl 同构）+ `this.findByField(Entity::getField, value)`，规则同步泛化：**dax-pay 内嵌 2 → 52**。
- 顺带确认：favorites-web 是 JPA 项目（无 MyBatis），逆向索引 0 是**正确行为**——工具不装懂。

### 第三轮（pig / yudao-cloud / OneBlog / renren-security / newbee-mall-cloud）：验证轮，零新增

规则全部经受住跨仓库验证。pig 的 5 处 `<association select=...>` N+1 懒加载子查询链接正确产出；yudao-cloud（与 ruoyi-vue-pro 同源不同仓库）识别 1628 条 Wrapper 记录，helper 归并、X-Wrapper、字段值三条规则跨仓库一致复现。残缺仅 2 个声明无实现的死代码方法（OneBlog / xzs），非分析器问题。

**同场加映（v0.2 一批）**：JdbcTemplate 的 `SELECT COUNT(*)` 在 `selectCount`/`exists`/`countByExample` 上不再虚报全列（COUNT 不碰业务列，标 0）；XML 逗号清理曾经把 `id, order_id` 吃成 `id order_id`（`order` 前缀被误当 ORDER 关键字）；`@MapperScan` 注解和 javadoc 里提到 `@Mapper` 会把**启动类**误判成 Mapper——注解名改从去注释文本抽取。多项目模式上线（`CODECONTEXT_MAPS_DIR` + `project` 参数 + `list_maps`），一个 server 管多个项目。

## 最后一块：跨方法/跨类数据流

练兵后最硬的三条边界其实是同一个问题——**一条查询用的条件，不是在消费它的那条语句里拼出来的**。拼装发生在 helper 方法里、别的类里、调用方手里。静态分析要把这条数据流在方法之间、类之间接回去。

- **跨类 helper + 套 helper**：全局 helper 注册表，接收者按**字段类型**解析（`orderQuerySupport.buildBase` 里的 `orderQuerySupport` 是字段名不是类名——这个坑 debug 了半天）；helper 里再调 helper 时方法体递归展开，防循环。
- **调用方拼的条件（参数传播）**：消费方法的签名带 Wrapper 参数、条件由调用方拼——两阶段 + 不动点收敛，传播版落地后自动剔除"缺调用方信息"的降级版记录。RuoYi-Vue-Plus 里大量 `selectDeptList(Wrapper<SysDept>)` 用的是 MP **基类** `Wrapper<T>`，补上基类后**真缺失 71 → 22**。

```sql
-- 调用方拼 status，目标方法内 gt id，恰好一条完整记录
SELECT * FROM orders WHERE status = ? AND id = ?
```

- **Example criteria 分组语义**：`createCriteria()` 开 AND 组、`or()` 开 OR 组，多组带括号——旧版按出现顺序平铺，**求值语义是错的**（AND 优先级高于 OR），这种"看起来能解析、其实在骗人"的结果比漏报更危险。这里真实项目当场教做人：分组逻辑重构后 litemall 的 Example 从 123 条掉到 28——它的风格是 `example.or().andUserIdEqualTo(uid)` 直接开**匿名组**，我只接了"先有 criteria 变量"的形式。补上匿名组，123 全部回来。
- **跨类常量互拼**：`SQL_A = "..." + SqlParts.OPENID_WHERE`，token 支持点号限定名 + 全局不动点折叠。

## 23 个项目的总账（全部用最新分析器重跑）

| 项目 | 文件 | 路由 | 实体 | Mapper 方法 | 有 SQL | 内嵌 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ruoyi-vue-pro | 6,355 | 3,009 | 540 | 3,673 | 2,135 | 1,631 |
| yudao-cloud | 6,852 | 2,999 | 538 | 3,660 | 2,123 | 1,628 |
| dax-pay | 2,946 | 1,315 | 173 | 31 | 29 | 52 |
| JeecgBoot | 984 | 968 | 98 | 468 | 467 | 262 |
| snowy | 845 | 431 | 47 | 200 | 197 | 344 |
| mall | 524 | 246 | 96 | 856 | 856 | 114 |
| 其余 16 个 | 4,641 | 1,873 | 555 | 2,733 | 3,251 | 244 |
| **合计 23 项** | **22,147** | **10,736** | **1,887** | **10,921** | **7,773** | **4,275** |

内嵌 4,275 条 = MBG Example 271 + Wrapper 链 4,004。零回归：mall 856/856、vhr 163/163、litemall Example 123/123、xmall 34/34 全部无缺失。（“内嵌”指 SQL 不写在注解/XML 里、由 Wrapper 链/Example 在 Java 代码里长出来的那部分；ruoyi-vue-pro/dax-pay 的"有 SQL"差异是 default 方法委托链的死代码与方法体内联写法，属已知边界。favorites-web 是 JPA 项目不计 Mapper。）

demo 夹具 25 个 Java 文件 / 29 条路由，回归断言 **75 项**。

## 还有什么没覆盖（诚实清单）

-   多跳传播链：调用方拼好传 A、A 再传 B——超过一跳不追（一跳已覆盖，且是真实项目的主流形态）
-   运行期拼参（`"..." + variable`）静态拿不到，硬解必然误报
-   正则级解析，内部类/Lombok 可能漏
-   澄清一条：`selectById` 标"触碰全部列"不是过近似，是语义事实——MP 底层就是取整行，改任何列的类型都会炸行映射。count 族则标 0 列

## 招募：你的项目就是最好的测试用例

说实话，现在的规则是 23 个项目喂出来的。第 24 个项目大概率还会撞上新的拼装姿势——这恰恰是最需要你的地方。等 100 个、1000 个项目喂进去，我们共同开发的这个项目一定能成为每个还写 Spring Boot 和 MyBatis 的必备！！

三档参与方式：

**1. 拿你的项目跑一把，报漏报（最有价值，5 分钟）**

```bash
python analyzer/framework_map.py <你的SpringBoot项目>
```

打开生成的 `framework_map.md`，找"明明用了却没识别"的地方，提个 issue 附小段源码就行。

**2. 补解析规则**：已知排队中的见上。[CONTRIBUTING.md](https://github.com/23512478/ContextGate/blob/main/CONTRIBUTING.md) 写了完整流程——demo 夹具 + 断言 + 全绿。

**3. 适配新工具/语言方向**：MCP 协议，接 Claude Code / Cline 零配置。

## 快速体验

```bash
pip install "mcp<2"
git clone https://github.com/23512478/ContextGate
cd ContextGate
python mcp-server/test_mcp.py   # 零配置，自动分析内置 demo，75 项断言
```

**项目地址**：<https://github.com/23512478/ContextGate> ⭐

如果你也天天用 AI 写 Spring Boot，受够了它 grep 半天还漏链路，欢迎来玩。报漏报就是最大的贡献。
