package com.demo.controller;

import com.demo.service.StatsService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
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

    @GetMapping("/stats/openid/cross")
    public List<Map<String, Object>> openidCross() {
        return statsService.demoOpenidCross();
    }

    @GetMapping("/stats/openid/detail")
    public List<Map<String, Object>> openidDetail() {
        return statsService.demoOpenidDetail();
    }

    @GetMapping("/stats/openid/local")
    public List<Map<String, Object>> openidLocal() {
        return statsService.demoOpenidLocal();
    }

    @GetMapping("/stats/openid/local-inline")
    public Long openidLocalInline() {
        return statsService.demoOpenidLocalInline();
    }

    /** 真运行期拼参：方法参数直接拼进 SQL，骨架应保留、值降级为 ?。 */
    @GetMapping("/stats/runtime/inline")
    public List<Map<String, Object>> runtimeInline(@RequestParam Long userId) {
        return statsService.runtimeConcatInline(userId);
    }

    /** 真运行期拼参：方法调用返回值拼进 SQL。 */
    @GetMapping("/stats/runtime/call")
    public List<Map<String, Object>> runtimeCall(@RequestParam Long userId) {
        return statsService.runtimeConcatCall(userId);
    }

    /** 真运行期拼参：拼进局部 sql 变量再整变量传参。 */
    @GetMapping("/stats/runtime/var")
    public Map<String, Object> runtimeVar(@RequestParam Long userId) {
        return statsService.runtimeConcatVar(userId);
    }
}
