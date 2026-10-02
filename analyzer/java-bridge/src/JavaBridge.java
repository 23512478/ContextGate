import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.TypeParameter;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

/**
 * ContextGate JavaParser 桥接器
 * 用法: java JavaBridge <源码根目录> <输出json路径>
 * 输出: 项目内所有类的结构信息 + 符号求解后的调用接收者类型
 *
 * 设计: 只用 JavaParserTypeSolver(项目源码) + ReflectionTypeSolver(JDK),
 * 不依赖 Maven 类路径 —— 外部类型(Spring/MP)解不出没关系,
 * 我们要的是项目内部的泛型绑定和接收者类型, 这正是正则啃不动的部分.
 */
public class JavaBridge {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: JavaBridge <srcRoot> <outJson>");
            System.exit(1);
        }
        Path srcRoot = Paths.get(args[0]);
        Path outJson = Paths.get(args[1]);

        // 找所有 src/main/java 目录作为类型求解根; 找不到就用传入根
        List<Path> sourceRoots = Files.walk(srcRoot)
                .filter(p -> p.toString().replace('\\', '/').endsWith("src/main/java"))
                .collect(Collectors.toList());
        if (sourceRoots.isEmpty()) sourceRoots = Collections.singletonList(srcRoot);

        CombinedTypeSolver ts = new CombinedTypeSolver();
        ts.add(new ReflectionTypeSolver(false));
        for (Path p : sourceRoots) {
            try { ts.add(new JavaParserTypeSolver(p.toFile())); } catch (Exception ignored) {}
        }

        ParserConfiguration cfg = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17)
                .setSymbolResolver(new JavaSymbolSolver(ts));
        JavaParser parser = new JavaParser(cfg);

        List<Path> javaFiles = Files.walk(srcRoot)
                .filter(p -> p.toString().endsWith(".java"))
                .filter(p -> !p.toString().replace('\\', '/').contains("/test/"))
                .collect(Collectors.toList());

        StringBuilder sb = new StringBuilder();
        sb.append("{\"classes\":[");
        int parsed = 0, failed = 0;
        boolean first = true;
        for (Path f : javaFiles) {
            CompilationUnit cu;
            try {
                cu = parser.parse(f).getResult().orElse(null);
                if (cu == null) { failed++; continue; }
            } catch (Exception e) { failed++; continue; }
            parsed++;
            for (TypeDeclaration<?> td : cu.getTypes()) {
                first = emitType(sb, td, cu, first);
            }
        }
        sb.append("],\"meta\":{\"parsed\":").append(parsed)
          .append(",\"failed\":").append(failed).append("}}");

        Files.createDirectories(outJson.getParent() == null ? Paths.get(".") : outJson.getParent());
        Files.write(outJson, sb.toString().getBytes(StandardCharsets.UTF_8));
        System.out.println("parsed=" + parsed + " failed=" + failed);
    }

    /** 递归输出类型(含内部类), 返回更新后的 first 标记 */
    private static boolean emitType(StringBuilder sb, TypeDeclaration<?> td, CompilationUnit cu, boolean first) {
        if (!first) sb.append(',');
        first = false;
        sb.append('{');
        String fqn = td.getFullyQualifiedName().orElse(td.getNameAsString());
        kv(sb, "fqn", fqn); sb.append(',');
        kv(sb, "name", td.getNameAsString()); sb.append(',');
        kv(sb, "pkg", cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("")); sb.append(',');
        kv(sb, "kind", td instanceof ClassOrInterfaceDeclaration
                ? (((ClassOrInterfaceDeclaration) td).isInterface() ? "interface" : "class")
                : td instanceof EnumDeclaration ? "enum" : "other"); sb.append(',');

        // 类型形参
        sb.append("\"type_params\":[");
        if (td instanceof ClassOrInterfaceDeclaration) {
            ClassOrInterfaceDeclaration cid = (ClassOrInterfaceDeclaration) td;
            join(sb, cid.getTypeParameters().stream().map(TypeParameter::getNameAsString).collect(Collectors.toList()));
        }
        sb.append("],");

        if (td instanceof ClassOrInterfaceDeclaration) {
            ClassOrInterfaceDeclaration cid = (ClassOrInterfaceDeclaration) td;
            // extends (原文 + 类型实参)
            sb.append("\"extends\":[");
            boolean ef = true;
            for (ClassOrInterfaceType t : cid.getExtendedTypes()) {
                if (!ef) sb.append(','); ef = false;
                typeJson(sb, t);
            }
            sb.append("],\"implements\":[");
            boolean imf = true;
            for (ClassOrInterfaceType t : cid.getImplementedTypes()) {
                if (!imf) sb.append(','); imf = false;
                typeJson(sb, t);
            }
            sb.append("],");
        } else {
            sb.append("\"extends\":[],\"implements\":[],");
        }

        // 字段
        sb.append("\"fields\":[");
        boolean ff = true;
        for (FieldDeclaration fd : td.getFields()) {
            for (VariableDeclarator v : fd.getVariables()) {
                if (!ff) sb.append(','); ff = false;
                sb.append('{');
                kv(sb, "name", v.getNameAsString()); sb.append(',');
                kv(sb, "type", v.getTypeAsString()); sb.append(',');
                kv(sb, "resolved", resolveQuiet(v.getType())); sb.append(',');
                sb.append("\"annotations\":[");
                join(sb, fd.getAnnotations().stream().map(a -> a.getNameAsString()).collect(Collectors.toList()));
                sb.append("]}");
            }
        }
        sb.append("],");

        // 方法
        sb.append("\"methods\":[");
        boolean mf = true;
        for (MethodDeclaration md : td.getMethods()) {
            if (!mf) sb.append(','); mf = false;
            sb.append('{');
            kv(sb, "name", md.getNameAsString()); sb.append(',');
            kv(sb, "ret", md.getTypeAsString()); sb.append(',');
            sb.append("\"params\":[");
            join(sb, md.getParameters().stream().map(p -> p.getTypeAsString() + " " + p.getNameAsString()).collect(Collectors.toList()));
            sb.append("],\"annotations\":[");
            join(sb, md.getAnnotations().stream().map(a -> a.getNameAsString()).collect(Collectors.toList()));
            sb.append("],\"calls\":[");
            // 方法体内的调用表达式, 尝试符号求解接收者类型
            boolean cf = true;
            if (md.getBody().isPresent()) {
                for (MethodCallExpr call : md.getBody().get().findAll(MethodCallExpr.class)) {
                    if (!cf) sb.append(','); cf = false;
                    sb.append('{');
                    kv(sb, "name", call.getNameAsString()); sb.append(',');
                    String scopeText = call.getScope().map(Expression::toString).orElse("");
                    kv(sb, "scope", scopeText); sb.append(',');
                    sb.append("\"argc\":").append(call.getArguments().size()).append(',');
                    // 求解: 接收者类型 + 方法声明所属类型
                    String recv = "";
                    try {
                        if (call.getScope().isPresent()) {
                            recv = call.getScope().get().calculateResolvedType().describe();
                        }
                    } catch (Throwable ignored) {}
                    kv(sb, "recv_type", recv); sb.append(',');
                    String decl = "";
                    try {
                        decl = call.resolve().declaringType().getQualifiedName();
                    } catch (Throwable ignored) {}
                    kv(sb, "decl_type", decl);
                    sb.append('}');
                }
            }
            sb.append("]}");
        }
        sb.append("]}");

        // 内部类递归
        for (TypeDeclaration<?> inner : td.getMembers().stream()
                .filter(m -> m instanceof TypeDeclaration).map(m -> (TypeDeclaration<?>) m).collect(Collectors.toList())) {
            first = emitType(sb, inner, cu, first);
        }
        return first;
    }

    private static void typeJson(StringBuilder sb, ClassOrInterfaceType t) {
        sb.append('{');
        kv(sb, "raw", t.getNameAsString()); sb.append(',');
        sb.append("\"args\":[");
        if (t.getTypeArguments().isPresent()) {
            join(sb, t.getTypeArguments().get().stream().map(Object::toString).collect(Collectors.toList()));
        }
        sb.append("],");
        String resolved = "";
        try { resolved = t.resolve().describe(); } catch (Throwable ignored) {}
        kv(sb, "resolved", resolved);
        sb.append('}');
    }

    private static String resolveQuiet(com.github.javaparser.ast.type.Type t) {
        try { return t.resolve().describe(); } catch (Throwable e) { return ""; }
    }

    private static void kv(StringBuilder sb, String k, String v) {
        sb.append('"').append(k).append("\":\"").append(esc(v)).append('"');
    }

    private static void join(StringBuilder sb, List<String> items) {
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) sb.append(',');
            sb.append('"').append(esc(items.get(i))).append('"');
        }
    }

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder r = new StringBuilder(s.length() + 16);
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': r.append("\\\""); break;
                case '\\': r.append("\\\\"); break;
                case '\n': r.append("\\n"); break;
                case '\r': r.append("\\r"); break;
                case '\t': r.append("\\t"); break;
                default:
                    if (c < 0x20) r.append(String.format("\\u%04x", (int) c));
                    else r.append(c);
            }
        }
        return r.toString();
    }
}
