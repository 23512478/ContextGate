# 微服务的调用链终于能跨进程了：静态分析器硬刚 yudao 的 Feign 三层常量链

> ContextGate 第九轮。前面八轮把单进程 Spring Boot 项目的链路摸了个底朝天，但有个边界一直绕着走：微服务。你在 yudao-cloud 里追一条调用链，追到 `permissionApi.getUserRoleIdListByRoleIds()` 就断了——这是个 Feign 远程调用，真正干活的代码在另一个服务的 HTTP 接口里。这轮把这条边补上了：yudao 新增 115 条 `/rpc-api/**` 契约路由、识别 47 个 Feign 客户端，12 个非微服务项目回归路由数零变化。踩的坑一个比一个隐蔽，记下来。

## 📌 这轮要解决什么

[ContextGate](https://github.com/23512478/ContextGate) 干的事一句话：丢给它一个 Spring Boot + MyBatis 项目，静态分析出一条链：

```
HTTP 路由 → Controller → Service → Mapper → SQL → 表/列
```

前八轮这条链在**单进程**内已经相当完整，直到拿 yudao-cloud（40 个 Maven 模块的微服务全家桶）一练，断链断得整整齐齐：

```
BpmTaskCandidateRoleStrategy#calculateUsers
    └─ permissionApi.getUserRoleIdListByRoleIds(roleIds)   ← 链在这断了
```

`permissionApi` 是个 `@FeignClient` 接口，这个调用本质是一次 HTTP 请求，真正执行逻辑的是 system 服务里的 `PermissionApiImpl`。分析器要回答三个问题：

1. 这玩意是个远程调用，目标服务叫什么？
2. HTTP 请求的确切方法和路径是什么？
3. 目标服务的代码也在同一个仓库里（yudao 是 monorepo），能不能继续往里钻？

真正动手才发现，这三个问题没有一个是"识别个注解"那么简单。

---

## 一、先看 yudao 的 Feign 到底长什么样

如果 Feign 接口都写得这么朴素，这轮一天就能收工：

```java
// 想象中的美好世界
@FeignClient(name = "system-server")
public interface DeptApi {

    @GetMapping("/dept/get")
    DeptRespDTO getDept(@RequestParam("id") Long id);
}
```

但 yudao 的真实代码是这样的，常量一共套了**三层**：

```java
// 第一层：公共模块的接口（注意，是 interface！）
public interface RpcConstants {
    String RPC_API_PREFIX = "/rpc-api";
}

// 第二层：每个 *-api 模块各自的 ApiConstants
public interface ApiConstants {
    String NAME = "system-server";
    String PREFIX = RpcConstants.RPC_API_PREFIX + "/system";
}

// 第三层：Feign 接口自己又拼一段
@FeignClient(name = ApiConstants.NAME)
public interface DeptApi {

    String PREFIX = ApiConstants.PREFIX + "/dept";

    @GetMapping(PREFIX + "/get")
    Long getDept(@RequestParam("id") Long id);
}

// 服务端：注解全在接口上，实现类只有 @Override
@RestController
public class DeptApiImpl implements DeptApi {

    @Resource
    private DeptService deptService;

    @Override
    public Long getDept(Long id) {
        return deptService.getDept(id);   // ← 真正的逻辑在这
    }
}
```

最终的 HTTP 路径是 `/rpc-api/system/dept/get`，但这行字符串**在整个代码库里根本不存在**——它是四个常量跨三个类拼出来的。分析器拿不到这个字符串，跨服务边就是残的：你只能告诉用户"这里有个远程调用"，说不出去哪。

于是这轮的核心任务变成了一个编译器活：**常量折叠（constant folding）**。

---

## 二、坑一：接口里的常量，连 `static final` 都不写

分析器本来就有类常量收集能力（为了拼 SQL 片段），靠的是匹配这种声明：

```python
re.compile(r"(?:public\s+)?(?:static\s+)?(?:final\s+)?String\s+(\w+)\s*=")
```

喂给 `RpcConstants` 一看——啥也没收到。

第一个原因很恶心：**Java 接口里的字段是隐式 `public static final` 的**，所以 yudao 直接写成：

```java
public interface RpcConstants {
    String RPC_API_PREFIX = "/rpc-api";   // 连 static 都没有
}
```

这倒好办，interface 模式下放宽匹配就行。真正的麻烦是接口里还可以有 `default`/`static` 方法，方法体里也有 `String xxx = "..."`，那是局部变量不是常量，不能收。怎么区分？

**把方法体整块抹掉**。写了个 `_mask_brace_blocks`：扫一遍文本，配对的 `{ ... }` 整体替换成等长空格（正确跳过字符串和字符字面量里的括号），抹完之后剩下的顶层 `String` 声明必然是常量。

结果还是零命中。调试发现两个叠加的坑：

**坑 1a：javadoc 挡在常量前面。** 我写的边界正则是 `(?:^|;)`，意思是常量声明必须出现在开头或分号之后。但真实文本是：

```java
public interface RpcConstants {

    /**
     * RPC API 的前缀
     */
    String RPC_API_PREFIX = "/rpc-api";   // 前面是 */，不是 ; 也不是开头
```

于是先加一步"只抹注释、保留字符串字面量"的清洗，再抹方法体。

**坑 1b：最外层的类体大括号把整个类全抹了。** `_mask_brace_blocks` 喂进去的是整个类体（自带最外层 `{}`），masker 看到第一个 `{` 就忠实地把"这个块"抹到配对的 `}`——整个类体全军覆没，常量当然没了。改成只对内部文本 `body_raw[1:-1]` 做块抹除。

三个小问题叠在一起，单看任何一个都不值一提，组合起来就是半小时。最后：

```python
if kind == "interface":
    const_src = _mask_brace_blocks(strip_comments(body_raw[1:-1]))
```

`RpcConstants` 的常量终于进来了。

---

## 三、坑二：十几个模块都叫 ApiConstants，简单名空间互相覆盖

常量能收了，跑 yudao 一看折叠结果，血压上来了：

```python
system 模块 ApiConstants 的 NAME 折出来是 'pay-server'   # ？？？
```

根因：yudao 十几个模块（system、pay、infra、bpm……）**每个模块都有一个类叫 `ApiConstants`**，每个里面都有个 `NAME = "xxx-server"`。分析器为了查找快，维护了一个"简单名 → 类"的索引 `by_simple`，后扫到的 pay 模块把 system 模块覆盖了。这在单模块项目里从来不是问题，在 monorepo 里是必然踩的雷。

Java 编译器遇到 `ApiConstants.NAME` 时怎么确定是哪个类？看 **import**。所以给 `parse_java` 加了 `imports` 字段：

```java
import cn.iocoder.yudao.module.system.enums.ApiConstants;
//              ↑ 折叠常量时必须按这个 FQN 找类，而不是赌 by_simple
```

常量归属解析改成三级优先级：

```python
def _resolve_const_owner(owner_cls, simple, classes, by_simple):
    # 1. 当前类 import 了这个简单名 → 用 import 的全限定名精确命中
    # 2. 没 import 但同包下有同名类 → 同包可见
    # 3. 都没有 → by_simple 兜底（java.lang 式的同包直觉）
```

所有跨类常量解析点（Feign 折叠、全局常量折叠循环、Wrapper 内联 SQL 的常量引用）全部切到这个新函数，不留死角。改完 `NAME` 正确折成 `system-server`。

这个坑的教训：**微服务 monorepo 里，类的简单名不再唯一，任何"简单名 → 唯一实体"的假设都是定时炸弹**。

---

## 四、坑三：把四个片段折成一个字符串

常量来源齐了，写表达式折叠器 `fold_str_expr`。它要吃的输入是注解参数的原始文本：

```java
@GetMapping(PREFIX + "/get")                    // 本类常量 + 字面量
@FeignClient(name = ApiConstants.NAME)          // 跨类常量
String PREFIX = RpcConstants.RPC_API_PREFIX + "/system"  // 跨类常量 + 字面量
```

做法是把表达式切成 token（字符串字面量 / 标识符 / `+`），然后：

- 字面量直接取值；
- 不带点的标识符查本类 `static_strs`；
- 带点的 `A.B` 按上面的 import 感知解析找到归属类再查；
- 全局不动点迭代——`RpcConstants.RPC_API_PREFIX` 第一轮折好，第二轮 `ApiConstants.PREFIX` 才能折，第三层 `DeptApi.PREFIX` 要等第三轮。

遇到方法调用、`${...}` 占位符、三元运算符这些真运行期成分，**返回 None 而不是瞎编**：边照收（调用事实存在），路径位置显示表达式原文。

折完又冒出一个字符级的 bug：路径变成了这样：

```
/rpc-api/system/dept/c a n c e l - b y - s t a r t - u s e r
```

每个字符之间被插了空格。原因是字面量字符收集进 buf 后，我脑抽写了 `" ".join(buf)`——把同一个字符串的字符用空格连起来了。改成 `"".join(buf)` 就好。

还有个语义坑：分析器原有的常量拼接是 **SQL 语义**，`A + B` 中间会插空格（`WHERE a ` + `AND b` 需要空格）。但 URL 路径里空格是非法的，折出来变成 `/rpc-api /system`。最后在折叠器出口加一道：`re.sub(r"\s*/\s*", "/", s)`，把斜杠两侧的空白收掉。

最终三层折叠链贯通：

```
RpcConstants.RPC_API_PREFIX        = "/rpc-api"
ApiConstants.PREFIX                = "/rpc-api/system"
DeptApi.PREFIX                     = "/rpc-api/system/dept"
@GetMapping(PREFIX + "/get")       → /rpc-api/system/dept/get ✅
```

---

## 五、服务端：注解全写在接口上，路由怎么收

调用端搞定了，服务端还有个反直觉的点。

Spring MVC 允许把 mapping 注解写在接口上，实现类实现接口后自动继承这些路由（Spring 官方文档明确，但有个限制：**只继承方法级 mapping，接口类级的 `@RequestMapping` 不继承**）。yudao 把这个特性用到了极致——`DeptApiImpl` 上一个 mapping 注解都没有，不特殊处理的话，115 条 `/rpc-api/**` 路由一条都扫不出来。

处理逻辑：

1. 收集接口的 HTTP 契约时沿 **extends 链 BFS**（接口是多继承的，`PermissionApi extends PermissionCommonApi`，父接口的方法也是契约），子接口同名方法覆盖父接口；
2. 遍历每个 `@RestController` 的 `implements`，把契约方法安到实现类上，但有两个护栏：
   - 实现类**自己声明了**的方法才安（接口里有但没实现的方法不是 handler）；
   - 实现类用自己的 `@GetMapping` 重写了的，以本类为准；
3. 类前缀只取**实现类自己的** `@RequestMapping`，绝不取接口的类级注解（跟 Spring 行为对齐）。

收出来的路由打标记 `via: "feign-contract"`（非 Feign 的普通接口契约打 `interface-contract`），方便区分。

---

## 六、Fallback 陷阱：熔断降级类不是服务端

SpringBlade 一练，又出洋相：7 个 Feign 客户端的"服务端实现"全连到了 `XxxClientFallback` 上。

Feign 的 fallback 是熔断降级用的：远程调用失败时，**在调用方本地进程**执行的兜底逻辑。它通常也 `implements` 这个 Feign 接口，所以"找接口的实现类"时很容易第一个撞上它。但它绝对不是服务端落点——把链钻进去，语义全错。

落点选择改成优先级制：

```python
# 1. @RestController 实现类（这才是真正的服务端）
# 2. 名字不含 Fallback 的普通实现
# 3. 都没有 → 边诚实地停在接口节点（dangling），
#    但把 Fallback 类名单独列出来告诉用户"有本地降级"
```

实测 SpringBlade 的 `IStorageClient` 仓内只有一个 `StorageClientFallback`，最终报告长这样：

```
### IStorageClient → 服务 blade-seata-storage
→ ⚠️ 服务端不在本仓库（仅有熔断降级类 StorageClientFallback，
   在调用方本地执行，不当作服务端落点）
```

不编。

---

## 七、调用图：边要跨进程，但事务不能跨 HTTP

最后把语义编进调用图。一条完整的跨服务链现在长这样（JSON 里每跳都带类型）：

```
BpmTaskCandidateRoleStrategy#calculateUsers
    └─ 🌐 feign        PermissionApi#getUserRoleIdListByRoleIds
                       @ system-server  GET /rpc-api/system/permission/user-role-id-list-by-role-id
        └─ 🛂 feign_server  PermissionApiImpl#getUserRoleIdListByRoleIds
             └─ service  PermissionServiceImpl#getUserRoleIdListByRoleId
                  └─ mapper ...
```

两个设计决定：

**1. 跨服务边不直接归一化到实现类。** 旧逻辑见到接口调用会直接替换成 impl（同进程语义）。Feign 必须保留两跳：`feign` 是网络边界，`feign_server` 是对端入口。这样 MCP 渲染时才能打出"🌐 出进程"和"🛂 进对端"两个不同的标记，用户一眼知道链在哪跨了服务。

**2. 事务闭包不跨 HTTP 传播。** `@Transactional` 的 REQUIRED 传播只在同一线程同一数据源内成立，HTTP 调用出去之后，对端方法在不在事务里是对端自己的事。`tx_closure` 遇到 `feign`/`feign_server` 边直接跳过。

带来的实际收益在**逆向索引**上：改 `UserMapper#selectById` 影响哪些接口？现在答案同时包含本端入口和远程 RPC 入口：

```
UserMapper#selectById 的上游路由：
  GET /api/v1/feign/user            ← 本服务的 HTTP 入口
  GET /rpc-api/demo/user/get        ← 别的服务通过 Feign 打进来的入口
```

在 yudao 里这条能力是实打实的：system 服务改一个 Mapper 方法，bpm 服务里有多少流程在通过 Feign 依赖它，以前全靠人脑记，现在图里直接有。

---

## 八、回归：12 个非微服务项目，一个数都没变

静态分析器加规则最怕误伤。每轮的铁规矩：拿一堆真实开源项目跑数字对比。

| 项目 | 旧路由 | 新路由 | 变化 | Feign 客户端 |
|---|---|---|---|---|
| RuoYi-Vue | 147 | 147 | 0 | - |
| mall4j | 203 | 203 | 0 | - |
| litemall | 219 | 219 | 0 | - |
| youlai-boot | 93 | 93 | 0 | - |
| SpringBlade | 181 | 181 | 0 | 7（落点修正，无新路由） |
| xmall | 160 | 160 | 0 | - |
| mall | 246 | 246 | 0 | - |
| AgileBoot | 76 | 76 | 0 | - |
| jpetstore | 22 | 22 | 0 | - |
| pig | 296 | 296 | 0 | 10 |
| RuoYi-Cloud | 137 | 137 | 0 | 3 |
| newbee-mall-cloud | 68 | 68 | 0 | 3 |
| **yudao-cloud** | **2999** | **3114** | **+115** | **47（44 个仓内有实现）** |

中间还破了个案：第一版加了 `(动词, 路径)` 去重，yudao 路由反而少了 58 条。逐条核对发现这 58 条全是**不同 Controller 映射了同一路径**（yudao 的 admin/app 双端 Controller，运行期按条件加载，零条是真重复）——去重键立刻改成 `(动词, 路径, 控制器, handler)`，只防同一条路由被多收，绝不合并真实存在的两个入口。最终 yudao 是干干净净的 2999 + 115，一条没删。

顺手在 demo 夹具里加了个最小微服务样例（Feign 接口 + 三层常量 + `@RestController implements` + 调用方），MCP 测试新增一组断言：跨服务标记、路径折叠、服务端下钻、rpc-api 契约路由反查、逆向索引双端入口，全绿。

---

## 九、这轮留下的边界

诚实清单照更，不吹"微服务全支持了"：

1. **动态路径仍折不出**：`@GetMapping(path + xxx())`、`${配置占位符}`、三元表达式这类运行期拼路径，边保留（调用事实在），路径位置显示原始表达式，绝不编一个假路径；
2. **目标服务不在当前仓库时链就到接口为止**：yudao monorepo 能钻透是因为 44 个服务端实现恰好在同一棵代码树里；真·多仓库部署时，分析器只能告诉你"调了哪个服务的哪个契约"，对端代码要切到那个仓库再分析；
3. **Feign 的自定义拦截器/编码器/契约配置不追**：比如全局 `RequestInterceptor` 给路径加统一前缀这种，静态不读配置；
4. **只认声明式 `@FeignClient`**：RestTemplate/WebClient 手写的 HTTP 调用、Dubbo RPC 不在这轮范围内。

---

## 小结

九轮下来一个很深的体感：**静态分析的难度从来不在"识别语法"，而在还原编译器替你做的那些隐式事**。接口字段隐式 `public static final`、import 决定同名类归属、注解字符串在编译期被常量折叠、接口方法被实现类隐式继承——每一个单独看都是 Java 基础，组合成真实项目的写法后，正则就得一个坑一个坑地填。

好在这轮填完，yudao 的链路第一次能从一个服务的 Controller 一路追到另一个服务的 Mapper：

```
GET /bpm/...（bpm 服务）
  → BpmTaskCandidateRoleStrategy#calculateUsers
    → 🌐 system-server GET /rpc-api/system/permission/...
      → 🛂 PermissionApiImpl → PermissionServiceImpl → Mapper
```

代码都在 [ContextGate](https://github.com/23512478/ContextGate)，纯正则零 Python 依赖（JavaParser 桥接是可选增强），demo 项目 `python mcp-server/test_mcp.py` 一键体验。第十轮见。
