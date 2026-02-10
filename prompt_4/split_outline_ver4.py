"""
将 outline_Ver.4.json 按顶层数组元素切分为多个 JSON 文件，按顺序命名 01.json, 02.json, ...
用法:
  python split_outline_ver4.py
  python split_outline_ver4.py --input prompt_4/outline_Ver.4.json --output prompt_4/outline_Ver.4_splits
"""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description="按层级切分 outline JSON 为多个文件")
    parser.add_argument(
        "--input",
        default="prompt_4/outline_Ver.4.json",
        help="输入的 outline JSON 文件路径",
    )
    parser.add_argument(
        "--output",
        default="prompt_4/outline_Ver.4_splits",
        help="输出目录，将写入 01.json, 02.json, ...",
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("输入 JSON 根节点必须是数组")

    os.makedirs(args.output, exist_ok=True)

    for i, item in enumerate(data, start=1):
        filename = f"{i:02d}.json"
        filepath = os.path.join(args.output, filename)
        name = item.get("name", "(无 name)")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print(f"已写入 {filename}（{name}）")

    print(f"共 {len(data)} 个文件，输出目录: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
