package com.demo.controller;

import com.demo.service.StatsService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/** 统计接口：调用链走到 JdbcTemplate 裸 SQL（没有 Mapper 节点）。 */
@RestController
@RequestMapping("/api/v1")
public class StatsController {

    @Autowired
    private StatsService statsService;

    @GetMapping("/stats/wallets/top")
    public List<Map<String, Object>> topWallets() {
        return statsService.topWallets();
    }

    @GetMapping("/stats/orders/sum")
    public Map<String, Object> orderSum() {
        return statsService.orderAmountSum();
    }

    @GetMapping("/stats/openid/count")
    public Long openidCount() {
        return statsService.demoOpenidCount();
    }

    @GetMapping("/stats/openid/detail")
    public List<Map<String, Object>> openidDetail() {
        return statsService.demoOpenidDetail();
    }
}
