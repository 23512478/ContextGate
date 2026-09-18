package com.demo.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.entity.User;
import com.demo.service.OrderQuerySupport;
import com.demo.service.SupportFactory;
import com.demo.entity.UserExample;
import com.demo.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;

@RestController
@RequestMapping("/api/v1")
public class WalletController {

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private OrderQuerySupport orderQuerySupport;

    @Autowired
    private ApplicationContext ctx;

    /** Object 字段：类型运行期才能确定（initHelper 里 new 赋值）。 */
    private Object helper;

    @Autowired
    private SupportFactory supportFactory;

    /** Object 字段：工厂方法赋值（made = supportFactory.create()，按签名 ret_type 推断）。 */
    private Object made;

    /** 充值：自定义 @Update 写 wallet_balance。 */
    @PostMapping("/wallet/recharge")
    public String recharge(@RequestParam Long userId, @RequestParam BigDecimal delta) {
        userMapper.addBalance(userId, delta);
        return "ok";
    }

    /** 查余额：走 MP 内置 selectById（SELECT * 全列触碰）。 */
    @GetMapping("/wallet/me")
    public User me(@RequestParam Long userId) {
        return userMapper.selectById(userId);
    }

    /** MP 内置 count：COUNT(*) 不触碰业务列（验证列级归因收窄）。 */
    @GetMapping("/wallet/count")
    public long countUsers() {
        return userMapper.selectCount(null);
    }

    @GetMapping("/wallet/lambda")
    public List<User> byLambda(@RequestParam String nickname) {
        return userMapper.selectByNicknameLambda(nickname);
    }

    /** MBG Example 动态条件：criteria.andXxxYyy 链 + selectByExample。 */
    @GetMapping("/wallet/search-example")
    public List<User> searchExample(@RequestParam String nickname) {
        UserExample example = new UserExample();
        example.createCriteria().andNicknameEqualTo(nickname);
        UserExample.Criteria recent = example.or();
        recent.andCreateTimeGreaterThan("2026-01-01");
        return userMapper.selectByExample(example);
    }

    /** Example 跨类传播：条件在调用方拼，消费在 OrderQuerySupport。 */
    @GetMapping("/wallet/example-support")
    public List<User> exampleSupport(@RequestParam String nickname) {
        UserExample ex = new UserExample();
        ex.createCriteria().andNicknameEqualTo(nickname);
        return orderQuerySupport.searchByExample(ex);
    }

    /** Example 多跳传播：Controller 拼 nickname → 中转层拼 create_time → 终点消费。
     *  修好的行为：终点的合成 SQL 应同时含两层条件（旧版只传一跳，Controller 的丢了）。 */
    @GetMapping("/wallet/example-relay")
    public List<User> exampleRelay(@RequestParam String nickname) {
        UserExample ex = new UserExample();
        ex.createCriteria().andNicknameEqualTo(nickname);
        orderQuerySupport.relayUserExample(ex);
        return null;
    }

    /** 链式返回值接收者：CALL_RE 只认「标识符.方法(」，尾方法 listUsersDirect 旧版收不到。 */
    @GetMapping("/wallet/chain-call")
    public User chainCall(@RequestParam Long userId) {
        return orderQuerySupport.getSelf().listUsersDirect(userId);
    }

    /** 方法内 new 出来的局部对象：类型不在注入字段表里，旧版断链。 */
    @GetMapping("/wallet/local-new")
    public User localNew(@RequestParam Long userId) {
        OrderQuerySupport support = new OrderQuerySupport();
        return support.listUsersDirect(userId);
    }

    /** var 关键字局部变量：类型从 new 右值取。 */
    @GetMapping("/wallet/local-var")
    public User localVar(@RequestParam Long userId) {
        var support = new OrderQuerySupport();
        return support.listUsersDirect(userId);
    }

    /** 链式带参中转：getService(userId) 带参，旧版只认无参 getter，尾方法断链。 */
    @GetMapping("/wallet/chain-arg")
    public User chainArg(@RequestParam Long userId) {
        return orderQuerySupport.getService(userId).listUsersDirect(userId);
    }

    /** 运行期接收者：getBean 出来的 bean 直接链式调用（旧版只剩 getBean 噪音边）。 */
    @GetMapping("/wallet/bean-chain")
    public User beanChain(@RequestParam Long userId) {
        return ctx.getBean(OrderQuerySupport.class).listUsersDirect(userId);
    }

    /** 运行期接收者：var + getBean 赋给局部变量再调用。 */
    @GetMapping("/wallet/bean-var")
    public User beanVar(@RequestParam Long userId) {
        var svc = ctx.getBean(OrderQuerySupport.class);
        return svc.listUsersDirect(userId);
    }

    /** 运行期接收者：Object 字段直调（@PostConstruct 里 new 赋值，赋值推断类型）。 */
    @GetMapping("/wallet/obj-field")
    public User objField(@RequestParam Long userId) {
        return helper.listUsersDirect(userId);
    }

    /** 运行期接收者：Object 字段强转调用 ((X) helper).m()，强转类型即接收者类型。 */
    @GetMapping("/wallet/obj-cast")
    public User objCast(@RequestParam Long userId) {
        return ((OrderQuerySupport) helper).listUsersDirect(userId);
    }

    @org.springframework.beans.factory.annotation.PostConstruct
    public void initHelper() {
        helper = new OrderQuerySupport();
    }

    /** Wrapper .select() 列裁剪：MP 内置 selectList 的保守"全列"应收窄到 select 列。 */
    @GetMapping("/wallet/sel-prune")
    public List<User> selPrune(@RequestParam Long userId) {
        LambdaQueryWrapper<User> w = new LambdaQueryWrapper<>();
        w.select(User::getId, User::getNickname);
        w.eq(User::getId, userId);
        return userMapper.selectList(w);
    }

    /** 工厂方法返回值（本类裸调用）：var svc = buildSupport()，产品类型取本类方法签名。 */
    @GetMapping("/wallet/factory-local")
    public User factoryLocal(@RequestParam Long userId) {
        var svc = buildSupport();
        return svc.listUsersDirect(userId);
    }

    /** 工厂方法返回值（跨类）：var svc = supportFactory.create()，recv 类型→create 的 ret_type。 */
    @GetMapping("/wallet/factory-bean")
    public User factoryBean(@RequestParam Long userId) {
        var svc = supportFactory.create();
        return svc.listUsersDirect(userId);
    }

    /** 工厂方法返回值（字段赋值）：made 在 @PostConstruct 里被工厂方法赋值。 */
    @GetMapping("/wallet/factory-field")
    public User factoryField(@RequestParam Long userId) {
        return made.listUsersDirect(userId);
    }

    /** 本类工厂方法：返回类型写在签名上，和方法体/参数无关。 */
    private OrderQuerySupport buildSupport() {
        return new OrderQuerySupport();
    }

    @org.springframework.beans.factory.annotation.PostConstruct
    public void initMade() {
        made = supportFactory.create();
    }
}
