# 纯正则打不过真 AST？ContextGate 的「可选桥接后端」是怎么设计的

> 分析器靠纯正则跑了七轮真实项目，诚实清单上的硬边界一直没动。第八轮我把 JavaParser 请了进来——但没有重写，没有引依赖，正则引擎还是默认后端。这篇讲清楚为什么这么选、怎么接的、以及踩了哪些坑。

做 [ContextGate](https://github.com/23512478/ContextGate) 最开始有个很硬的自我约束：**零依赖纯标准库**。一个 Python 文件，拷走就能跑，不需要 pip install，不需要 Java 环境。

前七轮靠正则 + 线性扫描，把 Spring Boot + MyBatis(-Plus) 的调用链解析做到了相当完整的程度：53 路由 demo、28 个真实项目练兵。但诚实清单上一直躺着几条「静态文本语义不可知」的边界——纯形参泛型绑定、复杂内部类、正则折不动的多层泛型。

第八轮，我把 JavaParser 请了进来。但怎么请，是个需要想清楚的问题。

---

## 一、正则的天花板在哪

先说清楚正则到底卡在哪，不是「正则不精确」这种虚词。

### 1. 嵌套泛型实参

正则解析 `extends` 声明时，能拿到泛型实参的**原文**：

```java
public class OrderServiceImpl
    extends AbstractOrderService<OrderMapper, Order> { }
```

这里的实参是简单类名，正则可以折。但真实项目里会遇到：

```java
public class XxxServiceImpl
    extends BaseManager<
        SuperMapper<OrderMapper>,   // 嵌套
        Order                       // 多层透传
    > { }
```

`SuperMapper<OrderMapper>` 整体是 M 位的实参，正则的尖括号配对是字符级的，遇到嵌套两层以上就开始犯错——要么切多了，要么把 `>` 当普通字符。

### 2. 字段类型的符号求解

```java
@Autowired
private OrderService orderService;   // 简单名，正则能查
@Autowired
private com.foo.service.OrderService orderService;  // 全限定名，要剥
private S service;                   // 泛型变量，要沿继承链折
```

前两种正则勉强能处理，第三种要配合继承链做 BFS 折叠——单层、两层没问题，中间夹三四个泛型基类、类型变量还改名（`T` → `TT` → `M`）的时候，正则的字符替换很容易折不干净，留下裸标识符。

### 3. 内部类和方法内定义

正则按文件扫，一个 `.java` 文件里的顶层类能收，**方法内匿名内部类、静态内部类的方法体**基本收不全。正则没有「作用域」概念，括号配对能定位类体，但内部类方法和外部类方法的字段归属会串。

这三类问题的共同点：**不是某条规则没写，而是字符级解析没有语法树，本质上做不到 100% 正确**。

---

## 二、为什么不直接重写成 AST

既然正则有天花板，最直觉的方案是重写：用 javaparser（Java 侧）或 tree-sitter（多语言）做真 AST 解析，一步到位。

我没这么做，三个原因：

1. **零依赖是这个工具的分发优势**。MCP Server 要配置到用户的 Trae/Cursor 里，分析器越简单越好。`pip install` 一堆东西、要求 Java 环境，都会抬高试用门槛。
2. **正则在 80% 场景已经够准**。实测 RuoYi-Vue 这种标准三层架构，桥接前后调用边**零差异**——正则把套路化写法吃透后，AST 没有额外信息可补。
3. **AST 解析器本身也有失败模式**。JavaParser 符号求解器需要类型求解环境，项目依赖的 Spring/MyBatis jar 不在 classpath 里时，外部类型一样解不出。它不是银弹。

所以结论是：**做一个可选的桥接后端，正则是默认，AST 是增强；桥接不可用时静默降级，用户甚至感知不到**。

---

## 三、架构：两个进程，一段 JSON

整体数据流：

```
Java 源码
   │
   ├── 正则引擎（默认，零依赖）─────────┐
   │                                    ├── 合并 → framework_map.json/.md
   └── JavaParser 桥接（可选，增强）────┘
         Java 进程输出 JSON
```

### 为什么是「Java 进程输出 JSON」而不是 Python 直接调

JavaParser 是 Java 库，Python 没法直接调。可选方案有 JNI、JPype、GraalVM——全都要装东西，违背可选原则。

最终方案土但稳：

- 一个单文件 `JavaBridge.java`（约 200 行）
- 用 `javac` 编译成 class
- Python 侧 `subprocess.run(["java", "-cp", ..., "JavaBridge", srcRoot, outJson])`
- 读 JSON，完事

进程间通信就是临时文件里的一段 JSON，没有服务、没有端口、没有长驻进程。一次分析跑一次，跑完即退。

### 符号求解器怎么配（关键决策）

JavaParser 真正有价值的是 `JavaSymbolSolver`——它能告诉你一个表达式的**声明类型**。但符号求解需要知道类型在哪：

```java
CombinedTypeSolver ts = new CombinedTypeSolver();
ts.add(new ReflectionTypeSolver(false));       // JDK 类型
for (Path p : sourceRoots) {
    ts.add(new JavaParserTypeSolver(p.toFile())); // 项目源码
}
```

**故意不加 Maven classpath 解析**。这意味着：

- 项目内部类的泛型绑定、字段类型、调用接收者 → 能解（这正是正则的盲区）
- `IService`、`BaseMapper` 这种外部 jar 里的类型 → 解不出，返回空

这是有意的取舍。外部框架类型本来就不需要桥接补——正则分析器对 Spring/MP 的内置行为有专门的规则（`_SERVICE_BUILTIN_MAP` 等）。桥接只负责项目内部，边界清晰。

### 桥接输出什么

每个类输出：

```json
{
  "fqn": "com.demo.controller.WidgetController",
  "name": "WidgetController",
  "extends": [{
    "raw": "BaseController",
    "args": ["WidgetService", "Widget"],
    "resolved": "com.demo.controller.base.BaseController<com.demo.service.WidgetService, com.demo.entity.Widget>"
  }],
  "fields": [{
    "name": "service",
    "type": "S",
    "resolved": "com.demo.service.WidgetService"
  }],
  "methods": [{
    "name": "add",
    "calls": [{
      "name": "save",
      "scope": "service",
      "recv_type": "com.demo.service.WidgetService",
      "decl_type": "com.baomidou.mybatisplus.extension.service.IService"
    }]
  }]
}
```

`resolved` 字段是核心——符号求解器折完泛型后的**全限定具体类型**。正则要沿继承链做 BFS 折叠的东西，JavaParser 一行 `type.resolve().describe()` 就给了。

---

## 四、Python 侧的三个补强点

桥接数据不是替代正则结果，而是在正则有缺口的地方补。三处：

### 1. extends 泛型实参

正则的 `extends_heads` 存的是实参原文，遇到嵌套泛型可能折不动。桥接的 `resolved` 给出全限定具体类型时，换掉：

```python
for i, (root, args) in enumerate(cls.get("extends_heads") or []):
    for be in bc.get("extends", []):
        if _simple_of(be.get("resolved", "")) != root:
            continue
        resolved_args = [_simple_of(a) for a in _bridge_type_args(be["resolved"])]
        # 桥接自己都没解成具体类型的（比如 extends Base<T>），别动
        if resolved_args and not any(a in own_params for a in resolved_args):
            cls["extends_heads"][i] = (root, resolved_args)
```

注意那个守卫：**桥接解出来还是本类类型变量的，绝不替换**。桥接也有解不出的时候（外部基类），这时候正则原文反而更有信息。

### 2. 字段类型

字段声明类型折泛型后正则可能留裸变量，桥接的 `resolved` 是具体类型：

```python
for bf in bc.get("fields", []):
    rt = bf.get("resolved", "")
    if rt and bf["name"] in (cls.get("field_full") or {}):
        simple = _simple_of(rt)
        if simple and simple != "Object" and simple in by_simple:
            cls["field_full"][bf["name"]] = simple
```

这里踩过一个低级坑：第一次写成了改 `fields` 字典，但实际消费字段类型的 `field_type_of` 读的是 `field_full`——改错地方等于没改。

### 3. 调用接收者兜底（最有价值）

`resolve_callees` 解析一个 `xxx.method()` 调用的接收者类型，有两条正则路径：

1. 字段表（注入字段）
2. 方法内局部变量表（含 `new`、工厂方法）

两条都失败时，原来直接放弃——「静态调用/运行期才解析的接收者，不追」。现在加第三道：

```python
if _BRIDGE_CALLS:
    bt = _BRIDGE_CALLS.get((target.get("fqn", ""), mname, field, cmethod))
    if bt:
        bcls = by_simple.get(bt)
        final_cls = by_simple.get(impl_of.get(bt, bt))
        if (bcls and (bcls["is_mapper"] or bcls["is_service_impl"] or bcls["kind"] == "interface")
                and (not final_cls or final_cls["kind"] != "enum")):
            emit(bt, cmethod, False)
```

桥接索引的 key 是 `(类fqn, 方法名, scope尾段, 调用名)`——`this.userService.save()` 里 scope 取尾段 `userService`，直接查符号求解的类型。

---

## 五、踩的坑：桥接不是开了就好

第一次在 mall4j 上开桥接，调用边从 864 涨到 **1021**，看着很美，仔细一看新增的 158 条：

```
AddrController#addAddr -> AddrParam#getAddrId
BasketServiceImpl#addShopCartItem -> ChangeShopCartParam#getCount
BasketServiceImpl#addShopCartItem -> ChangeShopCartParam#getSkuId
AdminLoginController#login -> CaptchaAuthenticationDTO#getUserName
...
```

全是 **DTO/Param 对象的 getter 调用**。这些是数据存取，不是框架链路，收进来全是噪音——逆向索引和影响面分析会被污染得一塌糊涂。

### 坑 1：白名单过滤

正则路径里有个 `local_type_ok` 过滤实体和 Example，但桥接兜底路径第一版没加类型限制。修正：桥接解出的接收者**只认 mapper / service / 接口**三种，DTO、VO、Param、枚举一律不收。

### 坑 2：枚举 implements 接口

加了白名单后 youlai-boot 冒出两条：

```
Result#result -> ResultCode#getCode
Result#result -> ResultCode#getMsg
```

`ResultCode` 是个枚举：

```java
public enum ResultCode implements IResultCode, Serializable { ... }
```

桥接解出接收者是接口 `IResultCode`，白名单放行；但 `emit` 里有个归一化逻辑——接口会通过 `impl_of` 映射到实现类，而枚举 implements 接口也被当成「实现」收进了 `impl_of`，最终边落到了枚举上。

修法：emit 之前检查**归一化后**的目标类，是枚举就丢弃。

### 坑 3：一条「丢失」的边其实是误报被纠正

对比桥接前后，mall4j 有一条边「丢了」：

```
ProdCommController#getProdCommPage
  旧: -> ProdCommServiceImpl#getProdCommDtoPageByUserId
  新: -> ProdCommServiceImpl#getProdCommPage
```

查源码，Controller 里写的是：

```java
return ServerResponseEntity.success(prodCommService.getProdCommPage(page, prodComm));
```

调的就是 `getProdCommPage`。旧正则在重载方法间匹配错了目标，桥接用符号求解纠正成正确的那个。**这不是回归，是修对了**——但如果不逐条核对，很容易被「边数少了」的表象误导。

---

## 六、实测：什么项目受益最大

四个项目开桥接前后对比：

| 项目 | 架构风格 | 调用边变化 | 逆向索引 | 说明 |
| --- | --- | --- | --- | --- |
| **AgileBoot** | DDD 分层 | +4，3 条误报被纠正 | **13 → 36** | 提升最大 |
| mall4j | 标准三层 + MP | +1 | 240 | 桥接纠正 1 条重载误匹配 |
| RuoYi-Vue | 标准三层 | 0 | 155 | 零差异，正则已够准 |
| youlai-boot | 标准三层 | 0（修噪音后） | 74 | 零差异 |

规律很清楚：

- **越标准的三层架构，桥接越没有用武之地**——注入字段都是简单类型，正则第一条路径就命中了
- **DDD / 多层泛型基类的项目收益最大**——AgileBoot 的 ApplicationService → ModelFactory → Model 链路里，大量字段类型要折多层泛型，正则折不动，桥接直接解

这也验证了「可选增强」的定位：不增加标准项目的任何成本，只在正则真不够的地方发力。

### 顺带修的崩溃

第七轮还暴露过一个 `_example_defuse` 的解包崩溃——两个提前返回的分支写了 `return []`，调用方期望两个返回值 `(records, props)`，litemall/mall/xmall 三个项目直接跑挂。这种是纯手滑 bug，和桥接无关，一并修了。

---

## 七、怎么用

桥接默认是**自动检测**的：Java 可用、`analyzer/java-bridge/out/JavaBridge.class` 存在，就自动启用；任何一步失败静默回退纯正则，分析不会中断。

首次使用跑一次安装脚本（下载 4 个 JAR + javac 编译，JAR 不进 git）：

```bash
python analyzer/java-bridge/setup.py
```

不想用桥接（比如排查问题时要对比纯正则结果）：

```bash
# Windows
set CG_NO_BRIDGE=1
# Linux/Mac
export CG_NO_BRIDGE=1
```

跑分析时 stdout 会提示：

```
JavaParser 桥接已启用（388 类，1971 条调用接收者）
[OK] 扫描 385 个 Java 文件，385 个类，203 条路由
```

---

## 诚实的边界

桥接缩小了盲区，但没有消灭盲区。剩下的硬边界：

1. **外部 jar 里的类型仍然解不出**。桥接只配了项目源码 + JDK 的类型求解器，Spring/MP 框架类不在 classpath 里。目前够用是因为框架内置行为走专门规则，但如果项目重度依赖某个陌生 starter 的泛型基类，桥接也帮不上。
2. **`new` 出来的非 Spring 对象内部调用不追**。AgileBoot 那种 `new UserModel(...)` 的领域对象，方法里再调注入的 service，需要跨「对象图」追踪——桥接能解字段类型，但对象不是 bean、构造参数传播不做，仍然断。
3. **桥接有性能成本**。mall4j（385 个文件）桥接阶段大约多花几秒到十几秒。大项目（halo 那种 1000+ 文件）会更明显，这是子进程启动 + 全量符号求解的固有开销。
4. **要求本机有 JDK**（不是 JRE，要 `javac` 编译桥接器；运行时只要 `java`）。Java 8+ 即可，JavaParser 3.25.x 向下兼容。

---

## 写在最后

这轮做完，对「正则 vs AST」的体感比开始时清晰多了：**它们不是替代关系，是成本和精度的不同档位**。

正则档：零依赖、毫秒级、80% 场景够用，代价是复杂语法要逐个补规则。
AST 档：精确、有作用域和符号信息，代价是环境、依赖、性能。

ContextGate 的做法是把两个档位都做进去，默认低档（零门槛），环境允许时自动升高档（补盲区），升不上去也不影响低档工作。用户不需要理解这套机制——跑一把，输出变准了就行。

代码在 [ContextGate](https://github.com/23512478/ContextGate)（MIT）。如果你的项目是 DDD 分层或有多层泛型基类，装桥接跑一把对比看看；标准三层项目也欢迎验证「零差异」——不产生噪音边和提升覆盖率同样重要。

---

**如果这篇对你有启发，欢迎点赞 / 收藏 / 关注。有问题评论区聊。**
