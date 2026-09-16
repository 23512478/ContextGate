# 《AI 看不懂的三种 Java 写法·续：带参链式、getBean、Object 字段，逐个接通》

上一篇（[诚实清单还债篇](https://blog.csdn.net/2402_85811331/article/details/164757634)）结尾留了三条还没动的：

1. **链式中转的 getter 带参数时不追**（`a.getService(id).x()`）——带参 getter 的返回类型依赖参数值，静态拿不到
2. **运行期接收者不追**：`applicationContext.getBean(...)`、声明为 `Object` / 泛型 `T` 的字段
3. **Wrapper `.select()` 子查询列裁剪**排队中

这三条放了几天，越看越觉得不对劲——它们不像"内部类、Lombok"那种需要大改解析器的硬骨头，更像是上一篇说的第一类：**机制现成，只差接线**。于是又盘了一遍，结果三条全是第一类。这篇是第二轮还债实录。

## 第一条：Wrapper `.select()` 列裁剪——保守全列的收窄

先交代为什么这件事值得做。MyBatis-Plus 的内置 `selectList(wrapper)` 底层就是 `SELECT *`，所以分析器一直标"触碰全部列"——这在语义上是事实，不是近似。但很多项目会写：

```java
LambdaQueryWrapper<User> w = new LambdaQueryWrapper<>();
w.select(User::getId, User::getNickname);   // 只要两列
w.eq(User::getId, userId);
return userMapper.selectList(w);
```

这种情况下还标"触碰全部 5 列"就是过度保守了——AI 改 `users.openid` 字段时，`impact` 会把这条链路报出来，实际上它根本没碰 openid。

修法不复杂，核心就两步：

1. **消费点的 Wrapper 链必须静态可见且带显式 `.select(...)`**。Wrapper 链分析器本来就在做（条件动词 → SQL 片段），`.select(User::getId, ...)` 里的方法引用能解出列名，把这些列收集起来，替换掉"全列"占位。
2. **保守原则：该消费点的每个调用方都可见才裁**。如果 `selectList` 有多个调用方，其中一个的 Wrapper 是参数传进来的（看不见）或者直接 `null`，那就**不裁**——宁可多报一列，不能漏报。

代码里就是这个判断：

```python
callers = builtin_callers.get((mapper_name, bm), [])
if not callers or not all(o in sel_pruned_by_owner for o in set(callers)):
    return None   # 有一个调用方看不见，保守不裁
```

裁完之后的记录长这样：

```json
{
  "name": "selectList",
  "sql": {
    "kind": "SELECT",
    "text": "SELECT id, nickname FROM users WHERE id = ?",
    "columns": ["users.id (User.id)", "users.nickname (User.nickname)"],
    "mp_builtin": true,
    "select_pruned": true
  }
}
```

`impact` 里这个调用点带 **✂** 标记，一眼能看出是裁过的；`find_sql` 也能反查到裁剪后的真实 SQL（旧版占位文本 `"(MyBatis-Plus 内置 SELECT *)"` 不参与反查）。

边界写清楚：**count 族标 0 列不动、写操作全表写不动**——它们的语义本来就和行读取不同，不碰。

## 第二条：getter 带参的链式中转——参数不影响返回类型

上一篇修好的链式调用只认**无参** getter：`a.getSelf().listUsers()` 能通，但 `a.getService(userId).listUsers()` 直接断链。诚实清单里写的是"带参 getter 的返回类型依赖参数值，静态拿不到"——仔细一想，这句话**不对**。

返回类型写在方法签名里，和参数值有什么关系？

```java
public OrderQuerySupport getService(Long tenantId) {
    return this;
}
```

`getService` 的返回类型是 `OrderQuerySupport`，不管 `tenantId` 传什么都是这个类型。上一篇那个链式正则把中间节限定成 `\.\w+\(\)`（空括号），等于自己把带参的排除了。放宽成 `\.\w+\([^()]*\)` 就行——节内参数用 `[^()]*` 线性匹配，不嵌套，不会有回溯性能问题。

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

根节点也放宽了：上一篇只支持字段/局部变量做根，现在本类裸调用也通——`getSelf().getService(x).tail()` 的根 `getSelf` 返回类型从本类方法签名取。

### 踩坑：`re.findall` 单分组返回 1-tuple，解包直接崩

这条值得单独记一笔。getter 节是从 group(3) 的文本里二次剥出来的，第一版我写的是：

```python
getters = re.findall(r"[a-z]\w*\s*\([^()]*\)", ccm.group(3))
```

然后 `for gname, gargs in getters:` 直接解包——**崩了**。`re.findall` 只有一个分组（或者没分组）时返回的是 **1-tuple**，`(gname, gargs)` 解包会报 `not enough values to unpack`。必须写两个显式分组：

```python
getters = tuple(re.findall(r"([a-z]\w*)\s*\(([^()]*)\)", ccm.group(3)))
```

这样每个元素是 `(name, args)` 的 2-tuple，解包才对。这个坑和上一篇的 `\n` 拼接 bug 一样，都是**正则 API 的细节陷阱**——写的时候不觉得，跑起来才知道。

## 第三条：运行期接收者——静态拿不到的类型，代码里其实有线索

这是三条里看起来最硬的。`ctx.getBean(OrderQuerySupport.class)` 返回什么类型，运行期才知道；声明为 `Object` 的字段 `helper`，实际是什么类型也运行期才知道。诚实清单直接归到第三类"原理拿不到"。

但仔细看代码，**静态文本里其实有线索**：

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

字段声明是 `Object`，但 `@PostConstruct` 里被 `new OrderQuerySupport()` 赋值了。扫描方法体里的赋值语句，如果右值是 `new X()`、`getBean(X.class)` 或 `(X) ...`，就把 `X` 当作该字段的真实类型。沿继承链查（子类可以给父类字段赋值）。

### 线索三：强转

```java
((OrderQuerySupport) helper).listUsersDirect(userId);
```

强转类型 `OrderQuerySupport` 就是接收者类型——程序员已经告诉你了。

三个线索合起来，大部分"运行期接收者"都能救回来。而且 `getBean` 调用本身不再产生噪音边——之前 `ctx.getBean(...)` 会被当成一次普通调用收进来，在图里留一条指向 `ApplicationContext` 的假边，现在直接跳过。

## 数字与验证

- demo 夹具新增 6 条路由（`chain-arg` / `bean-chain` / `bean-var` / `obj-field` / `obj-cast` / `sel-prune`），**33 → 39 路由**
- 回归断言新增 **7.41 / 7.42 / 7.43**，全绿
- `sel-prune`：`selectList` 从触碰 5 列收窄到 **2 列**（id, nickname），`SELECT id, nickname FROM users WHERE id = ?`，`select_pruned: true`，`impact` 带 ✂
- `chain-arg`：`getService(userId).listUsersDirect()` 尾方法接入，一路追到 `UserMapper#selectById`
- `bean-chain` / `bean-var` / `obj-field` / `obj-cast`：四条运行期接收者链路全部从路由追到 Mapper 内置方法，且 `getBean` 噪音边消失

对照 demo 夹具一眼看懂三条规则各管什么：

```java
// 列裁剪：select 的列替换全列
LambdaQueryWrapper<User> w = new LambdaQueryWrapper<>();
w.select(User::getId, User::getNickname);
w.eq(User::getId, userId);
return userMapper.selectList(w);   // ✂ 触碰 2 列

// 带参链式中转：参数不影响返回类型解析
return orderQuerySupport.getService(userId).listUsersDirect(userId);

// 运行期接收者四种形态
ctx.getBean(OrderQuerySupport.class).listUsersDirect(userId);   // .class 参数
var svc = ctx.getBean(OrderQuerySupport.class);                 // var + getBean
return helper.listUsersDirect(userId);                          // Object 字段赋值推断
return ((OrderQuerySupport) helper).listUsersDirect(userId);    // 强转
```

## 更新后的诚实清单

还完这三条，剩下的边界如实列出：

- **工厂方法返回值接收者不追**（`f = buildXxx()`）——工厂方法内部逻辑静态推不出返回类型
- **纯泛型绑定不追**：子类只是 `extends Base<T>` 却从不给 `T` 赋值，类型参数无静态线索
- **运行期拼参拿不到**：`"..." + variable` 的 SQL 骨架，静态无解
- **正则级解析的老边界**：内部类 / 同文件多类、Lombok 生成方法，遇到再补

方法没变：demo 夹具 + 断言 + 全绿，一条命令复现全部。你的项目里如果有带参链式中转、`getBean` 调用、Object 字段直调、或者 Wrapper `.select()` 裁剪的场景，跑一把 `python analyzer/framework_map.py <你的项目>`，对着 `framework_map.md` 报漏报——**你的项目就是最好的测试用例**，这句话每次都算数。

仓库：[ContextGate](https://github.com/23512478/ContextGate)（MIT，分析器零依赖纯标准库）。这批改动已合入 main，随下个版本发布。
