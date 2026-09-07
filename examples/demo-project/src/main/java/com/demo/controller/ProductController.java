package com.demo.controller;

import com.demo.model.Product;
import com.demo.service.ProductService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
public class ProductController {

    @Autowired
    private ProductService productService;

    @GetMapping("/products/detail")
    public Product detail(@RequestParam Long id) {
        return productService.getByIdOrThrow(id);
    }

    @GetMapping("/products")
    public List<Product> list() {
        return productService.list();
    }

    @PostMapping("/products/purchase")
    public String purchase(@RequestParam Long id, @RequestParam Integer count) {
        productService.purchase(id, count);
        return "ok";
    }
}
