#!/usr/bin/env python3
"""
IPTV 源合并/去重脚本
每天自动爬取 3 个源 → 提取 CCTV+卫视 → 去重选优 → 生成 china.m3u
"""

import re
import sys
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError
from collections import defaultdict

# ===== 配置 =====
SOURCES = [
    {
        "name": "de聚合IPTV",
        "url": "https://develop202.github.io/migu_video/interface.txt",
    },
    {
        "name": "it聚合iptv",
        "url": "https://raw.githubusercontent.com/mzky/checklist/refs/heads/master/itvlist.m3u",
    },
    {
        "name": "aptv iptv",
        "url": "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    },
]

# 剔除关键词（含这些词的频道丢弃）
EXCLUDE_KEYWORDS = [
    "香港", "HK", "HongKong", "hongkong", "hong_kong",
    "澳门", "Macau", "macau", "Macao",
    "台湾", "Taiwan", "taiwan",
    "凤凰", "Phoenix",
    "翡翠", "TVB", "tvb",
    "CHC",  # 付费电影
    "测试", "test", "Test",
    "CGTN",  # 对外频道不算国内
]

# 要保留的 group-title 关键词（或频道名匹配）
INCLUDE_GROUPS = [
    "央视", "CCTV", "cctv",
    "卫视", "卫视IPV4", "卫视",
    "4K", "8K", "超清",
    "春晚", "春节",
    "其他", "国内",
]

# 输出文件
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "china.m3u")
EPG_URL = "https://material.yang-1989.xyz/epg.xml.gz"

# ===== 工具函数 =====

def fetch_url(url, timeout=30):
    """下载 URL 内容"""
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urlopen(req, timeout=timeout)
        data = resp.read()
        # 尝试 UTF-8 解码，失败则用 GBK
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("gbk", errors="replace")
    except URLError as e:
        print(f"[WARN] 下载失败: {url} -> {e}")
        return ""
    except Exception as e:
        print(f"[WARN] 下载异常: {url} -> {e}")
        return ""


def parse_m3u(content, source_name=""):
    """解析 M3U 内容，返回频道列表"""
    channels = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:"):
            # 解析 EXTINF 标签
            extinf = line

            # 提取频道名（逗号后面的部分）
            name_match = re.search(r',(.+?)$', extinf)
            if not name_match:
                i += 1
                continue
            channel_name = name_match.group(1).strip()

            # 提取 tvg-id
            tvg_id = ""
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf)
            if tvg_id_match:
                tvg_id = tvg_id_match.group(1)

            # 提取 tvg-name
            tvg_name = ""
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', extinf)
            if tvg_name_match:
                tvg_name = tvg_name_match.group(1)

            # 提取 group-title
            group_title = ""
            group_match = re.search(r'group-title="([^"]*)"', extinf)
            if group_match:
                group_title = group_match.group(1)

            # 提取 tvg-logo
            tvg_logo = ""
            logo_match = re.search(r'tvg-logo="([^"]*)"', extinf)
            if logo_match:
                tvg_logo = logo_match.group(1)

            # 提取 UA 信息（兼容 user-agent 和 http-user-agent）
            ua = ""
            for ua_pat in [r'user-agent="([^"]*)"', r'http-user-agent="([^"]*)"']:
                ua_m = re.search(ua_pat, extinf)
                if ua_m:
                    ua = ua_m.group(1)
                    break

            # 获取 URL（下一行）
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("#EXT"):
                url = lines[i].strip()
                if url and not url.startswith("#"):
                    # 计算质量评分
                    quality_score = calc_quality_score(
                        channel_name, group_title, url, ua, extinf, source_name
                    )

                    channels.append({
                        "name": channel_name,
                        "tvg_id": tvg_id or channel_name,
                        "tvg_name": tvg_name or channel_name,
                        "group": group_title,
                        "url": url,
                        "logo": tvg_logo,
                        "ua": ua,
                        "quality": quality_score,
                        "source": source_name,
                        "extinf": extinf,
                    })
                    break
                i += 1
        i += 1

    return channels


# 源优先级（越高越优先）
SOURCE_PRIORITY = {
    "de聚合IPTV": 30,   # 官方咪咕CDN，最稳定
    "aptv iptv": 20,    # 综合源
    "it聚合iptv": 10,   # 聚合代理源
}


