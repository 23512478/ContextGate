package com.demo.service;

import com.demo.constant.SqlParts;
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

    /** 类级 SQL 常量：JdbcTemplate 常把 SQL 抽成 static final 字段（验证常量收集）。 */
    private static final String SQL_DEMO_OPENID =
            "SELECT COUNT(*) AS openid_total FROM users "
            + "WHERE openid = 'demo-openid'";

    /** 常量 SQL 统计：SQL 在类级 static final 常量里，方法内只传常量名。 */
    public Long demoOpenidCount() {
        return jdbcTemplate.queryForObject(SQL_DEMO_OPENID, Long.class);
    }

    /** 公共 WHERE 片段 + 每查询片段：常量互拼（验证常量折叠到不动点）。 */
    private static final String WHERE_OPENID = " WHERE openid = 'demo-openid'";
    private static final String SQL_OPENID_DETAIL =
            "SELECT id, nickname FROM users" + WHERE_OPENID;

    /** 常量互拼 SQL 统计。 */
    public List<Map<String, Object>> demoOpenidDetail() {
        return jdbcTemplate.queryForList(SQL_OPENID_DETAIL);
    }

    /** 跨类常量互拼：引用 SqlParts 的公共片段（验证全局常量折叠）。 */
    private static final String SQL_OPENID_CROSS =
            "SELECT id, nickname FROM users" + SqlParts.OPENID_WHERE;

    public List<Map<String, Object>> demoOpenidCross() {
        return jdbcTemplate.queryForList(SQL_OPENID_CROSS);
    }
}
