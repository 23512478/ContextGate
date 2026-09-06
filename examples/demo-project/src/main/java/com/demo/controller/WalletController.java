package com.demo.controller;

import com.demo.entity.User;
import com.demo.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;

@RestController
@RequestMapping("/api/v1")
public class WalletController {

    @Autowired
    private UserMapper userMapper;

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
}