def calc_quality_score(name, group, url, ua, extinf, source=""):
    """计算频道质量评分（越高越好）"""
    score = 0

    # 源优先级加分
    score += SOURCE_PRIORITY.get(source, 0)

    # 4K/8K 加分
    if "4K" in name or "4K" in group or "4k" in url.lower():
        score += 100
    if "8K" in name or "8K" in group:
        score += 200

    # 超清加分
    if "超清" in name or "超清" in group:
        score += 50
    if "高清" in name or "高清" in group:
        score += 30

    # UA 线索
    if "iPhone" in ua or "iphone" in ua:
        score += 20  # iPhone UA 通常质量更高
    if "aliplayer" in ua:
        score += 15
    if "bestv" in ua:
        score += 10

    # URL 线索
    if "hd" in url.lower():
        score += 10
    if "2160" in url:
        score += 100
    if "1080" in url:
        score += 30
    if "720" in url:
        score += 10

    return score


def should_exclude(name, group):
    """检查频道是否需要剔除"""
    combined = f"{name} {group}"
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in combined.lower():
            return True
    return False


def should_include(name, group):
    """检查频道是否属于我们想要的范围（CCTV/卫视/4K/春晚）"""
    # 来自 4K8K频道 分组的一律保留
    if "4K" in group or "8K" in group or "超清" in group:
        return True
    # 春晚保留
    if "春晚" in group or "春晚" in name:
        return True
    # 央视/卫视保留
    for kw in INCLUDE_GROUPS:
        if kw.lower() in group.lower() or kw.lower() in name.lower():
            return True
    return False


def normalize_name(name):
    """统一频道名：去除后缀差异，方便跨源匹配"""
    n = name.strip()
    # 去除 综合、高清、超清、HD 等后缀
    n = re.sub(r'(综合|高清|超清|HD|hd|超清|标清)$', '', n)
    # 去除空格
    n = n.strip()
    return n


def deduplicate(channels):
    """
    频道去重：按统一后的频道名分组（兼容不同源的 tvg-id 差异）
    每个频道保留 1 主 + 最多 3 备用
    主用 = 质量评分最高的
    备用 = 评分次高的，不同来源/不同URL
    """
    grouped = defaultdict(list)

    for ch in channels:
        # 先尝试用 tvg_id，再尝试用频道名
        key = ch["tvg_id"]
        # 如果 tvg_id 含特殊字符，用归一化后的名称
        if "综合" in key or "高清" in key or "超清" in key:
            key = normalize_name(ch["name"])
        grouped[key].append(ch)

    result = []
    dedup_stats = {"total_groups": 0, "with_backup": 0}

    for ch_name, items in sorted(grouped.items()):
        # 按质量评分降序排列
        items.sort(key=lambda x: (-x["quality"], x["source"]))

        # 去重 URL（同一个源的不同URL算不同）
        unique = []
        seen_urls = set()
        for item in items:
            url_key = item["url"].split("?")[0]  # 去掉参数部分对比
            if url_key not in seen_urls:
                seen_urls.add(url_key)
                unique.append(item)

        if not unique:
            continue

        dedup_stats["total_groups"] += 1

        # 主用（1个）
        main = unique[0]
        # 备用（最多3个）
        backups = unique[1:4]

        if backups:
            dedup_stats["with_backup"] += 1

        result.append({
            "main": main,
            "backups": backups,
            "total_found": len(items),
            "total_used": 1 + len(backups),
        })

    print(f"[INFO] 去重结果: {dedup_stats['total_groups']} 个频道组, "
          f"{dedup_stats['with_backup']} 个有备用")

    return result


def categorize(channel_data):
    """将频道分类到不同分组"""
    categories = {
        "央视频道": [],
        "卫视4K频道": [],
        "卫视频道": [],
        "其他频道": [],
        "历年春晚": [],
    }

    for item in channel_data:
        main = item["main"]
        name = main["name"]
        group = main["group"]

        # 春晚
        if "春晚" in group or "春晚" in name:
            categories["历年春晚"].append(item)
        # 4K 频道
        elif "4K" in name or "4K" in group:
            categories["卫视4K频道"].append(item)
        # 央视
        elif "CCTV" in name.upper() or "cctv" in group.lower() or "央视" in group:
            categories["央视频道"].append(item)
        # 卫视
        elif "卫视" in name or "卫视" in group or "卫星" in group:
            categories["卫视频道"].append(item)
        else:
            categories["其他频道"].append(item)

    return categories


