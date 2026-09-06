package com.demo.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** 演示用评价实体（配合 XML mapper：resultMap / sql 片段 / include）。 */
@TableName("comments")
public class Comment {
    private Long id;
    private Long orderId;
    private Long userId;
    private String content;
    private Integer rating;
    private LocalDateTime createTime;
}
