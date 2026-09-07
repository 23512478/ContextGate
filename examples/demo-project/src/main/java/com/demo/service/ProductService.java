package com.demo.service;

import com.demo.model.Product;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * Service 接口：@Transactional 标在接口方法上（mall 风格）。
 * 分析器需把事务注解传播到实现类同名方法。
 */
public interface ProductService {

    List<Product> list();

    Product getByIdOrThrow(Long id);

    @Transactional
    int purchase(Long id, Integer count);
}
