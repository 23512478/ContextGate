上一篇（[23 个项目练兵全记录](https://blog.csdn.net/2402_85811331/article/details/164626629)）结尾我说：第 24 个项目大概率还会撞上新的拼装姿势。这次没有等项目来撞，做了一件反过来事：**把诚实清单当 backlog，自己盘了一遍**。

盘的方法很朴素——对着每条"已知做不到"，去代码里找它做不到的原因，然后分成三类：

1. **机制现成，只差接线**：数据结构、正则、不动点轮都在，就差一处没接上
2. **部分可解**：原理上拿不全，但能降级出半份结果
3. **原理拿不到**：运行期才发生的事，静态分析无解

结论有点意外：清单里有两条看起来最硬的，其实都是第一类。这篇文章就是这两条的还债实录——包括修的过程中剥出来的三层洋葱、一个差点白做的设计错误、和一个潜伏了很久的拼接 bug。

## 第一条：Example 多跳传播，断的其实不是传播是种子

先交代背景。MyBatis Generator 的 `Example` 是老式动态查询三件套：

```java
UserExample ex = new UserExample();
ex.createCriteria().andNicknameEqualTo(nickname);   // 条件在这里拼
orderQuerySupport.relayUserExample(ex);              // 转传
```

v0.2.0 已经支持"条件在调用方拼、消费在目标方法"的**一跳**传播。但诚实清单里写着：Example 参数传播追一跳，Wrapper 参数传播多跳。也就是说链再长一节——Controller 拼 → 中转层再拼 → 终点消费——Controller 那层条件就丢了。

看代码发现第一层洋葱：**这根本不是能力差距**。传播循环和 Wrapper 共用同一套队列结构，Wrapper 那边有 `nxt.extend(props)` 把下游消费点续进队列，Example 这边 `nxt` 恒为空——等于齿轮都在，传送带没装。让 `_example_defuse` 返回传播目标、接上队列，理论上就通了。

理论上。接完线跑 demo，终点还是没记录。

第二层洋葱：**变量名跨跳不一致**。Controller 里叫 `ex`，中转层的方法参数叫 `example`。种子收集器按变量名过滤语句，`ex` 拼的条件语句到了中转层那边对不上 `example` 这个名字，整块丢失。修法是把链上所有 `XxxExample` 类型的声明变量都并进种子收集的起始集合——条件是跟着对象走的，不是跟着变量名走的。

修完再跑，终点有记录了，但 SQL 长这样：

```sql
SELECT * FROM users WHERE nickname = ? AND create_time > ?
```

没有括号。两层条件挤进了同一个 criteria 组——而正确语义应该是 `(nickname = ?) AND (create_time > ?)`，两个独立组。这是第三层洋葱，也是最隐蔽的一个：**种子语句拼接用的是 `\n`，而下游的语句分割器按分号切**。整块种子被当成"一条语句"，`createCriteria()` 只触发一次，所有条件全归进那个组。改成 `;\n` 拼接，分组语义立刻恢复：

```sql
SELECT * FROM users WHERE (nickname = ?) AND (create_time > ?)
```

这条 bug 值得单独记一笔：它在**一跳场景下永远暴露不出来**。一跳的种子进了目标方法直接消费，不需要再切分；只有第二跳出现、种子需要被二次解析时，`\n` 拼接的整块文本才塌缩成一条语句。和上一篇那个"旧夹具上永远暴露不出来"的 ORDER 关键字 bug 是同一个道理——**回归测试只保护你修过的姿势，不保护你没试过的深度**。

多跳通了之后还有个隐患要防：A 把 Example 传给 B、B 又传回 A 的互传写法，会让种子每轮变大、按三元组去重失效，直接死循环。修法是按（目标类， 目标方法）记录已播种的语句集合，新种子不是严格增长就停止接力。真实项目里大概没人这么写，但静态分析工具的死循环防护不能赌人性。

## 第二条：链式调用是收集问题，不是解析问题

诚实清单里还有一条从 v0.1 传下来的：接收者解析不出类型的调用不追，点名了两种——链式返回值 `getService().x(w)` 和方法内 `new` 出来的对象。代码里的原注释更直白：

```python
if not ftype:
    continue  # 局部变量/静态调用，MVP 不追
```

先说链式。`a.getService().listUsers()` 这种写法，调用解析正则的接收者位置只认单个标识符——链式的接收者位置是个 `)`，**尾方法根本就进不了数据**。所以这个问题的第一步不是"怎么解析类型"，是"先把这条调用收进来"。加一个链式收集正则（中间节限定无参 getter，`(\w+(?:\.\w+\(\))+)\.\w+\(` 的形态，无嵌套量词），收进来之后类型解析反而是最容易的部分：

方法签名里的返回类型，扫描器**本来就采集了**，只是从来没人消费它。`getSelf()` 的签名写着返回 `OrderQuerySupport`，顺着链逐节查过去，尾方法的接收者类型就落出来了。零新数据，纯接线。

局部变量是同一个思路：`OrderQuerySupport support = new OrderQuerySupport()` 的类型就写在声明里，`var s = new T()` 的类型就写在 new 右边。给每个方法建一张局部变量类型表，字段表查不到时兜底查它——那句 "MVP 不追" 的注释可以换了。

## 差点白做：过滤条件想错了方向

这两条还债过程中我犯了个设计错误，值得写出来。

局部变量来源收进来的东西很杂——`String`、`List`、实体对象、Example 全会进表。第一版我心想宁缺毋滥：局部来源一律不产兜底边（component），免得图里全是噪音。结果 demo 一跑，三条新链路**全部没通**：

```java
OrderQuerySupport support = new OrderQuerySupport();
support.listUsersDirect(userId);   // 断链
```

`OrderQuerySupport` 不以 `Service` 结尾、不实现任何接口——它是个普通 `@Service` 组件类，正卡在"不是 Mapper、不是 Service"的中间地带，而兜底边被我亲手关了。

修完才发现过滤条件从一开始就写错了方向：**该过滤的是"什么内容是噪音"，不是"数据从哪个来源来"**。局部变量上调用 `user.setNickname(...)`、`example.createCriteria(...)` 是噪音，因为实体和 Example 不是组件；局部变量上调用 `support.listUsersDirect(...)` 是真链路。按类型过滤（实体/Example 排除，其余进兜底），来源根本不用管。

## 数字与验证

- demo 夹具新增 4 条路由（`example-relay` / `chain-call` / `local-new` / `local-var`），29 → 33
- 回归断言 75 → **78 项**全绿（7.38 Example 多跳、7.39 链式、7.40 局部 new / var）
- 逆向索引验证：三条新链路全部从路由一路追到 `UserMapper#selectById`；Example 三个消费点各恰好一条完整记录，无重复落地
- 诚实清单收窄 2 条，排队清单同步更新

对照 demo 夹具可以一眼看懂这两条规则各自管什么：

```java
// 多跳：Controller 拼 nickname → 中转层拼 create_time → 终点合成两层条件
UserExample ex = new UserExample();
ex.createCriteria().andNicknameEqualTo(nickname);
orderQuerySupport.relayUserExample(ex);

// 链式：尾方法按无参 getter 的签名返回类型逐节解析
return orderQuerySupport.getSelf().listUsersDirect(userId);

// 局部：方法内 new 的对象，类型表兜底（var 同理）
OrderQuerySupport support = new OrderQuerySupport();
return support.listUsersDirect(userId);
```

## 更新后的诚实清单

还完这两条，剩下的边界如实列出：

- **链式中转的 getter 带参数时不追**（`a.getService(id).x()`）——带参 getter 的返回类型依赖参数值，静态拿不到
- **运行期接收者不追**：`applicationContext.getBean(...)`、声明为 `Object` / 泛型 `T` 的字段
- **运行期拼参拿不到**：`"..." + variable` 的 SQL 骨架，静态无解（局部 `final String` 单赋值传播可以救一批，排队中）
- **Wrapper `.select()` 子查询列裁剪**排队中
- **正则级解析的老边界**：内部类 / 同文件多类、Lombok 生成方法，遇到再补

方法没变：demo 夹具 + 断言 + 全绿，一条命令复现全部。你的项目里如果有链式转传、方法内造 Wrapper、或者别的没见过的拼装姿势，跑一把 `python analyzer/framework_map.py <你的项目>`，对着 `framework_map.md` 报漏报——**你的项目就是最好的测试用例**，这句话每次都算数。

仓库：[ContextGate](https://github.com/23512478/ContextGate)（MIT，分析器零依赖纯标准库）。这批改动已合入 main，随下个版本发布。
