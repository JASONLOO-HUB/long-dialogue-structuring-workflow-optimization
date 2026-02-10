"""
PDF 转带行号文本脚本
- 使用 pdfplumber 按 y/x 坐标排序文本块（适配多栏布局）
- 方案一：A4 常规排版，左栏=AI回答、右栏=用户提问，用页面中线 (page.width/2) 区分
- 自动合并同一角色内因 PDF 换行产生的断句
- 每行前添加 [L编号][答/问] 前缀
- 输出: transcript_with_lines.txt
可在 Google Colab 直接运行（需先 !pip install pdfplumber）
"""

# 在 Colab 中如未安装可取消下行注释：
# !pip install pdfplumber

import pdfplumber
from pathlib import Path
from collections import defaultdict

# A4 标准宽度（pt），仅当 pdfplumber 未提供 page.width 时使用
A4_WIDTH_PT = 595.28


def extract_text_blocks(pdf_path: str) -> list[dict]:
    """
    按页提取所有文本块，每个块含 text, x0, top, page, page_width。
    无坐标时 x0=None。返回按 (page, y, x) 排序的块列表。
    """
    blocks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_width = getattr(page, "width", None) or A4_WIDTH_PT
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False,
                extra_attrs=[],
            )
            if not words:
                raw_text = page.extract_text()
                if raw_text:
                    for line in raw_text.splitlines():
                        t = line.strip()
                        if t:
                            blocks.append({
                                "text": t,
                                "x0": None, "top": len(blocks), "page": page_num,
                                "page_width": page_width,
                            })
                continue

            rows = {}
            for w in words:
                y = round(w["top"], 1)
                if y not in rows:
                    rows[y] = []
                rows[y].append(w)

            for y in sorted(rows.keys()):
                line_words = sorted(rows[y], key=lambda w: w["x0"])
                line_text = " ".join(w["text"] for w in line_words)
                if not line_text.strip():
                    continue
                blocks.append({
                    "text": line_text,
                    "x0": line_words[0]["x0"],
                    "top": y,
                    "page": page_num,
                    "page_width": page_width,
                })

    blocks.sort(key=lambda b: (b["page"], b["top"], b["x0"] if b["x0"] is not None else 0))
    return blocks


def page_has_two_columns(blocks: list[dict]) -> dict[int, bool]:
    """按页检测是否真有左右两栏：该页既有 x0<中线 又有 x0>=中线 的块才标答/问，否则整页为正文。"""
    by_page: dict[int, list[dict]] = defaultdict(list)
    for b in blocks:
        if b.get("x0") is not None and b.get("text", "").strip():
            by_page[b["page"]].append(b)
    result: dict[int, bool] = {}
    for page_num, page_blocks in by_page.items():
        pw = page_blocks[0].get("page_width") or A4_WIDTH_PT
        midline = pw / 2
        has_left = any(b["x0"] < midline for b in page_blocks)
        has_right = any(b["x0"] >= midline for b in page_blocks)
        result[page_num] = has_left and has_right
    return result


def role_by_x0(block: dict, two_col_by_page: dict[int, bool] | None = None) -> str:
    """左栏=答，右栏=问；仅当该页为双栏布局时区分，单栏页标为 ?（正文）。无坐标标为 ?。"""
    x0, pw = block.get("x0"), block.get("page_width") or A4_WIDTH_PT
    if x0 is None:
        return "?"
    if two_col_by_page is not None and not two_col_by_page.get(block["page"], False):
        return "?"
    midline = pw / 2
    return "答" if x0 < midline else "问"


def merge_broken_sentences(lines_with_roles: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """只合并同一角色（答/问）的断句；角色为 ? 的与前后不合并。"""
    if not lines_with_roles:
        return []
    sentence_end = set(".!?。！？;；")
    merged = []
    buffer_text, buffer_role = lines_with_roles[0]

    for i in range(1, len(lines_with_roles)):
        curr_text, curr_role = lines_with_roles[i]
        prev_stripped = buffer_text.rstrip()
        curr_stripped = curr_text.strip()

        if curr_role != buffer_role:
            merged.append((buffer_text, buffer_role))
            buffer_text, buffer_role = curr_text, curr_role
            continue
        if buffer_role == "?" or curr_role == "?":
            merged.append((buffer_text, buffer_role))
            buffer_text, buffer_role = curr_text, curr_role
            continue

        if prev_stripped and prev_stripped[-1] in sentence_end:
            merged.append((buffer_text, buffer_role))
            buffer_text, buffer_role = curr_text, curr_role
            continue
        if prev_stripped.endswith(":"):
            merged.append((buffer_text, buffer_role))
            buffer_text, buffer_role = curr_text, curr_role
            continue
        if curr_stripped.startswith(("问：", "答：", "Q:", "A:", "Q：", "A：")):
            merged.append((buffer_text, buffer_role))
            buffer_text, buffer_role = curr_text, curr_role
            continue
        if prev_stripped and prev_stripped[-1].isascii() and curr_stripped and curr_stripped[0].isascii():
            buffer_text = buffer_text + " " + curr_text
        else:
            buffer_text = buffer_text + curr_text

    merged.append((buffer_text, buffer_role))
    return merged


def pdf_to_line_numbered_text(
    pdf_path: str,
    output_path: str = "transcript_with_lines.txt",
) -> None:
    blocks = extract_text_blocks(pdf_path)
    two_col_by_page = page_has_two_columns(blocks)
    lines_with_roles = [
        (b["text"].strip(), role_by_x0(b, two_col_by_page))
        for b in blocks
        if b["text"].strip()
    ]
    merged = merge_broken_sentences(lines_with_roles)

    with open(output_path, "w", encoding="utf-8") as f:
        for i, (line, role) in enumerate(merged, start=1):
            f.write(f"[L{i}][{role}] {line}\n")

    n_qa = sum(1 for _, r in merged if r != "?")
    print(f"已处理 {len(blocks)} 个文本块，合并为 {len(merged)} 行（其中答/问 {n_qa} 行），已保存到: {output_path}")


if __name__ == "__main__":
    # ========== 在 Colab 中修改为你的 PDF 路径 ==========
    # 方式1: 本地上传到 Colab 后使用文件名
    PDF_PATH = "your_conversation.pdf"

    # 方式2: Colab 中先运行下面两行上传文件，再运行本脚本
    # from google.colab import files
    # uploaded = files.upload()  # 选 PDF 后，PDF_PATH = list(uploaded.keys())[0]

    # 方式3: 从 Google Drive 挂载后使用
    # from google.colab import drive
    # drive.mount("/content/drive")
    # PDF_PATH = "/content/drive/MyDrive/your_conversation.pdf"

    if not Path(PDF_PATH).exists():
        print("请先上传 PDF 或修改 PDF_PATH 为实际路径后再运行。")
    else:
        pdf_to_line_numbered_text(PDF_PATH, "transcript_with_lines.txt")
