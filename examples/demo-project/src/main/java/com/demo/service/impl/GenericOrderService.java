package com.demo.service.impl;

import com.demo.entity.Order;
import com.demo.service.MidOrderService;
import org.springframework.stereotype.Service;

/**
 * 具体子类：T 在这里钉死成 Order，本类一个自有方法都没有，全部继承。
 * 路由调 midGet / genericGetById 时，调用图节点要靠继承解析补建，
 * 最终落到 OrderMapper#selectById。
 */
@Service
public class GenericOrderService extends MidOrderService<Order> {
}
