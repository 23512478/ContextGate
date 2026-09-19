# 《静态分析复审诚实清单：两条"无解"，其实是我没往下看一层》

做静态分析工具，我有个习惯：做不到的规则不装死，写进一份"诚实清单"挂在 README 上，哪类写法不追、为什么不追，一条条列清楚。

这份清单最近做了一次复审，结论有点打脸：**里面有两条"静态无解"，根本不是原理问题，是我当时没往下看一层就草草归类了。**

一条是"工厂方法返回值接收者不追"，另一条藏在"运行期拼参拿不到"里。这篇是复审和修复实录。

## 打脸一：工厂方法——"拿不到对象"被我写成了"拿不到类型"

清单原文是：工厂方法返回值接收者（`f = buildXxx()`）不追，因为静态推不出返回类型。

这句话乍看没毛病。工厂方法嘛，返回什么不是运行期才知道？但把例子摆出来就露馅了：

```java
private OrderQuerySupport buildSupport() {
    return new OrderQuerySupport();
}

var svc = buildSupport();
svc.listUsersDirect(userId);
```

`buildSupport()` 运行期返回的**那个对象**确实拿不到——但我要的从来不是那个对象，是它的**类型**。而类型就白纸黑字写在方法签名上：`OrderQuerySupport`。不管方法体里 `new` 了什么、走了哪个 if 分支，签名声明的返回类型是静态事实。

之前修好的链式 getter 已经证明过一次同样的事（返回类型扫描器从 v0.1 就采集了，只是没人消费），结果到了工厂方法这儿又绕进去了。跨类形态同理：

```java
var svc = supportFactory.create();   // supportFactory 是注入字段 → SupportFactory
                                     // SupportFactory.create() 签名 → OrderQuerySupport
```

还有字段赋值形态：声明为 `Object` 的字段，在 `@PostConstruct` 里被工厂方法赋值：

```java
private Object made;

@PostConstruct
public void initMade() {
    made = supportFactory.create();
}
```

### 实现上唯一的新东西：延迟描述符

逻辑简单，但有个时序问题：识别 `var svc = buildXxx()` 发生在**单文件解析阶段**，这时候所有类还没扫完，`SupportFactory` 的方法签名表（`by_simple`）根本不存在，想查 `create()` 的返回类型也无处可查。

解法是 parse 阶段先不解析，存一个延迟描述符，等全局类表建好再解：

```python
# parse 阶段：只记录"这是个工厂方法调用"，不关心返回类型
local_vars[name] = ("bare", "buildSupport")            # 本类裸调用
field_assign[fname] = ("call", "supportFactory", "create")  # 字段.方法()

# build 阶段：by_simple 就绪后，沿继承链查签名 ret_type
def ret_type_of(cls_name, meth_name):
    ...  # 类自己没有就查父类，接口方法声明也带 ret_type
```

接收者本身也是工厂产物时（`var a = x.build(); var b = a.make()`），描述符套描述符，递归一层就解开了。

修完三种形态全部从路由追到 Mapper：`factory-local`（本类）、`factory-bean`（跨类）、`factory-field`（字段赋值）。

## 打脸二："运行期拼参无解"——一刀切切掉了能救的那批

清单里还有一句话：`"..." + variable` 的 SQL 骨架，静态无解。

典型例子是 JdbcTemplate：

```java
jdbcTemplate.queryForList("SELECT * FROM users WHERE id = " + userId);
```

这个确实无解——`userId` 是方法参数，值运行期才进来。我当时把所有"字面量 + 标识符"的拼接都归到了这一类，局部变量声明只收纯字面量右值。但项目里还有另一种常见写法：

```java
public List<Map<String, Object>> demoOpenidLocal() {
    final String tail = " WHERE openid = 'local-pin'";
    String cols = "id, nickname";
    String sql = "SELECT " + cols + " FROM users" + tail;
    return jdbcTemplate.queryForList(sql);
}
```

`cols` 和 `tail` 都是方法内的单赋值 String，值在静态文本里完完整整。把它们判成"运行期拼参无解"，纯属一刀切误伤。

修法是把类级 static 常量那套机制**原样搬到方法内**：

1. 每个局部 String 声明，右值从 `=` 切到 `;`，切成 token 列表——字面量是 `("lit", 文本)`，标识符是 `("id", 名字)`，遇到方法调用、括号这种真运行期成分直接放弃该变量；
2. 不动点折叠：`sql` 引用 `cols`/`tail`，第一轮 `cols` 先折出来，第二轮 `sql` 就能折。所以**片段定义在前面后面都无所谓**；
3. 标识符还允许是本类 static 常量、`Other.Const` 跨类常量——消费点和类级常量共用一套解析。

折叠结果：

```
SELECT id, nickname FROM users WHERE openid = 'local-pin'
```

还有一种更省变量的写法，jdbc 首参直接拼，连中间 `sql` 变量都没有：

```java
final String where = " WHERE openid = 'inline-pin'";
jdbcTemplate.queryForObject("SELECT COUNT(*) AS c FROM users" + where, Long.class);
```

给字面量拼接函数加一个可选的标识符解析回调，遇到非字面量片段时回调问一句"这个名字你认识吗"，认识就续拼、不认识就停。半截 SQL 也不会留下。

边界照旧诚实划清：右值拼的是**方法参数、方法调用返回值**这类真运行期成分的变量，放弃——这才是"运行期拼参无解"的准确范围。

## 两条债的共性：数据和机制都是现成的

修完复盘，这两条有同一个味道：

- 工厂方法需要的 `ret_type`，方法签名扫描器从第一天就在采集；
- 局部 String 需要的 token 切分 + 不动点折叠，类级常量早就跑了大半年。

**没有一条需要新能力，全是"把已有的东西用到新场景"。** 它们被写进"无解"清单，原因也一样：归类时图省事，把"这一层拿不到"夸大成了"整条无解"——拿不到运行期对象，不等于拿不到静态类型；一部分拼接无解，不等于所有标识符拼接都无解。

## 验证

- demo 夹具新增 5 条路由（`factory-local` / `factory-bean` / `factory-field` / `openid/local` / `openid/local-inline`），**44 路由**全量回归全绿
- 回归断言新增 **7.44 / 7.45**：三条工厂链路全部追到 `UserMapper#selectById`；两条局部拼接 SQL 全文可被 `find_sql` 反查
- 三条工厂链路的边都落在真实类型上，没有出现"工厂调用被当成普通噪音边"的副作用

## 更新后的诚实清单

还掉这两条，剩下的是真硬的：

- **纯泛型绑定无赋值线索**：子类只是 `extends Base<T>` 却从不给 `T` 赋值，类型参数在静态文本里没有任何落地点
- **真运行期拼参**：SQL 里拼方法参数、方法调用返回值，值只有运行期才有
- **正则级解析的老边界**：内部类 / 同文件多类、Lombok 生成方法

最后留一句给自己的提醒：**"诚实"不只是把做不到的写出来，还包括定期回去复审自己写下的"做不到"。** 清单里的每一条"无解"都应该标注清楚——到底是哪一层无解。否则诚实清单也会变成另一种偷懒：用一个干脆的结论，掩盖一个其实只需要往下看一层的问题。

仓库：[ContextGate](https://github.com/23512478/ContextGate)（MIT，分析器零依赖纯标准库）。这批改动已合入 main。
