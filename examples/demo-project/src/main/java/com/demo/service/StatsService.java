package com.demo.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/** 统计服务：SQL 不走 Mapper，直接用 JdbcTemplate 裸写（演示内嵌 SQL 提取）。 */
@Service
public class StatsService {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    /** 余额榜：裸 SELECT，触碰 users.wallet_balance。 */
    public List<Map<String, Object>> topWallets() {
        String sql = "SELECT id, nickname, wallet_balance FROM users "
                + "ORDER BY wallet_balance DESC LIMIT 10";
        return jdbcTemplate.queryForList(sql);
    }

    /** 总订单额：聚合裸 SQL。 */
    public Map<String, Object> orderAmountSum() {
        return jdbcTemplate.queryForMap(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM orders");
    }
}
