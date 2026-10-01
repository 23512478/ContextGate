# Spring Boot 静态调用链提取：攻克泛型绑定与运行期 SQL 两大难题

> 不用任何 Java AST 库，纯正则 + 线性扫描，如何让 AI 看懂那些「看起来动态、其实静态信息全在源码里」的 Java 写法？

做 [ContextGate](https://github.com/23512478/ContextGate) 这个工具的初衷很简单：给一个 Spring Boot + MyBatis 项目，自动吐出「哪个 HTTP 接口 → 哪个 Service → 哪个 Mapper 方法 → 读了哪张表的哪些列」的完整地图。改字段怕漏影响面、做数据治理要列血缘、评审要看 SQL 触达范围，这些场景都用得上。

整个分析器零第三方依赖，全靠正则和线性扫描——这是有意为之，换台机器 `python framework_map.py 项目目录` 直接出结果，不折腾。

但正则解析 Java 有两道绕不开的坎：**泛型继承里的类型绑定**，和 **SQL 字符串里拼接运行期值**。v0.2.1 就是专门啃这两块硬骨头的。这篇把设计思路和实现细节完整记下来。

---

## 一、泛型继承：为什么 AI 总是看不懂 `extends AbstractBase<M, T>`

MyBatis-Plus 的 `ServiceImpl<M, T>` 是最早支持的泛型场景：

```java
public class ProductServiceImpl extends ServiceImpl<ProductMapper, Product> {}
```

子类写死了 `M=ProductMapper`、`T=Product`，分析器扫到 `this.getById()` 就能映射到 `ProductMapper#selectById`。一开始这段是硬编码的——正则抓 `ServiceImpl<(\w+), (\w+)>`，拿到两个类型就结束。

**直到真实项目里出现了这种写法：**

```java
public abstract class AbstractEntityService<M extends BaseMapper<T>, T> {
    @Autowired
    protected M mapper;

    public T findOne(Long id) {
        return mapper.selectById(id);   // ← 分析器卡在这里
    }
}

public class OrderService extends AbstractEntityService<OrderMapper, Order> {}
```

方法体全在基类里，`mapper` 的类型是 `M`，`findOne` 的返回类型是 `T`。分析器去类表里查 `M`，查不到，直接判「类型不可知」，调用链断在基类。

更过分的是中间还能再隔一层：

```java
public abstract class Mid<T> extends AbstractEntityService<OrderMapper, T> {}
public class OrderService extends Mid<Order> {}
```

`Mid` 把 `M` 钉成了 `OrderMapper`，`T` 继续往下透传。要把 `T` 从 `OrderService` 一路折回到 `AbstractEntityService`，必须沿继承链逐层对齐形参和实参。

### 核心设计：带命名空间的绑定折叠

直觉做法是从具体子类往上 BFS，每跳一层把「父类形参 ← 子类实参」存进字典。但有个隐蔽的坑：

```java
class A<T> { ... }
class B<T> extends A<T> { ... }   // 两个 T 不是同一个东西！
class C extends B<Order> { ... }
```

如果绑定只按裸形参名 `T` 存，`A` 的 `T` 和 `B` 的 `T` 会串值。

所以绑定的 key 是 **`(声明类, 形参名)` 二元组**：

```python
# C extends B<Order>
# B<T> extends A<T>
bindings[("B", "T")] = "Order"
bindings[("A", "T")] = "Order"   # 透传自 B 的 T
```

解析字段类型、方法签名返回类型时，必须带上「这段类型写在哪个类里」。`M mapper` 写在 `AbstractEntityService`，就用 `("AbstractEntityService", "M")` 去折；`T findOne()` 的返回类型同理。十层基类都叫 `T` 也不怕，各归各的命名空间。

`ServiceImpl<M, T>` 那三处正则特判也全部换成读这套折叠结果——直接继承和中间夹自定义基类走同一条逻辑，不再特殊照顾。

### 衍生问题：继承方法的调用图补建

绑定折叠解决了「类型是谁」，还有个「方法在哪」的问题。

`OrderService` 自己一个方法都没有，调用图第一轮只建子类自身声明的方法节点。但 `Mid#midGet` 里有个裸调用：

```java
public T midGet(Long id) {
    return genericGetById(id);   // 裸调，不带 this
}
```

这条 self 边指向 `OrderService#genericGetById`，但这个节点不存在——调用图里没有它。逆向追链到这里就断了。

**修法**：调用图建完后扫一遍所有边的目标，目标节点不存在的，按继承解析补出它的下游（方法体从父类拿，绑定从子类视角折），不动点扩到不再增长。

最终链路基类的 `genericGetById` 节点被补建，`OrderService#midGet → OrderService#genericGetById → OrderMapper#selectById` 整条链通了。

Mapper 侧同理：

```java
public interface SuperMapper<T> extends BaseMapper<T> {}
public interface OrderMapper extends SuperMapper<Order> {}
```

`OrderMapper` 的实体要沿接口链折到 `Order`，和 Service 那条链共用同一套折叠逻辑。

### 诚实的边界

只有一种情况真的追不了：子类也是 `extends Base<T>`，一路上去没有任何一层给 `T` 实参。静态文本里就是没有 `T` 的信息，语义上不可知。

---

## 二、运行期拼参：别整块丢，留个骨架

JdbcTemplate 的 SQL 拼参数是静态分析的经典翻车现场：

```java
jdbcTemplate.queryForList("SELECT id, nickname FROM users WHERE id = " + userId);
```

`userId` 是方法参数，值运行期才进来。旧版的拼接扫描器一遇到不可解析的标识符就 break，整条 SQL 从地图里消失。

**但「值不可知」不等于「整条 SQL 无价值」。** `users` 表、`id` 和 `nickname` 列都是静态可见的。如果 `impact('User')` 漏掉这个调用点，就是实打实的漏报——你以为改 `users.nickname` 不影响这个接口，实际上影响。

### 核心设计：不可解析片段降级为 `?`

新扫描器不再遇到未知就停。字面量、可解析的常量（局部 final、类 static、跨类常量）照旧拼；方法参数、方法调用返回值、三元、括号表达式这些静态拿不到的成分，统一折成一个 `?`：

```
SELECT id, nickname FROM users WHERE id = ?
```

四个实现细节：

**1. 括号平衡跳过**

```java
"... WHERE id = " + normalize(userId)
```

`normalize(userId)` 整体归一个 `?`，不拆里面的参数。扫描器遇到 `(` 就配对跳到对应的 `)`，整个调用当一个原子处理。

**2. 相邻 `?` 合并**

连续多个运行期片段只留一个 `?`，不产出 `WHERE id = ? AND name = ? ?` 这种怪东西。

**3. 骨架照旧校验**

关键字（select/insert/update/delete）、表名、列名直接在带 `?` 的骨架上跑，归因逻辑完全不用改。`?` 对表列归因没有任何影响。

**4. 局部变量传参也收**

```java
String sql = "SELECT id, nickname FROM users WHERE id = " + userId;
jdbcTemplate.queryForList(sql);
```

旧版局部 `sql` 变量因为右值有运行期成分，整块放弃。新版产出 `(骨架, has_runtime_param=True)`，jdbc 调用继承这个标记。

三种形态（参数内联、方法返回值、局部变量传参）走同一套扫描器，输出一致。

### 输出提示

记录里多了个 `has_runtime_param` 字段，markdown 和 MCP 三个工具（`trace_call` / `find_sql` / `impact`）在 SQL 后面加一句提示：

> ⚠️ 含运行期拼参（`?` 为静态不可知值，值本身拿不到；表/列归因仍有效）

不隐瞒，也不夸大。

### 诚实的边界

`?` 位置上的运行期值本身静态就是拿不到的——这个不骗自己。能给的是骨架、表、列，以及「这里有个运行期参数」的标记。

---

## 三、效果

demo 项目加了 4 条路由覆盖这两个场景，路由总数从 44 到 48；断言加到 7.50，全量回归 + 多项目模式都绿。

| 场景 | 旧版行为 | v0.2.1 行为 |
| --- | --- | --- |
| `extends AbstractBase<M, T>` 自定义泛型基类 | 链路断在基类 | M/T 沿继承链折叠，接到具体 Mapper |
| `SuperMapper<T> extends BaseMapper<T>` 接口链 | 实体归因失败 | 沿接口链折到具体实体 |
| SQL 拼方法参数 | 整条 SQL 丢弃 | 骨架 `WHERE id = ?`，表/列归因保留 |
| SQL 拼方法返回值 | 整条 SQL 丢弃 | 同上 |
| 运行期值拼进局部变量再传参 | 整条 SQL 丢弃 | 同上，标记随变量继承 |

---

## 写在最后

正则解析 Java 听起来很野，但实际项目里 80% 的代码都是套路化的写法——泛型基类、工厂方法、Wrapper 链、Example 条件。把这些套路逐个吃透，覆盖度就很可观。剩下 20%（内部类、Lombok 生成方法、注解处理器产物）要靠 AST 或增量编译，那是另一条路了。

代码在 [ContextGate](https://github.com/23512478/ContextGate)（MIT，零依赖纯标准库），v0.2.1 已发版。你的项目里有这两种写法的话，跑一把 `python analyzer/framework_map.py <你的项目>` 试试，漏了提 issue。

---

**如果这篇对你有启发，欢迎点赞 / 收藏 / 关注。有问题评论区聊。**
