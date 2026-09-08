上一篇（[mall / vhr 练出的 5 个 bug](https://github.com/23512478/ContextGate)）发出去的时候，我心里清楚一件事：**那 5 个修完，只代表两个项目的写法被覆盖了**。诚实清单里还躺着——MBG `Example` 动态条件、Wrapper 拆变量跨语句、`static final` SQL 常量、XML `<association>`/`<collection>`/`<foreach>`、resultMap `extends`……一条都没做。

所以这次没有新功能发布，没有大版本，做了一件笨事：**又拉了 20 个真实开源项目，分三轮灌进分析器，把"诚实清单"一条一条划掉**。每轮的流程完全一样：跑分析器 → 盯异常信号（计数为 0、缺失暴涨、实体数离谱）→ 顺藤摸瓜找根因 → 修 → demo 夹具 + 断言沉淀回归。

这篇文章就是三轮的全记录：发现了什么、修了什么、长出了什么规则。数字都在，欢迎对着仓库复现。

## 第一轮：ruoyi-vue-pro / JeecgBoot / jpetstore-6 / renren-fast

第一轮撞上的全是"撞名"和"自研扩展"——闭门写规则时根本想不到的写法。

- **MapStruct 的 `@Mapper` 和 MyBatis 的 `@Mapper` 是两个世界**。ruoyi-vue-pro 一上来报出 2058 个"无 SQL 的 Mapper 方法"，异常信号一查：全是 MapStruct 的 `*Convert` 转换器接口，注解同名不同包。按 import 归属区分（`org.mapstruct.Mapper` vs `org.apache.ibatis.annotations.Mapper`），`extends BaseMapper` 的除外（转换器不会继承它）。
- **yudao 系全部使用自研的 `LambdaQueryWrapperX` / `QueryWrapperX`**——X 后缀扩展类，规则表里没有它们，等于对这类项目 blind。
- **`selectOne(Entity::getField, value)` 这种字段值便捷方法**（BaseMapperPlus 风格），ruoyi-vue-pro 仓库 500+ 处，全部没有合成 `WHERE`。

修完这一轮：ruoyi-vue-pro 的内嵌 SQL 识别从 178 条涨到 **1631 条**，"无 SQL 的 Mapper 方法"覆盖率 85%。

## 第二轮：snowy / dax-pay / xmall / xzs / favorites-web

第二轮教的是"继承式调用"——影响面最大的一课。

- snowy 的服务层 `extends ServiceImpl<SysUserMapper, SysUser>`，**整层不注入 mapper 字段**，查询全走 `this.list()` / `remove()` / `getById()` 这些继承方法。调用图对这条通道完全失明——snowy 的逆向索引只有 4 条。修法：17 个 ServiceImpl 继承方法映射到泛型 M 的 baseMapper 内置方法。结果：**snowy 逆向索引 4 → 200，事务闭包 339 → 480**。
- dax-pay 更进一步：自研 `BaseManager<M, T>`（和 ServiceImpl 同构），配套 `this.findByField(Entity::getField, value)`。基类正则和字段值规则同步泛化，**dax-pay 内嵌 2 → 52**。
- favorites-web 逆向索引 0 是**正确行为**——它是 JPA 项目，没有 MyBatis。工具不装懂，这比硬编个数字出来重要。

## 第三轮：pig / yudao-cloud / OneBlog / renren-security / newbee-mall-cloud

第三轮是验证轮：**零新增缺陷**。前两轮的规则全部经受住跨仓库验证——pig 的 5 处 `<association select=...>` N+1 懒加载子查询链接正确产出；yudao-cloud（与 ruoyi-vue-pro 同源但独立仓库）识别 1628 条 Wrapper 记录，helper 归并、X-Wrapper、字段值三条规则跨仓库一致复现。残缺仅 2 个声明无实现的死代码方法（OneBlog / xzs），非分析器问题。

**同场加映（v0.2 一批）**：`selectCount`/`exists`/`countByExample` 不再虚报全列（COUNT 不碰业务列）；XML 逗号清理曾经把 `id, order_id` 吃成 `id order_id`（`order` 前缀被误当 ORDER 关键字，这个 bug 在旧夹具上永远暴露不出来）；`@MapperScan` 注解和 javadoc 里提到 `@Mapper` 会把**启动类**误判成 Mapper。多项目模式上线（`CODECONTEXT_MAPS_DIR` + `project` 参数 + `list_maps`），一个 server 管多个项目。

## 最后一块：跨方法/跨类数据流

三轮练完，诚实清单里剩的三条最硬的边界其实是同一个问题——**一条查询用的条件，不是在消费它的那条语句里拼出来的**。拼装发生在 helper 方法里、别的类里、调用方手里，或者是常量的另一段。静态分析要把这条数据流在方法之间、类之间接回去：def-use 链 + 不动点传播。

- **全局 helper 注册表**：跨类 helper（`lqw = Other.buildXxx(...)`）与 helper 套 helper（方法体递归展开，防循环）。一个坑 debug 了半天：`orderQuerySupport.buildBase(...)` 里的 `orderQuerySupport` 是**字段名**不是类名，直接拿去查注册表永远查不到——得先映射到类型名。
- **参数传播**：消费方法的签名带 Wrapper 参数、条件由调用方拼（条件在这里拼，消费在另一个类）。两阶段 + 不动点收敛，传播版落地后自动剔除"缺调用方信息"的降级版记录。RuoYi-Vue-Plus 大量 `selectDeptList(Wrapper<SysDept>)` 用的是 MP **基类** `Wrapper<T>`，都不在四个具体子类名单里——补上基类后**真缺失 71 → 22**。
```sql
-- 调用方拼 status，目标方法内 gt id，恰好一条完整记录
SELECT * FROM orders WHERE status = ? AND id = ?
```
- **Example criteria 分组语义**：`createCriteria()` 开 AND 组、`or()` 开 OR 组，多组带括号。旧版按出现顺序平铺——由于 AND 优先级高于 OR，**平铺结果的求值语义是错的**，这种"看起来能解析、其实在骗人"的结果比漏报更危险。这里真实项目当场教做人：分组逻辑重构后跑回归，litemall 的 Example 从 123 条掉到 28——它的风格是 `example.or().andUserIdEqualTo(uid)` 直接开**匿名组**，我只接了"先有 criteria 变量"的形式。给每种写法留的位置永远比真实写法少一种。补上匿名组，123 全部回来。
- **跨类常量互拼**：`SQL_A = "..." + SqlParts.OPENID_WHERE`，token 支持点号限定名 + 全局不动点折叠。

## 23 个项目的总账

全部用最新分析器重跑的统一口径（含上一篇的 mall / vhr——它们也复测了，零回归）：

| 项目 | 文件 | 路由 | 实体 | Mapper 方法 | 有 SQL | 内嵌 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ruoyi-vue-pro | 6,355 | 3,009 | 540 | 3,673 | 2,135 | 1,631 |
| yudao-cloud | 6,852 | 2,999 | 538 | 3,660 | 2,123 | 1,628 |
| dax-pay | 2,946 | 1,315 | 173 | 31 | 29 | 52 |
| JeecgBoot | 984 | 968 | 98 | 468 | 467 | 262 |
| snowy | 845 | 431 | 47 | 200 | 197 | 344 |
| 其余 17 个 | 4,165 | 2,014 | 491 | 2,889 | 2,822 | 358 |
| **合计 23 项** | **22,147** | **10,736** | **1,887** | **10,921** | **7,773** | **4,275** |

内嵌 4,275 = MBG Example 271 + Wrapper 链 4,004（"内嵌"指 SQL 不写在注解/XML 里、由 Wrapper 链 / Example 在 Java 代码里长出来的那部分）。关键项全部零回归：mall 856/856、vhr 163/163、litemall Example 123/123、xmall 34/34。demo 夹具 25 个 Java 文件 / 29 条路由，回归断言 **75 项**——clone 下来一条命令全部复现。

## 还有什么没覆盖（诚实清单）

- 传播边界：Wrapper 条件沿调用链不动点收敛，**多跳、跨类可追**（实测 Controller → Service A → Service B → Mapper 三跳条件不丢）；前提是每跳目标方法有方法体、接收者类型可解析（注入字段/类名），接收者解析不出类型的调用（链式返回值 `getService().x(w)`、方法内 `new` 的对象）不追；Example 参数传播追一跳
- 运行期拼参（`"..." + variable`）静态拿不到，硬解必然误报
- 正则级解析，内部类 / Lombok 可能漏
- 澄清一条：`selectById` 标"触碰全部列"不是过近似，是语义事实——MP 底层就是取整行，改任何列的类型都会炸行映射。count 族则标 0 列

## 招募：你的项目就是最好的测试用例

现在这 23 个项目喂出来的规则，第 24 个项目大概率还会撞上新的拼装姿势——这恰恰是最需要你的地方。等 100 个、1000 个项目喂进去，我们共同开发的这个项目一定能成为每个还写 Spring Boot 和 MyBatis 的必备！！

三档参与方式：

**1. 拿你的项目跑一把，报漏报（最有价值，5 分钟）**

```bash
python analyzer/framework_map.py <你的SpringBoot项目>
```

打开生成的 `framework_map.md`，找"明明用了却没识别"的地方，提个 issue 附小段源码就行。

**2. 补解析规则**：排队中的见上。[CONTRIBUTING.md](https://github.com/23512478/ContextGate/blob/main/CONTRIBUTING.md) 写了完整流程——demo 夹具 + 断言 + 全绿。

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
