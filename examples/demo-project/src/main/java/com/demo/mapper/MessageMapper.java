package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.Message;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface MessageMapper extends BaseMapper<Message> {

    // 裸 SELECT *：content/role 等列只靠星号带出，分析器必须展开
    @Select("SELECT * FROM messages WHERE conversation_id = #{conversationId} ORDER BY create_time DESC")
    java.util.List<Message> selectRecent(Long conversationId);
}
