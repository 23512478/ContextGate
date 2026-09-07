package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.User;
import com.demo.entity.UserExample;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

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

    // MBG 风格：SQL 由 Example 动态条件合成（无注解 SQL）
    List<User> selectByExample(UserExample example);

    // MP 的 lambda() 链入口：mapper default 方法内部构建动态查询
    default List<User> selectByNicknameLambda(String nickname) {
        return this.lambda()
                .select(User::getId, User::getNickname)
                .eq(User::getNickname, nickname)
                .list();
    }
}
