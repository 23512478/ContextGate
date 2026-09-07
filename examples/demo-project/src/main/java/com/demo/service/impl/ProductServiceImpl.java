package com.demo.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.demo.mapper.ProductMapper;
import com.demo.model.Product;
import com.demo.service.ProductService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 同时演示两种服务层写法：字段注入 mapper（list/purchase）
 * 和 ServiceImpl 继承式调用（getByIdOrThrow 走泛型 M 的 baseMapper）。
 */
@Service
public class ProductServiceImpl extends ServiceImpl<ProductMapper, Product> implements ProductService {

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

    /** ServiceImpl 继承式调用：this.getById() 委托给泛型 M 的 baseMapper.selectById。 */
    public Product getByIdOrThrow(Long id) {
        Product product = this.getById(id);
        if (product == null) {
            throw new RuntimeException("商品不存在");
        }
        return product;
    }

    /** Manager/ServiceImpl 风格的字段值调用：findByField(Entity::getField, value)。 */
    public Product findByIdField(Long id) {
        return this.findByField(Product::getId, id);
    }
}
