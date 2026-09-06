package com.demo.service;

import com.demo.entity.Order;
import com.demo.entity.User;
import com.demo.mapper.OrderMapper;
import com.demo.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;

@Service
public class OrderServiceImpl {

    @Autowired
    private OrderMapper orderMapper;
    @Autowired
    private UserMapper userMapper;

    /** 下单：事务内写订单 + 读用户（MP 内置 insert/selectById，应被识别为全列触碰）。 */
    @Transactional
    public Order create(Long userId, String title, BigDecimal amount) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new RuntimeException("用户不存在");
        }
        Order order = new Order();
        order.setUserId(userId);
        order.setTitle(title);
        order.setAmount(amount);
        order.setStatus(0);
        orderMapper.insert(order);
        return order;
    }

    public java.util.List<java.util.Map<String, Object>> listMyOrders(Long userId) {
        return orderMapper.selectMyOrders(userId);
    }
}
