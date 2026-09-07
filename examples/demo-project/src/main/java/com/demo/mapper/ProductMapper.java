package com.demo.mapper;

import com.demo.model.Product;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 原生 MyBatis Mapper：不继承 BaseMapper，SQL 写在注解里。 */
public interface ProductMapper {

    @Select("SELECT * FROM product WHERE id = #{id}")
    Product selectById(Long id);

    @Select("SELECT * FROM product ORDER BY create_time DESC")
    List<Product> selectAll();

    @Update("UPDATE product SET stock = stock - #{count} WHERE id = #{id}")
    int deductStock(Long id, Integer count);
}
