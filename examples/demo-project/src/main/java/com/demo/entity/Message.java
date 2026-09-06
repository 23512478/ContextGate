package com.demo.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** 演示用聊天消息实体（覆盖裸 SELECT * 展开）。 */
@TableName("messages")
public class Message {
    private Long id;
    private Long conversationId;
    private String role;
    private String content;
    private LocalDateTime createTime;
}
