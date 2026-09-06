package com.demo.controller;

import com.demo.entity.Comment;
import com.demo.mapper.CommentMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** 评价接口：调用链从路由走到 XML 里的 SQL（验证 XML 语句也能逆向到路由）。 */
@RestController
@RequestMapping("/api/v1")
public class CommentController {

    @Autowired
    private CommentMapper commentMapper;

    @GetMapping("/comments/{id}")
    public Comment detail(@PathVariable Long id) {
        return commentMapper.selectDetail(id);
    }

    @GetMapping("/comments/order/{orderId}")
    public List<Comment> listByOrder(@PathVariable Long orderId) {
        return commentMapper.listByOrderId(orderId);
    }

    @PatchMapping("/comments/{id}")
    public String update(@PathVariable Long id, @RequestParam String content) {
        commentMapper.updateContent(id, content);
        return "ok";
    }
}
