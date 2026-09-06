package com.demo.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 演示用订单实体。 */
@TableName("orders")
public class Order {
    private Long id;
    private Long userId;
    private String title;
    private BigDecimal amount;
    private Integer status;
    private LocalDateTime createTime;
}
