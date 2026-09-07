package com.demo;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 启动类。@MapperScan 注解里含 "@Mapper" 子串——
 * 回归：本类不应被误判为 Mapper（litemall 真实项目踩中的坑）。
 */
@SpringBootApplication
@MapperScan("com.demo.mapper")
public class DemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}
