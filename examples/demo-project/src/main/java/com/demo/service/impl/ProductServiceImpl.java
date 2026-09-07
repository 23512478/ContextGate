package com.demo.service.impl;

import com.demo.mapper.ProductMapper;
import com.demo.model.Product;
import com.demo.service.ProductService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ProductServiceImpl implements ProductService {

    @Autowired
    private ProductMapper productMapper;

    @Override
    public List<Product> list() {
        return productMapper.selectAll();
    }

    /** 接口上标了 @Transactional，这里不需要重复标。 */
    @Override
    public int purchase(Long id, Integer count) {
        return productMapper.deductStock(id, count);
    }
}
