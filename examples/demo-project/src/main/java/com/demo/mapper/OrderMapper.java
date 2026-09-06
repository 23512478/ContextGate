package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import java.util.Map;

@Mapper
public interface OrderMapper extends BaseMapper<Order> {

    // 别名星号 o.* + JOIN 读 u.nickname：覆盖别名星号展开 + 跨表列归属
    @Select("SELECT o.*, u.nickname AS user_name FROM orders o "
            + "LEFT JOIN users u ON o.user_id = u.id "
            + "WHERE o.user_id = #{userId} ORDER BY o.create_time DESC")
    java.util.List<Map<String, Object>> selectMyOrders(Long userId);
}
