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
}