def generate_m3u(categories):
    """生成标准的 M3U 文件内容"""
    lines = []

    # 只有一行 #EXTM3U（合并所有参数）
    epg_attr = f' x-tvg-url="{EPG_URL}"' if EPG_URL else ''
    lines.append(f'#EXTM3U{epg_attr}')

    category_order = ["央视频道", "卫视4K频道", "卫视频道", "其他频道", "历年春晚"]

    for cat_name in category_order:
        items = categories.get(cat_name, [])
        if not items:
            continue

        # 分组标题用 #EXTGRP（标准格式）
        lines.append(f'#EXTGRP:{cat_name}')

        for item in items:
            main = item["main"]

            # 主用 - 只保留标准属性，去掉 user-agent 等非标属性
            extinf_parts = []
            if main["tvg_id"]:
                extinf_parts.append(f'tvg-id="{main["tvg_id"]}"')
            if main["tvg_name"]:
                extinf_parts.append(f'tvg-name="{main["tvg_name"]}"')
            if main["logo"]:
                extinf_parts.append(f'tvg-logo="{main["logo"]}"')
            # group-title 用分组名
            extinf_parts.append(f'group-title="{cat_name}"')
            # user-agent（部分源需要特定UA才能访问）
            if main["ua"]:
                extinf_parts.append(f'http-user-agent="{main["ua"]}"')

            quality_tag = ""
            if main["quality"] >= 100:
                quality_tag = " ★4K"
            elif main["quality"] >= 50:
                quality_tag = " ★高清"

            extinf_str = " ".join(extinf_parts)
            lines.append(f'#EXTINF:-1 {extinf_str},{main["name"]}{quality_tag}')
            lines.append(main["url"])

            # 备用
            for idx, backup in enumerate(item["backups"]):
                bq_tag = ""
                if backup["quality"] >= 100:
                    bq_tag = " ★4K"
                elif backup["quality"] >= 50:
                    bq_tag = " ★高清"

                backup_name = f'{backup["name"]}-备用{idx+1}'
                bk_extinf = f'tvg-id="{backup["tvg_id"]}" group-title="{cat_name}"'
                if backup["ua"]:
                    bk_extinf += f' http-user-agent="{backup["ua"]}"'
                lines.append(f'#EXTINF:-1 {bk_extinf},{backup_name}{bq_tag}')
                lines.append(backup["url"])

    return "\n".join(lines)


def main():
    print("=" * 50)
    print("IPTV 源合并工具 v1.0")
    print("=" * 50)

    all_channels = []

    # 1. 爬取所有源
    for src in SOURCES:
        print(f"\n[下载] {src['name']}: {src['url']}")
        content = fetch_url(src["url"])
        if not content:
            print(f"[SKIP] {src['name']} 下载为空，跳过")
            continue

        channels = parse_m3u(content, src["name"])
        print(f"[解析] {src['name']}: 共 {len(channels)} 条频道")

        # 过滤
        before = len(channels)
        channels = [c for c in channels if not should_exclude(c["name"], c["group"])]
        excluded = before - len(channels)
        print(f"[过滤] {src['name']}: 剔除 {excluded} 个境外/测试频道")

        # 筛选目标频道
        channels = [c for c in channels if should_include(c["name"], c["group"])]
        print(f"[筛选] {src['name']}: 保留 {len(channels)} 个 CCTV/卫视/4K/春晚")

        all_channels.extend(channels)

    print(f"\n[汇总] 3 个源合并后共 {len(all_channels)} 条频道")

    # 2. 去重
    deduped = deduplicate(all_channels)

    # 3. 分类
    categorized = categorize(deduped)

    # 4. 统计
    total = sum(len(v) for v in categorized.values())
    print(f"\n[分类] 共 {total} 个频道组:")
    for cat, items in categorized.items():
        if items:
            main_count = len(items)
            backup_count = sum(len(i["backups"]) for i in items)
            print(f"  {cat}: {main_count} 个频道 (主用) + {backup_count} 个备用")

    # 5. 生成文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    m3u_content = generate_m3u(categorized)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"\n[完成] 已生成: {OUTPUT_FILE}")
    print(f"       共 {len(m3u_content.splitlines())} 行")

    # 也输出 JSON 统计用于 GitHub Actions
    stats = {
        "sources": len(SOURCES),
        "total_channels": total,
        "categories": {k: len(v) for k, v in categorized.items() if v},
        "generated_file": OUTPUT_FILE,
    }
    stats_path = os.path.join(OUTPUT_DIR, "stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"[JSON] 统计信息: {stats_path}")


if __name__ == "__main__":
    main()
