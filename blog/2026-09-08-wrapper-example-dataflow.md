# 把 Wrapper 的拼装现场挖出来：ContextGate 补上跨方法/跨类数据流

我做了个工具叫 [ContextGate](https://github.com/23512478/ContextGate)——把 Spring Boot + MyBatis 的框架约定（路由、注入、事务、SQL、实体映射）离线预编译成一张代码地图，通过 MCP 喂给 AI 编程工具（Trae / Cursor / Claude Code），让 AI 改代码前查地图而不是全文 grep。

上一篇文章（20 个真实项目练兵）结束时，诚实清单里还躺着三条最硬的边界。这次把它们全啃了——写完才发现，三条其实是**同一类问题：跨方法/跨类的数据流**。

回顾一下当时剩的三条：

> - Wrapper 跨语句只支持同类内直链；跨类传递、helper 套 helper、调用方在方法外拼的条件不追
> - SQL 常量支持同类互拼折叠；跨类互拼静态拿不到
> - MBG Example：AND/OR 按出现顺序平铺（criteria 分组语义不还原），Example 作方法参数传入不追

看上去是三个功能点。本质是同一个问题：**一条查询用的条件和语句，不是在消费它的那条语句里拼出来的**。拼装发生在别的方法里（helper）、别的类里（跨类 builder）、调用方手里（参数传进来），或者是常量的另一段（跨类互拼）。静态分析要在没有运行时信息的前提下，把这条数据流在方法之间、类之间接回去——教科书上叫 def-use 链 + 不动点传播。

## 修了 4 组（每个都是真实写法逼出来的）

### 组 1：跨类 helper + helper 套 helper

**现象**：ruoyi-vue-pro 的服务层长这样——

```java
LambdaQueryWrapper<SysDept> lqw = buildQueryWrapper(dept);   // 本类 helper
```

更狠的是 RuoYi-Vue-Plus：helper 是**另一个类**的方法，helper 里面还会再调别的 helper。v1 只支持"本类内直链"，helper 之外的链文本一律不追，条件丢一片。

**修复**：预扫全部类，建全局 helper 注册表，键是 `(类名, 方法名)`。三个细节：

- 接收者按**字段类型**解析：`orderQuerySupport.buildBase(...)` 里的 `orderQuerySupport` 是字段名不是类名，得先映射到 `OrderQuerySupport` 再查表（这个坑 debug 了我半天——直接拿字段名当类名查，永远查不到）
- helper 套 helper：方法体里再调 helper 时，被调者的方法体文本递归展开拼进来，frozenset 防循环引用，结果缓存
- helper 查找分两路：`buildXxx(...)` 查本类，`other.buildXxx(...)` 查全局表

**结果**（demo 验证）：

```sql
-- searchByHelper 消费，条件一半来自跨类 helper OrderQuerySupport#buildBase(status)
-- 一半来自本类 helper 自己的 like
SELECT * FROM orders WHERE status = ? AND title = ?
```

跨类 helper 的 status 之前是直接丢的。

### 组 2：调用方在方法外拼的条件（参数传播）

**现象**：消费方法的签名带 Wrapper 参数，条件由**调用方**拼——

```java
// 调用方
LambdaQueryWrapper<Order> w = new LambdaQueryWrapper<>();
w.eq(Order::getStatus, status);           // 条件在这里拼
return orderQuerySupport.searchByWrapper(w);   // 消费在另一个类
```

v1 只能解析目标方法体内的条件（`w.gt(Order::getId, 0L)`），调用方的 status 全丢——而且会生成一条**缺条件的不完整记录**，比没有更误导。

**修复**：`scan_inline_sql` 改成两阶段——

- 主扫阶段：消费语句命中的接收方法是「带 Wrapper 参数**且有方法体**」的目标时，不消费、改传播：把调用方攒的链文本作为种子记下来
- 传播轮：不动点收敛。把种子播种到目标方法参数的链头，重跑一遍 def-use；传播出去的记录再传播，直到没有新的
- 去重：参数变量在目标方法内的"本地消费记录"是没有调用方信息的降级版，传播版落地后自动剔除，否则同一个方法出两条

**结果**：恰好一条完整记录——

```sql
SELECT * FROM orders WHERE status = ? AND id = ?
-- status = 调用方拼的，id = 目标方法内的 gt
```

真实项目立刻回礼：RuoYi-Vue-Plus 大量 `default List<SysDeptVo> selectDeptList(Wrapper<SysDept> queryWrapper)`——参数类型是 MP **基类** `Wrapper<T>`，不在四个具体 Wrapper 名单里，参数正则补上基类后，它的真缺失 71 → 22。

### 组 3：Example 的分组语义 + 参数传播

**现象**：MBG Example 的 `createCriteria()` / `example.or()` 是**分组**语义：AND 组、OR 组，组间 OR 连接。v1 按出现顺序平铺，生成 `nickname = ? OR create_time > ? AND deleted = false` 这种——由于 AND 优先级高于 OR，**平铺结果的求值语义是错的**，和 MySQL 实际执行不一致。这种"看起来能解析、其实在骗人"的结果比漏报更危险。

**修复**：

- 分组解析：`createCriteria()` 开 AND 组，`or()` 开 OR 组；多组相遇时每组加括号；组间按连接词连接
- Parameter 传播：Example 作参数传给其他方法时，调用方的条件语句作为种子拼给目标方法——识别按**参数类型**（方法是 `UserExample ex` 参数就当 Example 消费者），不看方法名

**这里踩了两个坑，真实项目当场教做人**：

1. 分组逻辑重构后跑 20 项目回归，litemall 的 Example 从 123 条掉到 28。挖了一小时：litemall 的风格是 `example.or().andUserIdEqualTo(uid).andDeletedEqualTo(false)`——`or()` 直接开**匿名组**、不带 criteria 变量，我的分组逻辑只接"先有变量 = example.createCriteria()"的形式。给每种写法留的位置永远比真实写法少一种。补上匿名组分支，123 全部回来。
2. Example 参数传播第一版写死了 5 个标准消费动词（`selectByExample` 等），demo 里目标方法叫自定义名 `searchByExample`，检测循环零命中。正则永远匹配不上它不认识的词——改成按"Example 变量出现在实参里"识别，方法名不限。

### 组 4：跨类 SQL 常量互拼

**现象**：

```java
// StatsService 里，引用 SqlParts 类的公共片段——跨类互拼
private static final String SQL = "SELECT id, nickname FROM users" + SqlParts.OPENID_WHERE;
```

v1 折同类常量没问题，跨类只支持单常量引用（`Foo.SQL_X` 直接用），互拼丢。

**修复**：token 化时支持点号限定名（`SqlParts.OPENID_WHERE` 是一个 id，不是断点）；本类折不出来的挂到类身上，类收集完在主流程做**全局不动点折叠**——跨类引用按类型名直查，直到没有新折出来的为止。

**结果**：跨类互拼的常量完整折叠成一条 SQL。

## 途中踩的非数据流坑

demo 夹具膨胀到 29 条路由后，`GET /orders/search` 的子串匹配同时命中 `/orders/search-alias|flexible|helper|param|support` 一族 6 条，直接进"请精确输入"消歧。修成**精确路径优先**：查询串与路由全等时直接命中，前缀/子串只做模糊兜底。这个 bug 在路由少的 demo 里永远暴露不出来——又是"写法比你想的多"系列。

## 修完之后

20 个项目全量重跑（统一最新口径），对照：

| 项目 | 之前 | 现在 | 说明 |
| --- | --- | --- | --- |
| litemall | 123 | **123** | 分组重构 litemall 无回归（一度掉 28，匿名组补上恢复） |
| mall / xmall | 114 / 34 | **114 / 34** | Example 分组语义无回归 |
| JeecgBoot | 254 | **262** | 数据流新规则的顺带增益（+8） |
| pig | 25 | **26** | 同上（+1） |
| RuoYi-Vue-Plus | 46 | **51** | `Wrapper<T>` 基类参数对接（真缺失 71 → 22） |
| ruoyi-vue-pro / yudao-cloud | 1631 / 1628 | **持平** | 最大靶场，无重复无误报 |

合计：内嵌 SQL 可反查记录 **4,275 条**（MBG Example 271 + Wrapper 链 4,004），XML 懒加载 N+1 链接 5 处。（内嵌的定义：SQL 不写在注解/XML 里、由 Wrapper 链/Example/常量在 Java 代码里长出来的那部分。）

demo 夹具 25 个 Java 文件 / 29 条路由，回归断言 **75 项**，clone 下来 `python mcp-server/test_mcp.py` 一条命令全部复现。

## 还有什么没覆盖（诚实清单）

- **多跳传播链**：调用方拼好传 A、A 再传 B——超过一跳不追（一跳已覆盖，且一跳是真实项目的主流形态）
- **运行期拼参**：`"..." + variable` 静态分析的根本边界，硬解必然误报
- **正则级解析**：内部类、Lombok 生成方法可能漏
- 澄清一条：`selectById` 标"触碰全部列"不是过近似，是语义事实——MP 底层就是取整行，改任何列的类型都会炸行映射。count 族（`selectCount`/`exists`/`countByExample`）则标 0 列，COUNT 不碰业务列

## 招募：你的项目就是最好的测试用例

说实话，这三组规则是 20 个项目喂出来的。第 21 个项目大概率还会撞上新的拼装姿势——这恰恰是最需要你的地方。等 100 个、1000 个项目喂进去，这个共同开发的项目一定能成为每个还写 Spring Boot 和 MyBatis 的必备！！

三档参与方式：

**1. 拿你的项目跑一把，报漏报（最有价值，5 分钟）**

```bash
python analyzer/framework_map.py <你的SpringBoot项目>
```

打开生成的 `framework_map.md`，找"明明用了却没识别"的地方，提个 issue 附小段源码就行。

**2. 补解析规则**：排队中的见上（多跳传播链、内部类、Lombok）。[CONTRIBUTING.md](https://github.com/23512478/ContextGate/blob/main/CONTRIBUTING.md) 写了完整流程——demo 夹具 + 断言 + 全绿。

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
