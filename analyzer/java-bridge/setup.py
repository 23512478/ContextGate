#!/usr/bin/env python3
"""下载 JavaParser 桥接依赖并编译桥接器（首次使用前跑一次）"""
import os
import subprocess
import sys
import urllib.request

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(BRIDGE_DIR, "lib")
OUT = os.path.join(BRIDGE_DIR, "out")

MIRROR = "https://maven.aliyun.com/repository/public"
JARS = [
    ("com/github/javaparser/javaparser-core/3.25.10/javaparser-core-3.25.10.jar", "javaparser-core-3.25.10.jar"),
    ("com/github/javaparser/javaparser-symbol-solver-core/3.25.10/javaparser-symbol-solver-core-3.25.10.jar", "javaparser-symbol-solver-core-3.25.10.jar"),
    ("com/google/guava/guava/32.1.3-jre/guava-32.1.3-jre.jar", "guava-32.1.3-jre.jar"),
    ("org/javassist/javassist/3.30.2-GA/javassist-3.30.2-GA.jar", "javassist-3.30.2-GA.jar"),
]


def main():
    os.makedirs(LIB, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    for path, name in JARS:
        dest = os.path.join(LIB, name)
        if os.path.isfile(dest):
            print(f"skip {name} (exists)")
            continue
        url = f"{MIRROR}/{path}"
        print(f"downloading {name}...")
        urllib.request.urlretrieve(url, dest)
        print(f"  ok ({os.path.getsize(dest) // 1024}KB)")

    jars = [os.path.join(LIB, f) for f in os.listdir(LIB) if f.endswith(".jar")]
    cp = os.pathsep.join(jars)
    src = os.path.join(BRIDGE_DIR, "src", "JavaBridge.java")
    print("compiling JavaBridge.java...")
    r = subprocess.run(["javac", "-encoding", "UTF-8", "-cp", cp, "-d", OUT, src])
    if r.returncode != 0:
        print("compile failed", file=sys.stderr)
        sys.exit(1)
    print("done — 桥接器就绪，下次跑 framework_map.py 自动启用")


if __name__ == "__main__":
    main()
