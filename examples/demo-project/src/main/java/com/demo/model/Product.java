package com.demo.model;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 原生 MyBatis 风格的实体：无 @TableName，表名由类名推断（product → product）。
 * 用来验证分析器对无注解实体的兜底识别。
 */
public class Product implements Serializable {
    private Long id;

    private String name;

    private BigDecimal price;

    private Integer stock;

    private Date createTime;

    private static final long serialVersionUID = 1L;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public BigDecimal getPrice() { return price; }
    public void setPrice(BigDecimal price) { this.price = price; }
    public Integer getStock() { return stock; }
    public void setStock(Integer stock) { this.stock = stock; }
    public Date getCreateTime() { return createTime; }
    public void setCreateTime(Date createTime) { this.createTime = createTime; }
}
