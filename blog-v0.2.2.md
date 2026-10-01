# 零依赖静态分析：让 AI 看懂自研组合路由注解与空类继承 CRUD

> 项目里没有一个标准 `@RestController`，Controller 全被框架自研的组合注解包着，连类体都是空的——纯正则 + 线性扫描的分析器怎么把这些「看起来没有任何路由信息」的类还原成 137 条可追溯的 HTTP 接口？

做 [ContextGate](https://github.com/23512478/ContextGate) 的目标一直很明确：给一个 Spring Boot + MyBatis 项目，吐出「HTTP 接口 → Service → Mapper → 表/列」的完整调用链地图。前几轮把泛型绑定、运行期 SQL 拼接这些硬骨头啃下来了，回归 demo 也稳在 49 条路由全绿。

但一上真实项目就翻车了——前五轮只在 Guns 一家上见过自研路由注解，而且还是方法级的 AliasFor 形态。第六轮拉了 cool-admin、jetlinks、lamp-boot、jeesite5、erupt、hsweb 六个项目练兵，暴露了三种之前完全没覆盖的写法。这篇把设计思路和实现细节记下来。

---

## 一、组合注解：类上没有 `@RestController` 怎么办

标准 Spring MVC 的 Controller 长这样：

```java
@RestController
@RequestMapping("/api/users")
public class UserController { ... }
```

分析器用正则匹配 `@RestController` / `@Controller`，命中就认作 Controller，再从 `@RequestMapping` 里抠类级路径前缀。这套逻辑对 Spring 官方注解百试百灵。

**但真实项目里的 Controller 往往长这样：**

```java
// cool-admin
@CoolRestController(api = {"add", "delete", "update", "page", "list", "info"})
public class AdminSpaceTypeController extends BaseController<SpaceTypeService, SpaceType> {
}

// jetlinks / lamp-boot 风格
@RestController        // ← 这是个自定义注解，不是 Spring 的！
@RequestMapping("/device")
public class DeviceController { ... }

// 还有的包成一层
@ApiRestController("/order")
public class OrderController { ... }
```

第一眼看上去 `@CoolRestController`、`@ApiRestController` 完全是陌生注解，正则不认识，直接判「不是 Controller」，整个类零路由。更坑的是 `@RestController` 这个名字可能根本不是 Spring 的——有些框架自己定义了一个同名注解，元注解才是真的 Spring `@RestController`。

### 核心设计：扫元注解，闭包折叠

关键洞察：**自定义组合注解的元注解链里一定有 Spring 的 `@RestController` / `@RequestMapping`**。框架作者不可能重新发明一套 MVC 机制，他们只是用 Java 注解的元标注能力把 Spring 注解包了一层（甚至好几层），加上自己的属性（比如 cool 的 `api` 白名单）。

所以思路不是「枚举所有框架的注解名」，而是**扫项目内所有 `@interface` 定义，看它的元注解里有没有 Spring 的 Controller / RequestMapping**：

```python
def scan_meta_annotations(src_roots):
    ann_metas = {}
    for 每个 .java 文件:
        clean = strip_code(raw)          # 抹掉字符串/注释
        for 每个 @interface Xxx:
            head = 注解定义前面 800 字符   # 元注解都写在 @interface 上方
            ann_metas[Xxx] = 上面所有 @注解名

    # 闭包：A 标了 B，B 又标了 @RestController → A 也是
    while changed:
        for metas in ann_metas.values():
            for sub in list(metas):
                if sub in ann_metas:
                    metas |= ann_metas[sub]

    ctrl = {n for n, ms in ann_metas.items()
            if ms & {"RestController", "Controller"}}
    rm   = {n for n, ms in ann_metas.items()
            if "RequestMapping" in ms}
    return ctrl, rm
```

扫完之后，凡是元注解链最终落到 `@RestController` / `@Controller` 的自定义注解，标在类上就认作 Controller；元注解链含 `@RequestMapping` 的，其 `value` / `path` 属性就是类级前缀。

### 一个隐蔽的坑：别取第一个字符串

Guns 的 `@GetResource` 方法级注解吃过这个亏：

```java
@GetResource(name = "新增空间类型", path = "/space/type/add")
public R add(...) { ... }
```

`name` 写在 `path` 前面，如果偷懒取「第一个字符串字面量」，路径就变成了 `"新增空间类型"`。

类级组合注解更危险，因为它们常带数组属性：

```java
@CoolRestController(api = {"add", "delete", "update", "page", "list", "info"})
```

如果回退到第一个字符串，类前缀就成了 `"add"`，拼出来的路由是 `/add/add`——完全错误。所以**组合注解的前缀只认显式 `path=` / `value=` 属性**，没有就走约定推导（见第三节），绝不取第一个字符串。

---

## 二、空类继承 CRUD：方法体全在泛型基类，子类一个 mapping 都不写

认出来了 `AdminSpaceTypeController` 是 Controller，但类体是空的——一个 `@GetMapping` / `@PostMapping` 都没有。路由从哪来？

```java
@CoolRestController(api = {"add", "delete", "update", "page", "list", "info"})
public class AdminSpaceTypeController
    extends BaseController<SpaceTypeService, SpaceType> {
    // 空的！
}
```

基类 `BaseController<S, T>` 里才是真正的 handler：

```java
public abstract class BaseController<S extends IService<T>, T> {
    @Autowired
    protected S service;

    @PostMapping("/add")     public R add(T entity)    { service.save(entity); return R.ok(); }
    @PostMapping("/delete")  public R delete(Long[] ids){ service.removeByIds(Arrays.asList(ids)); return R.ok(); }
    @PostMapping("/update")  public R update(T entity) { service.updateById(entity); return R.ok(); }
    @GetMapping("/page")     public R page(Page<T> p)  { return R.ok(service.page(p)); }
    // ...
}
```

Spring MVC 在运行时会把子类注册成这些 handler 的实际接收者——`POST /admin/space/type/add` 实际进的是 `AdminSpaceTypeController` 继承来的 `add` 方法。**但静态分析如果只扫子类自身的方法，就会得到零路由。**

### 核心设计：沿继承链收集父类 handler

对每个 Controller，沿 `extends` 链往上走，把父类（以及祖父类……）所有带 `@*Mapping` 的方法都收进来，子类 override 同名的不重复：

```python
own_names = {m["name"] for m in c["methods"]}
pc, pguard = c, set()
while pc is not None and pc["name"] not in pguard:
    pguard.add(pc["name"])
    par = by_simple.get(父类名)
    if not par: break
    for meth in par["methods"]:
        if meth["http"] and meth["name"] not in own_names:
            emit_route(meth, owner=par)
            own_names.add(meth["name"])   # 再上层祖父类同名方法不重复收
    pc = par
```

### 节点键按子类视角，泛型实参绑子类

路由收集到了，但调用链还有个坑：`add` 方法体写在 `BaseController` 里，里面调的是 `service.save(entity)`。`service` 的类型是 `S`，`S` 的上界是 `IService<T>`——这两个都是形参。

如果按「方法声明类」（`BaseController`）的视角解析泛型，`S` 和 `T` 都是不可知的，链路断在 `service.save()`。

**正确视角是子类**：`AdminSpaceTypeController extends BaseController<SpaceTypeService, SpaceType>` 把 `S=SpaceTypeService`、`T=SpaceType` 钉死了。所以调用图补建继承路由节点时，按**子类的泛型绑定**去解析基类方法体里的 `service.save()`：

```
AdminSpaceTypeController#add
  └─ SpaceTypeServiceImpl#save       ← S 折成 SpaceTypeService
      └─ SpaceTypeMapper#insert      ← T 折成 SpaceType
```

这正好复用了上一轮做的「带命名空间的泛型绑定折叠」——`("BaseController", "S")` 从 `AdminSpaceTypeController` 的实参里折到 `SpaceTypeService`，`("BaseController", "T")` 折到 `SpaceType`。继承链上十层基类都叫 `S`/`T` 也不怕，各归各的命名空间。

路由记录里多了个 `handler_owner` 字段，区分「这个 handler 的方法体实际写在哪个类」，方便调试和展示。

---

## 三、cool-admin 约定前缀：包名和类名里藏着路径

`@CoolRestController` 经常**不写 `value`**，类前缀从哪来？

```java
package com.cool.modules.space.controller.admin;

@CoolRestController(api = {"add", "delete", "update", "page", "list", "info"})
public class AdminSpaceTypeController extends BaseController<...> { }
```

cool-admin 的 `AutoPrefixUrlMapping` 用一套固定规则从包名和类名推导前缀：

1. 包名 `modules` 之后去掉 `.controller`：`space.admin`
2. 前两段互换：`admin.space`
3. 类名剥 `Controller` 后缀：`AdminSpaceType`
4. 再剥掉前缀里已出现的驼峰词（`Admin`、`Space`），剩 `Type`
5. 拼起来：`/admin/space/type`

分析器忠实复刻了这套规则（包括 `ConvertUtil` 的驼峰切分），推导不了就返回 `None` 走兜底。

### `api` 白名单：没声明的方法不注册路由

`@CoolRestController(api = {"add", "delete", "update", "page", "info"})` 里没列 `list`，那基类的 `@PostMapping("/list")` 就**不应该**注册成路由——框架运行时会按这个白名单过滤。

`emit_route` 里加了一道判断：cool 自动前缀模式下，标准 CRUD 名（add/delete/update/page/list/info）如果不在 `api` 白名单里，直接跳过。实测 `AdminSpaceTypeController` 有 list 路由而某些只声明了 add 的子类没有，和框架行为一致。

---

## 四、顺带修了两个埋了好几轮的坑

练兵过程中暴露了两个之前没触发的问题，顺手修了。

### RecursionError：工厂描述符互相递归

cool-admin / hsweb / jetlinks 三个项目一跑就崩：

```
RecursionError: maximum recursion depth exceeded
```

根因是 `resolve_local_desc`（解析局部变量类型描述符）和 `field_type_of`（解析字段类型）互相调用——A 需要 B 的结果，B 又需要 A 的结果，没有终止条件。

修法很直接：两个函数都加**访问守卫**（按 `(desc, owner类名)` 去重）和**16 层深度上限**，超界返回 `None`。性能影响忽略不计，崩溃彻底消失。

### XML SQL 合并的半截账

上一轮为了让 markdown 渲染能看到 XML 里的 SQL，把 `xml_stmts` 合并进了 `by_simple` 的 mapper 方法，但**只同步了 `(kind, text)`**，`sql_tables` / `sql_columns` / `sub_selects` 这三个索引还是空的。

后果：JSON 里 XML 自定义 SQL 的表/列全空，`impact` 工具按列过滤时全部漏报；`<association select="...">` 的 N+1 子查询标注也丢了。demo 里 resultMap JOIN 命中 `content` 列、懒加载 `selectUserById` 这两个断言实际是红的——之前只看尾部输出漏检了。

修法：合并时把三个索引一并补上，JSON 序列化透传 `sub_selects`。XML 自定义 SQL 的列触碰、N+1 标注恢复正常。

---

## 五、效果

demo 新增 8 个文件复刻 cool-admin 形态：`@AdminApi` 元注解组合 + 空类 `WidgetController extends BaseController<WidgetService, Widget>` + 泛型 Service 接口/实现/MP Mapper，产生 4 条路由。

| 路由 | 调用链 |
| --- | --- |
| `POST /widget/add` | `WidgetController#add → WidgetServiceImpl#save → WidgetMapper#insert` |
| `POST /widget/update` | `WidgetController#update → WidgetServiceImpl#update → WidgetMapper#updateById` |
| `POST /widget/delete` | `WidgetController#delete → WidgetServiceImpl#delete → WidgetMapper#deleteById` |
| `GET /widget/page` | `WidgetController#page → WidgetServiceImpl#page → WidgetMapper#selectList` |

基线从 49 路由 / 6 Mapper / 5 实体 → **53 / 7 / 6**，断言加到 7.52，全量回归 + 多项目模式全绿。

六个训练项目全部无崩溃：

| 项目 | 路由数 | 说明 |
| --- | --- | --- |
| cool-admin-java | 137 | 约定前缀 + 空类继承 CRUD 全接通 |
| jetlinks-community | 324 | 类级元注解组合 |
| jeesite5 | 317 | 组合注解 |
| erupt | 141 | `@Erupt` 实体运行时动态注册 REST，静态分析硬边界 |
| lamp-boot | 92 | `@ApiRestController` 元注解 |
| hsweb-framework | 37 | WebFlux 框架库本体（非应用），少属正常 |

---

## 诚实的边界

有两种情况静态分析真的搞不定，不骗自己：

1. **`@Erupt` 式运行时动态注册**：erupt 框架在实体类上标 `@Erupt`，运行时通过 `HandlerInterceptor` 动态把 CRUD 接口挂上去。源码里没有任何 `@*Mapping`，静态文本里就是没有路由信息。这种只能靠运行时抓取或框架特定的注解处理器，纯正则做不到。

2. **元注解链跨 jar 包**：`scan_meta_annotations` 只扫**本项目源码**里的 `@interface`。如果组合注解定义在第三方依赖里（比如引入了某个 starter），分析器看不到它的元注解，就认不出来。目前要求注解定义在项目源码内（绝大多数自研框架满足）。

---

## 写在最后

正则解析 Java 听起来很野，但真实项目里 80% 的代码都是套路化的写法——泛型基类、组合注解、约定前缀、Wrapper 链。把这些套路逐个吃透，覆盖度就很可观。

自研路由注解这一轮的核心经验是：**别去枚举框架，去识别机制**。Spring MVC 的机制是「元注解链上一定有 `@RestController` + `@RequestMapping`」，不管外面包了多少层自定义注解、加了多少花里胡哨的属性，机制不变。顺着机制做，一次覆盖一大片框架。

代码在 [ContextGate](https://github.com/23512478/ContextGate)（MIT，零依赖纯标准库），v0.2.2 已合并。你的项目里有自研组合注解或空类继承 CRUD 的写法，跑一把 `python analyzer/framework_map.py <你的项目>` 试试，漏了提 issue。

---

**如果这篇对你有启发，欢迎点赞 / 收藏 / 关注。有问题评论区聊。**
