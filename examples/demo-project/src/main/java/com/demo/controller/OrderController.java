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

    /** Wrapper 动态查询入口：调用链应显示 MP Wrapper 合成 SQL。 */
    @GetMapping("/orders/search")
    public List<Order> search(@RequestParam String keyword) {
        return orderService.searchByTitle(keyword);
    }

    /** Wrapper 拆变量跨语句链式调用入口（验证 def-use 重建）。 */
    @GetMapping("/orders/search-flexible")
    public List<Order> searchFlexible(@RequestParam String keyword,
                                      @RequestParam Integer status,
                                      @RequestParam boolean recentOnly) {
        return orderService.searchOrdersFlexible(keyword, status, recentOnly);
    }
}
