package com.demo.controller;

import com.demo.entity.User;
import com.demo.service.OrderQuerySupport;
import com.demo.entity.UserExample;
import com.demo.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
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
}
