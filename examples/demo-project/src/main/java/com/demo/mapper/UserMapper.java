package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface UserMapper extends BaseMapper<User> {

    // 裸 SELECT *：分析器应展开为 users 全列
    @Select("SELECT * FROM users WHERE openid = #{openid}")
    User selectByOpenid(String openid);

    // 显式列
    @Select("SELECT id, nickname, wallet_balance, create_time FROM users ORDER BY create_time DESC")
    java.util.List<User> selectAll();

    // 写操作
    @Update("UPDATE users SET wallet_balance = COALESCE(wallet_balance, 0) + #{delta} WHERE id = #{userId}")
    int addBalance(Long userId, java.math.BigDecimal delta);
}
