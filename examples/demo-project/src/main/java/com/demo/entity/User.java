package com.demo.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 演示用用户实体（故意用全限定类型 java.math.BigDecimal，覆盖该解析规则）。 */
@TableName("users")
public class User {
    private Long id;
    private String openid;
    private String nickname;
    private java.math.BigDecimal walletBalance;
    private LocalDateTime createTime;
}
