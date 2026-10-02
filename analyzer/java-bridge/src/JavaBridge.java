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
import java.util.concurrent.ForkJoinPool;
import java.util.regex.*;
import java.util.stream.*;

/**
 * ContextGate JavaParser 桥接器
 * 用法: java JavaBridge <源码根目录> <输出json路径>
 * 输出: 项目内所有类的结构信息 + 符号求解后的调用接收者类型
 *
 * 设计: JavaParserTypeSolver(项目源码) + ReflectionTypeSolver(JDK)
 * + 可选 JarTypeSolver: 扫 pom.xml 把 ~/.m2 里已下载的依赖 jar 挂进来.
 * 外部类型(Spring/MP)解不出也没关系, 我们要的主要是项目内部的泛型绑定
 * 和接收者类型; jar 类路径纯 best-effort, 没有 m2 仓库照跑.
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

        // 可选 Maven 类路径: 扫项目 pom, 把本地 m2 仓库里的依赖 jar 挂到源码求解之后
        int mavenJars = 0;
        boolean mavenOff = "1".equals(System.getenv("CG_NO_MAVEN"));
        Path m2Repo = mavenOff ? null : locateM2Repo();
        if (mavenOff) {
            System.out.println("CG_NO_MAVEN=1, 跳过 Maven jar 类路径");
        } else if (m2Repo != null) {
            List<Path> poms = Files.walk(srcRoot)
                    .filter(p -> "pom.xml".equals(p.getFileName().toString()))
                    .filter(p -> !p.toString().replace('\\', '/').contains("/target/"))
                    .collect(Collectors.toList());
            if (!poms.isEmpty()) {
                try {
                    mavenJars = addMavenJars(ts, poms, m2Repo);
                    System.out.println("maven jars=" + mavenJars + " repo=" + m2Repo);
                } catch (Exception e) {
                    System.out.println("maven classpath 扫描失败(跳过): " + e);
                }
            }
        } else {
            System.out.println("没找到 ~/.m2/repository, 跳过 Maven jar 类路径");
        }

        final ParserConfiguration cfg = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17)
                .setSymbolResolver(new JavaSymbolSolver(ts));
        // JavaParser 的 parse 不是线程安全的(共享词法分析器), 每线程一个实例;
        // cfg 只在解析时读, 多实例共享一份没问题
        final ThreadLocal<JavaParser> parserTl =
                ThreadLocal.withInitial(() -> new JavaParser(cfg));

        List<Path> javaFiles = Files.walk(srcRoot)
                .filter(p -> p.toString().endsWith(".java"))
                .filter(p -> !p.toString().replace('\\', '/').contains("/test/"))
                .collect(Collectors.toList());

        // 多线程解析 + 符号求解(每个 CompilationUnit 线程内自闭, solver 只读共享),
        // 最后单线程拼 JSON. 大项目(几千文件)符号求解是 CPU 密集活, 并行能明显提速.
        // 但线程拉满时符号求解的锁竞争会反向放大耗时, 用 CG_BRIDGE_THREADS 显式给并发数.
        int threads = Math.max(1, Integer.parseInt(
                System.getenv().getOrDefault("CG_BRIDGE_THREADS", "8")));
        List<String> fragments = Collections.synchronizedList(new ArrayList<String>());
        java.util.concurrent.atomic.AtomicInteger parsed = new java.util.concurrent.atomic.AtomicInteger();
        java.util.concurrent.atomic.AtomicInteger failed = new java.util.concurrent.atomic.AtomicInteger();
        ForkJoinPool pool = new ForkJoinPool(threads);
        try {
            pool.submit(() -> javaFiles.parallelStream().forEach(f -> {
                CompilationUnit cu;
                try {
                    cu = parserTl.get().parse(f).getResult().orElse(null);
                    if (cu == null) { failed.incrementAndGet(); return; }
                } catch (Exception e) { failed.incrementAndGet(); return; }
                parsed.incrementAndGet();
                List<String> own = new ArrayList<>();
                for (TypeDeclaration<?> td : cu.getTypes()) {
                    emitType(own, td, cu);
                }
                if (!own.isEmpty()) fragments.addAll(own);
            })).get();
        } catch (Exception e) {
            throw new RuntimeException("parallel parse failed", e);
        } finally {
            pool.shutdown();
        }
        StringBuilder sb = new StringBuilder();
        sb.append("{\"classes\":[").append(String.join(",", fragments));
        sb.append("],\"meta\":{\"parsed\":").append(parsed.get())
          .append(",\"failed\":").append(failed.get())
          .append(",\"maven_jars\":").append(mavenJars).append("}}");

        Files.createDirectories(outJson.getParent() == null ? Paths.get(".") : outJson.getParent());
        Files.write(outJson, sb.toString().getBytes(StandardCharsets.UTF_8));
        System.out.println("parsed=" + parsed + " failed=" + failed);
    }

    /** 递归输出类型(含内部类): 每个类型生成一个独立 JSON 片段加进 out, 供并行解析后统一拼接 */
    private static void emitType(List<String> out, TypeDeclaration<?> td, CompilationUnit cu) {
        StringBuilder sb = new StringBuilder();
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

        // 当前类型片段先入列, 再递归内部类(顺序无所谓, 按 fqn 建索引)
        out.add(sb.toString());
        for (TypeDeclaration<?> inner : td.getMembers().stream()
                .filter(m -> m instanceof TypeDeclaration).map(m -> (TypeDeclaration<?>) m).collect(Collectors.toList())) {
            emitType(out, inner, cu);
        }
    }

    // ============ Maven 类路径(可选, best-effort) ============

    /** 定位本地 Maven 仓库: CG_M2_REPO 环境变量 > settings.xml 的 localRepository > 默认 ~/.m2/repository */
    private static Path locateM2Repo() {
        String env = System.getenv("CG_M2_REPO");
        if (env != null && !env.trim().isEmpty()) {
            Path p = Paths.get(env.trim());
            if (Files.isDirectory(p)) return p;
        }
        Path home = Paths.get(System.getProperty("user.home"));
        Path settings = home.resolve(".m2").resolve("settings.xml");
        if (Files.isReadable(settings)) {
            try {
                String xml = new String(Files.readAllBytes(settings), StandardCharsets.UTF_8);
                Matcher m = Pattern.compile("<localRepository>\\s*(.*?)\\s*</localRepository>", Pattern.DOTALL).matcher(xml);
                if (m.find()) {
                    String s = m.group(1).trim().replace("${user.home}", System.getProperty("user.home"));
                    Path p = Paths.get(s);
                    if (Files.isDirectory(p)) return p;
                }
            } catch (IOException ignored) {}
        }
        Path def = home.resolve(".m2").resolve("repository");
        return Files.isDirectory(def) ? def : null;
    }

    /**
     * 扫所有 pom.xml: 收集 properties/dependencyManagement/import BOM/真实依赖,
     * 把本地仓库里找得到的依赖 jar 挂成 JarTypeSolver. 返回挂上的 jar 数.
     */
    private static int addMavenJars(CombinedTypeSolver ts, List<Path> pomFiles, Path m2Repo) throws IOException {
        Map<String, String> props = new HashMap<>();       // 跨 pom 合并的属性(先见为准)
        Map<String, String> managed = new HashMap<>();     // g:a -> v, 来自所有 dependencyManagement
        List<String[]> deps = new ArrayList<>();           // 真实依赖 [g,a,v,scope,type,classifier]
        Deque<String[]> pending = new ArrayDeque<>();      // 待读的外部 pom(parent/import BOM) [g,a,v]
        for (Path pom : pomFiles) {
            String xml = readText(pom);
            if (xml != null) parsePom(xml, props, managed, deps, pending);
        }
        // 去 m2 读 parent 链和 import BOM(spring-boot 版本管理就在这条链上), 可链式扩展.
        // 版本占位符可能等父 pom 的属性才能解, 解不动的放回队列下一轮再试.
        Set<String> seenPom = new HashSet<>();
        boolean progress = true;
        while (progress && !pending.isEmpty()) {
            progress = false;
            int size = pending.size();
            for (int i = 0; i < size; i++) {
                String[] c = pending.poll();
                String v = subst(c[2], props);
                if (v == null || v.isEmpty() || v.contains("${")) {
                    pending.add(c);
                    continue;
                }
                if (!seenPom.add(c[0] + ":" + c[1] + ":" + v)) { progress = true; continue; }
                Path pomFile = m2Repo.resolve(c[0].replace('.', '/')
                        + "/" + c[1] + "/" + v + "/" + c[1] + "-" + v + ".pom");
                String xml = readText(pomFile);
                if (xml == null) continue;  // 本地仓库没下载(或项目内部 parent), 放弃这条
                parsePom(xml, props, managed, null, pending);
                progress = true;
            }
        }
        int n = 0;
        Set<String> seenJar = new HashSet<>();
        for (String[] d : deps) {
            String g = d[0], a = d[1], v = d[2];
            String scope = d[3] == null ? "" : d[3];
            String type = d[4] == null ? "" : d[4];
            if ("test".equals(scope) || "pom".equals(type)) continue;
            v = subst(v, props);
            if (v == null || v.isEmpty() || v.contains("${")) {
                v = subst(managed.get(g + ":" + a), props);  // 版本靠父 pom dependencyManagement 管
            }
            if (v == null || v.isEmpty() || v.contains("${")) continue;
            String fileName = a + "-" + v + (d[5] == null ? "" : "-" + d[5]) + ".jar";
            Path jar = m2Repo.resolve(g.replace('.', '/')
                    + "/" + a + "/" + v + "/" + fileName);
            if (!Files.isReadable(jar) || !seenJar.add(jar.toString())) continue;
            try {
                ts.add(new JarTypeSolver(jar.toString()));
                n++;
            } catch (IOException ignored) {}
        }
        return n;
    }

    /**
     * 解析单个 pom. deps 传 null 表示只收 dependencyManagement(用于读进来的 parent/BOM).
     * 约定: 版本占位符在本 pom 内立即用本 pom 属性替换, 剩 ${...} 留给全局属性兜底.
     * parent 坐标和 import BOM 都塞进 pending, 由外层去 m2 找.
     */
    private static void parsePom(String xml, Map<String, String> props,
                                 Map<String, String> managed, List<String[]> deps,
                                 Collection<String[]> pending) {
        xml = xml.replaceAll("(?s)<!--.*?-->", "");

        // 父 pom 坐标
        String pg = null, pa = null, pv = null;
        Matcher pm = Pattern.compile("(?s)<parent>(.*?)</parent>").matcher(xml);
        if (pm.find()) {
            String pb = pm.group(1);
            pg = tagText(pb, "groupId");
            pa = tagText(pb, "artifactId");
            pv = tagText(pb, "version");
            // 父 pom 也去 m2 读一把: 继承它的 properties 和 dependencyManagement
            if (pg != null && pa != null && pv != null) {
                pending.add(new String[]{pg, pa, pv});
            }
        }
        // 本 pom 坐标: 取第一个 <dependencies> 之前、parent 块之外的第一组 groupId/version
        String head = xml;
        int di = xml.indexOf("<dependencies>");
        if (di >= 0) head = xml.substring(0, di);
        if (pv != null) head = head.replaceFirst("(?s)<parent>.*?</parent>", "");
        String gg = tagText(head, "groupId");
        String gv = tagText(head, "version");
        String eg = gg != null ? gg : pg;
        String ev = gv != null ? gv : pv;

        // 本 pom 的属性视图 = 全局属性 + 本 pom properties + 内建坐标属性
        Map<String, String> local = new HashMap<>(props);
        Matcher propsM = Pattern.compile("(?s)<properties>(.*?)</properties>").matcher(xml);
        if (propsM.find()) {
            Matcher kvm = Pattern.compile("(?s)<([A-Za-z0-9_.-]+)>([^<]*)</\\1>").matcher(propsM.group(1));
            while (kvm.find()) {
                local.put(kvm.group(1), kvm.group(2).trim());
                props.putIfAbsent(kvm.group(1), kvm.group(2).trim());
            }
        }
        if (ev != null) { local.put("project.version", ev); local.put("pom.version", ev); }
        if (eg != null) { local.put("project.groupId", eg); local.put("pom.groupId", eg); }
        if (pv != null) { local.put("parent.version", pv); local.put("project.parent.version", pv); }
        if (pg != null) { local.put("parent.groupId", pg); local.put("project.parent.groupId", pg); }

        // dependencyManagement(BOM 自身也在这里): 先挖出来, 再从正文剔掉
        Matcher mgmM = Pattern.compile("(?s)<dependencyManagement>(.*?)</dependencyManagement>").matcher(xml);
        int from = 0;
        while (mgmM.find(from)) {
            String mb = mgmM.group(1);
            Matcher dsM = Pattern.compile("(?s)<dependencies>(.*?)</dependencies>").matcher(mb);
            while (dsM.find()) {
                for (String[] d : parseDepEntries(dsM.group(1))) {
                    String ver = subst(d[2], local);
                    if ("pom".equals(d[4]) && "import".equals(d[3])) {
                        pending.add(new String[]{d[0], d[1], ver});
                    } else {
                        managed.putIfAbsent(d[0] + ":" + d[1], ver);
                    }
                }
            }
            from = mgmM.end();
        }
        if (deps == null) return;
        String body = xml.replaceAll("(?s)<dependencyManagement>.*?</dependencyManagement>", "");

        // 正文里剩下的 <dependencies> 才是真实依赖
        Matcher depM = Pattern.compile("(?s)<dependencies>(.*?)</dependencies>").matcher(body);
        while (depM.find()) {
            for (String[] d : parseDepEntries(depM.group(1))) {
                d[2] = subst(d[2], local);
                deps.add(d);
            }
        }
    }

    /** 解析一个 <dependencies> 块, 每项返回 [groupId, artifactId, version, scope, type, classifier] */
    private static List<String[]> parseDepEntries(String block) {
        List<String[]> out = new ArrayList<>();
        Matcher m = Pattern.compile("(?s)<dependency>(.*?)</dependency>").matcher(block);
        while (m.find()) {
            String b = m.group(1);
            String g = tagText(b, "groupId");
            String a = tagText(b, "artifactId");
            if (g == null || a == null) continue;
            out.add(new String[]{g, a, tagText(b, "version"), tagText(b, "scope"),
                    tagText(b, "type"), tagText(b, "classifier")});
        }
        return out;
    }

    private static String tagText(String block, String tag) {
        Matcher m = Pattern.compile("(?s)<" + tag + ">\\s*(.*?)\\s*</" + tag + ">").matcher(block);
        return m.find() ? m.group(1).trim() : null;
    }

    /** ${prop} 替换, 解不动的原样保留(外层据此判断跳过) */
    private static String subst(String s, Map<String, String> props) {
        if (s == null) return null;
        for (int i = 0; i < 5 && s.contains("${"); i++) {
            Matcher m = Pattern.compile("\\$\\{([^}]+)}").matcher(s);
            StringBuffer sb = new StringBuffer();
            boolean changed = false;
            while (m.find()) {
                String val = props.get(m.group(1));
                if (val != null) {
                    m.appendReplacement(sb, Matcher.quoteReplacement(val));
                    changed = true;
                } else {
                    m.appendReplacement(sb, Matcher.quoteReplacement(m.group(0)));
                }
            }
            m.appendTail(sb);
            if (!changed) break;
            s = sb.toString();
        }
        return s.trim();
    }

    private static String readText(Path p) {
        try {
            return new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return null;
        }
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
