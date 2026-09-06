package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.Comment;
import org.apache.ibatis.annotations.Mapper;
import java.util.List;

/**
 * 这个 Mapper 的方法全部没有注解 SQL，SQL 写在
 * src/main/resources/mapper/CommentMapper.xml 里（验证 XML 解析脚手架）。
 */
@Mapper
public interface CommentMapper extends BaseMapper<Comment> {

    // 对应 XML <select id="selectDetail" resultMap="commentResultMap">：resultMap + JOIN + include
    Comment selectDetail(Long id);

    // 对应 XML <select id="listByOrderId">：裸 SELECT *
    List<Comment> listByOrderId(Long orderId);

    // 对应 XML <update id="updateContent">：<set> 动态 SQL
    int updateContent(Long id, String content);
}
