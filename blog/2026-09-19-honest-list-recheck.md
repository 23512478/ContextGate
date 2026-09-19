# 《工厂方法和局部拼 SQL：复审诚实清单，又抠出两条能修的》

前两轮把诚实清单上的规则还得差不多之后，我把 README 里那份"已知边界"又从头读了一遍，想看看剩下的到底还能不能动。读的时候发现有两条当初归得有点草率，这次顺手修了。

## 第一条：工厂方法返回值，类型其实在签名上

清单上原来写的是：工厂方法返回值接收者（`f = buildXxx()`）不追，静态推不出返回类型。

写这条的时候想的是：工厂方法返回什么对象，运行期才知道。但后来对着代码看，这话有问题。分析器要的从来不是那个对象，是类型，而类型就写在方法签名上：

```java
private OrderQuerySupport buildSupport() {
    return new OrderQuerySupport();
}

var svc = buildSupport();
svc.listUsersDirect(userId);
```

`buildSupport()` 方法体里怎么写、走哪个分支都无所谓，签名声明返回 `OrderQuerySupport`，这是静态的。这个东西扫描器一直在采（链式 getter 解析用的就是同一份 `ret_type`），只是 var 推断那几个分支只认 `new T()` 和 `getBean(T.class)`，工厂方法调用根本没往里收。

跨类的形态也一样：

```java
var svc = supportFactory.create();
```

`supportFactory` 是注入字段，类型 `SupportFactory`；再查它 `create()` 的签名，拿到 `OrderQuerySupport`。

真正费了点事的是时序。认出 `var svc = buildXxx()` 是在单文件解析阶段，这时候别的类还没扫完，全局类表不存在，想查 `create()` 的返回类型也没地方查。最后是 parse 阶段先存个占位的东西，等 build 阶段类表齐了再解：

```python
# parse 阶段只记下"这是个工厂方法调用"
local_vars[name] = ("bare", "buildSupport")
field_assign[fname] = ("call", "supportFactory", "create")
```

解析的时候沿继承链往上查方法签名，父类里有也认；接收者自己要是工厂产物（`var a = x.build(); var b = a.make()`），占位套占位，递归一层就出来了，没做更深的，真实项目里没见过。

字段赋值那种写法也一起接了。有个字段声明成 `Object`，在 `@PostConstruct` 里被工厂方法赋值：

```java
private Object made;

@PostConstruct
public void initMade() {
    made = supportFactory.create();
}
```

这跟之前 new 赋值、getBean 赋值走的是同一条字段赋值推断，只是右值多认出一种形态。

## 第二条：局部 String 拼 SQL，被"运行期拼参"一刀切了

清单上还有一句：`"..." + variable` 的 SQL 骨架静态无解。

这句对一半。像下面这种确实没办法，`userId` 是参数，值运行期才进来：

```java
jdbcTemplate.queryForList("SELECT * FROM users WHERE id = " + userId);
```

但项目里常见的另一种写法被一起误杀了：

```java
final String tail = " WHERE openid = 'local-pin'";
String cols = "id, nickname";
String sql = "SELECT " + cols + " FROM users" + tail;
jdbcTemplate.queryForList(sql);
```

`cols`、`tail` 都是方法内单赋值的 String，值在源码里摆着，没有任何运行期成分。之前局部变量声明只收纯字面量右值，`sql` 一引用别的变量整块就丢了。

修法没什么新东西，类级 static 常量那套搬下来用：右值从 `=` 切到第一个 `;`，切成 token，字面量和标识符分开记；遇到括号、方法调用这种成分，这个变量直接放弃。然后不动点折叠——第一轮 `cols`、`tail` 先折出来，第二轮 `sql` 引用它们就能折，所以片段写在前面后面都行。标识符还允许是本类常量和别的类的常量，跟类级那套共用解析。

折出来是完整的一句：

```
SELECT id, nickname FROM users WHERE openid = 'local-pin'
```

还有一种写法连中间变量都省了，jdbc 首参直接拼：

```java
final String where = " WHERE openid = 'inline-pin'";
jdbcTemplate.queryForObject("SELECT COUNT(*) AS c FROM users" + where, Long.class);
```

这个给字面量拼接函数加了个回调：拼到不是字面量的片段时，回头问一句这个名字认不认识，是局部常量就续上，不认识就停。不会留半截 SQL。

放弃的边界还是原来那条：右值里有方法参数、方法调用返回值的变量不收。那种才是真的运行期拼参。

## 验证

demo 加了 5 条路由：`factory-local`（本类工厂方法）、`factory-bean`（跨类）、`factory-field`（Object 字段工厂赋值）、`openid/local`（局部片段拼 sql 变量）、`openid/local-inline`（jdbc 首参直接拼），总数 39 到 44。

断言加了 7.44 和 7.45：三条工厂链路都从路由追到 `UserMapper#selectById`；两条拼接 SQL 能用 `find_sql` 反查到全文。全量回归加 多项目模式都绿。

## 剩下的

清单上还没动的几条：

- 纯泛型绑定：子类只写 `extends Base<T>` 但从不给 T 赋值，静态文本里找不到 T 到底是什么（`ServiceImpl<M, T>` 是单独硬编码支持的，自定义泛型基类还不行）
- 真运行期拼参：SQL 里拼方法参数、方法返回值
- 内部类、同文件多类、Lombok 生成方法：正则解析的老毛病，要动得换解析方式

老规矩，代码在 [ContextGate](https://github.com/23512478/ContextGate)（MIT，零依赖纯标准库），已经合进 main。你的项目里要是有这几种写法，跑一把 `python analyzer/framework_map.py <你的项目>`，漏了告诉我。
