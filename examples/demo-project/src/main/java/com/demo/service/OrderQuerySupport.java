package com.demo.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.entity.Order;
import com.demo.entity.User;
import com.demo.entity.UserExample;
import com.demo.mapper.OrderMapper;
import com.demo.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/** 跨类归并的陪练类：跨类 helper、带 Wrapper 参数消费、带 Example 参数消费。 */
@Service
public class OrderQuerySupport {

    @Autowired
    private OrderMapper orderMapper;

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private StatsService statsService;

    /** 跨类 helper：公共基础条件（被 OrderServiceImpl 套娃调用）。 */
    public LambdaQueryWrapper<Order> buildBase(Integer status) {
        LambdaQueryWrapper<Order> w = new LambdaQueryWrapper<>();
        w.eq(Order::getStatus, status);
        return w;
    }

    /** 带 Wrapper 参数的方法：调用方拼的条件经传播归并进这里的合成 SQL。 */
    public List<Order> searchByWrapper(LambdaQueryWrapper<Order> w) {
        w.gt(Order::getId, 0L);
        return orderMapper.selectList(w);
    }

    /** 带 Example 参数的方法：调用方拼的条件经传播归并进这里的合成 SQL。 */
    public List<User> searchByExample(UserExample example) {
        return userMapper.selectByExample(example);
    }

    /** Example 多跳中转：自己再拼一条条件，然后把 Example 转传给下一跳（StatsService）。
     *  修好的行为：终点合成 SQL 应同时含上游两层的条件（Controller 的 + 本层的）。 */
    public void relayUserExample(UserExample example) {
        example.createCriteria().andCreateTimeGreaterThan("2026-06-01");
        statsService.searchByRelay(example);
    }

    /** 链式调用的中转节：无参 getter 返回自身类型（ret_type 在签名里，可静态解析）。 */
    public OrderQuerySupport getSelf() {
        return this;
    }

    /** 链式/局部变量场景的落点：直接调 mapper 内置方法（全列触碰）。 */
    public User listUsersDirect(Long userId) {
        return userMapper.selectById(userId);
    }
}
