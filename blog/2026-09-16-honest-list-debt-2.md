# 《静态分析拿不到的三种 Java 写法，其实代码里都留了线索》

做 Spring Boot 静态代码分析的人，大概都被这三种写法劝退过——一看就觉得"运行期才发生的事，静态无解"，直接写进"已知不支持"清单。

我也一样。直到把它们逐个拆开看，发现**代码里其实留了静态线索**，只是之前没去捡。这篇就是这三种写法的拆解和接通实录。

## 第一种：Wrapper `.select()` 列裁剪——保守全列的收窄

MyBatis-Plus 的内置 `selectList(wrapper)` 底层是 `SELECT *`，所以分析器一直标"触碰全部列"。语义上这是事实——但实际项目里经常这么写：

```java
LambdaQueryWrapper<User> w = new LambdaQueryWrapper<>();
w.select(User::getId, User::getNickname);   // 只要两列
w.eq(User::getId, userId);
return userMapper.selectList(w);
```

还标"触碰全部 5 列"就是过度保守了。AI 改 `users.openid` 字段时，`impact` 会把这条链路报出来，实际上它根本没碰 openid。

修法两步：

1. **消费点的 Wrapper 链必须静态可见且带显式 `.select(...)`**。`.select(User::getId, ...)` 里的方法引用能解出列名，用这些列替换掉"全列"占位。
2. **保守原则：该消费点的每个调用方都可见才裁**。如果 `selectList` 有多个调用方，其中一个的 Wrapper 是参数传进来的（看不见）或者直接 `null`，那就**不裁**——宁可多报一列，不能漏报。

```python
callers = builtin_callers.get((mapper_name, bm), [])
if not callers or not all(o in sel_pruned_by_owner for o in set(callers)):
    return None   # 有一个调用方看不见，保守不裁
```

裁完的记录：

```json
{
  "name": "selectList",
  "sql": {
    "text": "SELECT id, nickname FROM users WHERE id = ?",
    "columns": ["users.id (User.id)", "users.nickname (User.nickname)"],
    "select_pruned": true
  }
}
```

`impact` 里带 **✂** 标记，`find_sql` 能反查到裁剪后的真实 SQL。边界写清楚：**count 族标 0 列不动、写操作全表写不动**——语义不同，不碰。

## 第二种：带参 getter 的链式中转——参数不影响返回类型

链式调用 `a.getService(userId).listUsers()`，初看觉得"带参 getter 的返回类型依赖参数值，静态拿不到"。

仔细一想，这句话**不对**。返回类型写在方法签名里，和参数值有什么关系？

```java
public OrderQuerySupport getService(Long tenantId) {
    return this;
}
```

`getService` 的返回类型是 `OrderQuerySupport`，不管 `tenantId` 传什么都是这个类型。所以问题根本不是"解析不出类型"，而是**链式正则把带参 getter 排除了**——之前只认空括号 `getService()`，放宽成 `getService(userId)` 就行，节内参数用 `[^()]*` 线性匹配，不嵌套，无回溯。

然后逐节查方法签名的 `ret_type`：

```python
for gname, gargs in getters:
    if gname == "getBean":        # 运行期装配，类型取 .class 参数
        bm = re.search(r"([\w.]+)\s*\.\s*class", gargs or "")
        t = simple_type(bm.group(1)) if bm else None
        continue
    gcls = by_simple.get(t)
    g_meth = next(m for m in gcls["methods"] if m["name"] == gname)
    t = simple_type(g_meth["ret_type"])   # 返回类型本来就采集了，零新数据
```

根节点也支持三种形态：字段、局部变量、本类裸调用（`getSelf().getService(x).tail()`）。

### 踩坑：`re.findall` 单分组返回 1-tuple，解包直接崩

getter 节从匹配文本里二次剥出，第一版写的是：

```python
getters = re.findall(r"[a-z]\w*\s*\([^()]*\)", ccm.group(3))
```

然后 `for gname, gargs in getters:` 解包——**崩了**。`re.findall` 只有一个分组（或没分组）时返回 **1-tuple**，`(gname, gargs)` 解包报 `not enough values to unpack`。必须写两个显式分组：

```python
getters = tuple(re.findall(r"([a-z]\w*)\s*\(([^()]*)\)", ccm.group(3)))
```

每个元素才是 `(name, args)` 的 2-tuple。正则 API 的细节陷阱，写的时候不觉得，跑起来才知道。

## 第三种：运行期接收者——静态拿不到的类型，代码里有线索

`ctx.getBean(OrderQuerySupport.class)` 返回什么类型、声明为 `Object` 的字段 `helper` 实际是什么类型，都是运行期才知道。但仔细看代码，**静态文本里留了三条线索**：

### 线索一：`.class` 参数

```java
ctx.getBean(OrderQuerySupport.class).listUsersDirect(userId);
```

`getBean` 的参数是 `OrderQuerySupport.class`——类型就写在那儿。从参数里正则解出 `X.class` 的 `X`，就是接收者类型。同样适用于赋给局部变量：

```java
var svc = ctx.getBean(OrderQuerySupport.class);
svc.listUsersDirect(userId);
```

### 线索二：赋值语句

```java
private Object helper;

@PostConstruct
public void initHelper() {
    helper = new OrderQuerySupport();   // 赋值给了真实类型
}
```

字段声明是 `Object`，但 `@PostConstruct` 里被 `new OrderQuerySupport()` 赋值。扫描方法体里的赋值语句，右值是 `new X()`、`getBean(X.class)` 或 `(X) ...` 时，把 `X` 当作该字段的真实类型，沿继承链查。

### 线索三：强转

```java
((OrderQuerySupport) helper).listUsersDirect(userId);
```

强转类型 `OrderQuerySupport` 就是接收者类型——程序员已经告诉你了。

三条线索合起来，大部分"运行期接收者"都能救回来。而且 `getBean` 调用本身不再产生噪音边——之前会被当成普通调用留一条指向 `ApplicationContext` 的假边，现在直接跳过。

## 验证

- demo 夹具新增 6 条路由（`chain-arg` / `bean-chain` / `bean-var` / `obj-field` / `obj-cast` / `sel-prune`），**39 路由**全量回归全绿
- `sel-prune`：`selectList` 从触碰 5 列收窄到 **2 列**（id, nickname），`SELECT id, nickname FROM users WHERE id = ?`，`impact` 带 ✂
- `chain-arg`：`getService(userId).listUsersDirect()` 尾方法接入，一路追到 `UserMapper#selectById`
- `bean-chain` / `bean-var` / `obj-field` / `obj-cast`：四条运行期接收者链路全部从路由追到 Mapper 内置方法，`getBean` 噪音边消失

## 还做不到的

诚实列出来：

- **工厂方法返回值接收者**（`f = buildXxx()`）——工厂方法内部逻辑静态推不出返回类型
- **纯泛型绑定**：子类只是 `extends Base<T>` 却从不给 `T` 赋值，类型参数无静态线索
- **运行期拼参的 SQL**：`"..." + variable` 的骨架，静态无解
- **正则级解析的老边界**：内部类、Lombok 生成方法，遇到再补

仓库：[ContextGate](https://github.com/23512478/ContextGate)（MIT，分析器零依赖纯标准库）。这批改动已合入 main。你的项目里如果有带参链式、`getBean`、Object 字段直调、Wrapper `.select()` 的场景，跑一把 `python analyzer/framework_map.py <你的项目>` 试试——**你的项目就是最好的测试用例**。
