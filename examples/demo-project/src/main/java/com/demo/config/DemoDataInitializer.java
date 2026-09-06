package com.demo.config;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** 启动初始化：@PostConstruct 隐藏入口 + JdbcTemplate 裸 INSERT（无路由，框架启动时跑一次）。 */
@Component
public class DemoDataInitializer {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @PostConstruct
    public void initDemoData() {
        jdbcTemplate.update(
                "INSERT INTO users (openid, nickname, wallet_balance) "
                + "VALUES ('demo-openid', 'demo-user', 0)");
    }
}
