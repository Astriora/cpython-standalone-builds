#!/usr/bin/env python3
"""
获取 uv CPython 版本信息（JSON格式）
按系统创建目录（文件夹名都叫 Python）并下载对应文件
支持多线程下载，充分利用带宽
"""

import json
import sys
import os
import argparse
from urllib.request import urlopen, Request, urlretrieve
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE_DIR = "downloads"
SYSTEMS = ["Linux", "macOS", "Windows"]
MAX_WORKERS = 8  # 并发下载线程数

# 用于线程安全的打印
print_lock = Lock()


def thread_safe_print(*args, **kwargs):
    """线程安全的打印函数"""
    with print_lock:
        print(*args, **kwargs)


def fetch_python_versions():
    """获取最新 release 的 CPython 版本信息"""
    api_url = (
        "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
    )
    try:
        req = Request(api_url, headers={"User-Agent": "astriora-fetch-python"})
        with urlopen(req, timeout=30) as response:
            release = json.loads(response.read().decode())

        result = {sys: {} for sys in SYSTEMS}

        version = release.get("tag_name", "")
        if not version:
            return result

        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if "install_only.tar.gz" not in name:
                continue

            download_url = asset.get("browser_download_url", "")

            system = None
            platform_info = ""

            if "unknown-linux-gnu" in name:
                system = "Linux"
                if "x86_64" in name:
                    platform_info = "x86_64"
                elif "aarch64" in name:
                    platform_info = "aarch64"
            elif "apple-darwin" in name:
                system = "macOS"
                if "x86_64" in name:
                    platform_info = "x86_64"
                elif "aarch64" in name:
                    platform_info = "aarch64 (Apple Silicon)"
            elif "pc-windows" in name:
                system = "Windows"
                if "x86_64" in name:
                    platform_info = "x86_64"
                elif "i686" in name:
                    platform_info = "i686"

            if system and platform_info:
                if version not in result[system]:
                    result[system][version] = []
                result[system][version].append(
                    {
                        "filename": name,
                        "platform": platform_info,
                        "url": download_url,
                        "sha256": None,
                    }
                )

        return result

    except Exception as e:
        print(f"获取失败: {e}", file=sys.stderr)
        return None


def download_single_file(url, save_path, filename):
    """下载单个文件"""
    try:
        thread_safe_print(f"⏳ 开始下载 {filename} ...")
        urlretrieve(url, save_path)
        thread_safe_print(f"✓ {filename} 下载完成")
        return True, filename
    except Exception as e:
        thread_safe_print(f"✗ 下载失败 {filename}: {e}", file=sys.stderr)
        # 删除可能损坏的部分文件
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except:
                pass
        return False, filename


def download_files(versions_data, systems_to_download, max_workers=MAX_WORKERS):
    """使用多线程按系统创建文件夹并下载文件和SHA256文件"""

    # 收集所有下载任务
    download_tasks = []
    sha_tasks = []

    for system in systems_to_download:
        if system not in versions_data:
            continue

        for version, files in versions_data[system].items():
            folder_path = os.path.join(BASE_DIR, system, "Python")
            os.makedirs(folder_path, exist_ok=True)

            # SHA256SUMS 文件任务
            sha_filename = f"SHA256SUMS-{version}.txt"
            sha_url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{version}/SHA256SUMS"
            sha_path = os.path.join(folder_path, sha_filename)

            if not os.path.exists(sha_path):
                sha_tasks.append((sha_url, sha_path, sha_filename))
            else:
                thread_safe_print(f"跳过 {sha_filename} (已存在)")

            # Python 文件任务
            for item in files:
                filename = item["filename"]
                url = item["url"]
                save_path = os.path.join(folder_path, filename)

                if os.path.exists(save_path):
                    thread_safe_print(f"跳过 {filename} (已存在)")
                    continue

                download_tasks.append((url, save_path, filename))

    # 统计信息
    total_tasks = len(sha_tasks) + len(download_tasks)
    if total_tasks == 0:
        thread_safe_print("没有需要下载的文件")
        return

    thread_safe_print(
        f"\n准备下载 {total_tasks} 个文件 (使用 {max_workers} 个线程)...\n"
    )

    success_count = 0
    failed_count = 0

    # 使用线程池下载
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 先下载 SHA256 文件（优先级高）
        futures = []
        for url, save_path, filename in sha_tasks:
            future = executor.submit(download_single_file, url, save_path, filename)
            futures.append(future)

        # 再下载 Python 文件
        for url, save_path, filename in download_tasks:
            future = executor.submit(download_single_file, url, save_path, filename)
            futures.append(future)

        # 等待所有任务完成
        for future in as_completed(futures):
            success, filename = future.result()
            if success:
                success_count += 1
            else:
                failed_count += 1

    thread_safe_print(f"\n下载完成! 成功: {success_count}, 失败: {failed_count}")


def main():
    parser = argparse.ArgumentParser(description="下载 Python 独立构建版本")
    parser.add_argument(
        "--system",
        choices=["Linux", "macOS", "Windows", "all"],
        default="all",
        help="指定下载的系统 (默认: all)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"并发下载线程数 (默认: {MAX_WORKERS})",
    )
    args = parser.parse_args()

    # 根据参数决定下载哪些系统
    if args.system == "all":
        systems_to_download = SYSTEMS
    else:
        systems_to_download = [args.system]

    print(f"正在获取 Python 版本信息 ({', '.join(systems_to_download)})...\n")
    versions_data = fetch_python_versions()
    if not versions_data:
        print("获取失败！")
        sys.exit(1)

    # 只保留需要的系统
    filtered_data = {
        sys: versions_data[sys] for sys in systems_to_download if sys in versions_data
    }

    # 输出 JSON
    print("=" * 60)
    print(json.dumps(filtered_data, indent=2, ensure_ascii=False))
    print("=" * 60)
    print()

    # 多线程下载文件
    download_files(versions_data, systems_to_download, args.workers)

    # 统计信息
    print("\n统计信息:")
    for system in systems_to_download:
        if system in versions_data:
            count = sum(len(items) for items in versions_data[system].values())
            print(f"  {system}: {count} 个文件")


if __name__ == "__main__":
    main()
