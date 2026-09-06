package com.demo.controller;

import com.demo.entity.Order;
import com.demo.service.OrderServiceImpl;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class OrderController {

    @Autowired
    private OrderServiceImpl orderService;

    @PostMapping("/orders")
    public Order create(@RequestParam Long userId,
                        @RequestParam String title,
                        @RequestParam BigDecimal amount) {
        return orderService.create(userId, title, amount);
    }

    @GetMapping("/orders/my")
    public List<Map<String, Object>> listMy(@RequestParam Long userId) {
        return orderService.listMyOrders(userId);
    }
}
