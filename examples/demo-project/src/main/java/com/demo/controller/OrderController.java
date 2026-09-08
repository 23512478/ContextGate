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

    /** Wrapper 拷贝别名入口（验证别名共享续链）。 */
    @GetMapping("/orders/search-alias")
    public List<Order> searchAlias(@RequestParam String keyword) {
        return orderService.searchByAliasCopy(keyword);
    }

    /** Wrapper 作方法参数入口（验证参数当已定义变量）。 */
    @GetMapping("/orders/search-param")
    public List<Order> searchParam(@RequestParam Integer status) {
        return orderService.searchByWrapperParam(new LambdaQueryWrapper<>());
    }

    /** Wrapper 跨类传播入口。 */
    @GetMapping("/orders/search-support")
    public List<Order> searchSupport(@RequestParam Integer status) {
        return orderService.searchViaSupport(status);
    }

    /** Wrapper 由 helper 构建入口（验证跨方法条件归并）。 */
    @GetMapping("/orders/search-helper")
    public List<Order> searchHelper(@RequestParam Integer status) {
        return orderService.searchByHelper(status);
    }
}
