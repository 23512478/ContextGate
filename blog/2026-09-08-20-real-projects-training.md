# 用 20 个真实开源项目"练兵"：ContextGate 修了 6 个 bug，长出 10 条新规则

> ContextGate（[github.com/23512478/ContextGate](https://github.com/23512478/ContextGate)）是一个给 Spring Boot + MyBatis(-Plus) 项目做「框架感知代码地图」的工具：离线静态解析出路由表、调用链、SQL 触碰列、事务边界，再通过 MCP 协议喂给 AI 编程工具，让 AI 不用全文搜索去猜"这个接口调了谁、改这个字段会炸哪"。
>
> 这篇文章记录我们把 20 个真实开源项目灌进分析器做三轮"练兵"的全过程：发现了什么、修了什么、长出了什么规则，以及接下来想招募什么样的协作者。

## 为什么要用真实项目训练

工具里的每条解析规则，本质上都是某种"民间写法"的编码。注解 SQL、XML mapper、`LambdaQueryWrapper` 链这些东西，每 popular 一个框架分支，就会出现新的民间写法：yudao 给 Wrapper 加 X 后缀，dax-pay 把数据层叫 Manager，snowy 的服务层根本不注入 mapper 字段……闭门造车写出来的规则，遇到真实代码库就是灾难。

所以我们定了个笨办法：**批量拉真实项目 → 跑分析器 → 盯着异常信号（计数为 0、缺失暴涨、实体数离谱）→ 顺藤摸瓜找根因 → 修掉 → demo 夹具 + 断言沉淀成回归**。三轮下来，共灌入 20 个项目、20,708 个类、10,686 条路由，分析器从没崩过一次（线性扫描器立功），但抓出了 6 个真 bug。

## 三轮训练都发现了什么

### 第一轮：mall / ruoyi-vue-pro / JeecgBoot / jpetstore-6 / renren-fast

- **MapStruct 撞名误判（最隐蔽的一个）**：ruoyi-vue-pro 报出 2058 个"无 SQL 的 Mapper 方法"，异常信号一查——全是 `*Convert` 转换器接口。MapStruct 的 `@Mapper` 和 MyBatis 的 `@Mapper` 是两个世界的东西，我们按 import 归属（`org.mapstruct.Mapper` vs `org.apache.ibatis.annotations.Mapper`）做了区分。
- **X 后缀 Wrapper**：yudao 系项目全部使用自研的 `LambdaQueryWrapperX` / `QueryWrapperX`，规则表里没有它们，等于对这类项目 blind。已加入识别与 def-use。
- **字段值便捷方法**：`selectOne(Entity::getField, value)` 这种 BaseMapperPlus 风格的 default 方法，仓库实测 500+ 处，现在能合成 `WHERE field = ?` 并算出触碰列。
- 效果：ruoyi-vue-pro 内嵌 SQL 识别从 178 条涨到 **1631 条**，无 SQL 方法覆盖率 85%。

### 第二轮：snowy / xmall / favorites-web / xzs / dax-pay

- **ServiceImpl 继承式调用全盲（影响面最大）**：snowy 的服务类 `extends ServiceImpl<SysUserMapper, SysUser>`，整层不注入 mapper 字段，查询全走 `this.list()` / `remove()` / `getById()` 这些继承方法。调用图对这条通道完全失明——snowy 的逆向索引只有 4 条。现在 17 个 ServiceImpl 继承方法会映射到泛型 M 的 baseMapper 内置方法，snowy 逆向索引 **4 → 200**，事务闭包 339 → 480。
- **Manager 层模式**：dax-pay 自研 `BaseManager<M, T>`（和 ServiceImpl 同构），配套 `this.findByField(Entity::getField, value)` 字段值调用。基类正则和字段值规则同步泛化，dax-pay 内嵌 SQL 2 → 52 条。
- 顺带确认：favorites-web 是 JPA 项目，逆向索引 0 是正确行为——工具不装懂。

### 第三轮：OneBlog / newbee-mall-cloud / renren-security / pig / yudao-cloud

- **零新增缺陷**。前两轮建立的规则全部经受住跨仓库验证：pig 的 5 处 `<association select=...>` N+1 子查询链接正确产出；yudao-cloud（与 ruoyi-vue-pro 同源但独立仓库）识别出 1628 条 Wrapper 记录，helper 归并、X-Wrapper、字段值三条规则跨仓库复现一致。
- 仅剩 2 个"缺失"实为项目自身的死代码（声明了接口方法但没有对应实现），非分析器问题。

另外前 5 个项目（RuoYi-Vue / litemall / newbee-mall / RuoYi-Vue-Plus / xxl-job）还贡献过：`@MapperScan` 注解和 javadoc 提及 `@Mapper` 导致启动类误判成 Mapper、`<foreach>` 重建、resultMap `extends`/`<association>` 嵌套列归因、类级 `static final` SQL 常量互拼折叠、Wrapper 拆变量跨语句 def-use、逗号清理误吃 `order_id` 等 6 项修复。

## 20 个项目的最终数字

| 项目 | 类 | 路由 | 实体 | 内嵌 SQL |
|---|---:|---:|---:|---:|
| ruoyi-vue-pro | 6,098 | 3,009 | 540 | 1,631 |
| yudao-cloud | 6,179 | 2,999 | 538 | 1,628 |
| dax-pay | 2,892 | 1,315 | 173 | 52 |
| JeecgBoot | 906 | 968 | 98 | 254 |
| snowy | 811 | 431 | 47 | 344 |
| mall | 517 | 246 | 96 | 114 |
| 其余 14 个 | 3,405 | 1,618 | 368 | 238 |
| **合计 20 个** | **20,708** | **10,686** | **1,860** | **4,261** |

内嵌 SQL 里：MBG Example 合成 271 条（全部解码出 WHERE 条件）、Wrapper 链合成 3,990 条。最大单项目（ruoyi-vue-pro，6,355 个文件）秒级出图，零崩溃。

## 现在的规则覆盖面

- 路由注解、`@Autowired`/`@Resource` 注入、`@Transactional` 闭包（支持标在接口上）、`@PostConstruct` 等隐藏入口
- 注解 SQL、XML mapper（`<resultMap>` 含 extends 继承与 `<association>`/`<collection>` 嵌套归因、`<sql>`+`<include>`、`<set>`/`<if>`、`<foreach>` 重建、`select=` 懒加载子查询 N+1 链接）
- 注解与 XML 之外的全部主流形态：JdbcTemplate 裸 SQL（局部变量、类级常量、常量互拼折叠）、Wrapper 链（含 X 后缀扩展类）、Wrapper 拆变量跨语句 def-use（分支续链、拷贝别名、方法参数、**本类 helper 条件归并**）、**ServiceImpl/BaseManager 继承式调用**、**字段值便捷方法**、MBG Example 动态条件
- 多模块 Maven、多项目地图（一个 server 管多个项目）

## 诚实清单（仍解不了的）

- 正则级解析：内部类、Lombok 生成方法等复杂语法可能漏
- Wrapper 跨类传递、helper 套 helper、调用方在方法外拼的条件不追
- 运行期拼参 SQL（`"..." + variable`）、跨类 SQL 常量互拼静态拿不到
- MBG Example 的 criteria 分组语义按出现顺序平铺
- mapper default 方法间的委托链（A 调 B、B 里拼条件）只解析一层

## 招募：我们需要你

这套规则的下一程，靠一个人刷项目是刷不完的。三种参与方式，按门槛从低到高：

1. **拿你的项目跑一把（5 分钟，最有价值）**
   ```bash
   git clone https://github.com/23512478/ContextGate.git
   python ContextGate/analyzer/framework_map.py /path/to/your-project out.md
   ```
   打开 `out.md`，找"这条链路/这个字段明明用了却没出现"的地方，[提 issue](https://github.com/23512478/ContextGate/issues) 附一小段 Java/XML 源码即可。**你的项目就是下一批规则的来源**——本文 10 条规则全都是这么来的。
2. **补解析规则**：挑一个已知边界（见上），按 CONTRIBUTING.md 的流程"demo 夹具 + 断言 + 全绿"。参考最近的 PR 节奏：一个规则 = 一个夹具方法 + 两条断言 + 半小时。
3. **适配更多 AI 工具/语言**：MCP 是标准协议，Trae / Cursor / Claude Code 之外的工具接入基本零成本；分析器目前只覆盖 Java 侧。

如果觉得有用，去 [仓库](https://github.com/23512478/ContextGate) 点个 Star 就是最大的鼓励。

## 快速开始

```bash
# 零依赖（Python 3.10+ 标准库），分析任意 Spring Boot + MyBatis 项目
python analyzer/framework_map.py /path/to/your-project

# 或在 AI 工具里直接配 MCP server，对着 AI 说人话：
# "追踪 GET /api/v1/orders/my 的完整调用链" / "改 wallet_balance 影响哪些接口？"
```

详见 [README](https://github.com/23512478/ContextGate#readme)。本文提到的所有规则都有 demo 夹具和回归断言（`mcp-server/test_mcp.py`，69 项断言），clone 即可复现。
