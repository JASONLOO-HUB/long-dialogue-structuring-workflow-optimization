# ========== Google Colab 代码块：复制到 Colab 按顺序运行 ==========

# ---------- 单元格 1：安装依赖 ----------
# !pip install pdfplumber -q

# ---------- 单元格 2：上传 PDF（可选，若用 Drive 可跳过） ----------
from google.colab import files
uploaded = files.upload()  # 弹出选择文件，选你的 PDF
PDF_PATH = list(uploaded.keys())[0]
print("已选择:", PDF_PATH)

# ---------- 单元格 3：脚本逻辑（复制下面整段） ----------
# 方案一：A4 常规排版，左栏=AI回答、右栏=用户提问，用页面中线 (page.width/2) 区分
import pdfplumber
from pathlib import Path
from collections import defaultdict

# A4 标准宽度（pt），仅当 pdfplumber 未提供 page.width 时使用
A4_WIDTH_PT = 595.28


def extract_text_blocks(pdf_path):
    """提取文本块，每块带 text, x0, top, page, page_width；无坐标时 x0=None。"""
    blocks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_width = getattr(page, "width", None) or A4_WIDTH_PT
            words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
            if not words:
                raw_text = page.extract_text()
                if raw_text:
                    for line in raw_text.splitlines():
                        t = line.strip()
                        if t:
                            blocks.append({
                                "text": t, "x0": None, "top": len(blocks), "page": page_num,
                                "page_width": page_width,
                            })
                continue
            rows = {}
            for w in words:
                y = round(w["top"], 1)
                rows.setdefault(y, []).append(w)
            for y in sorted(rows.keys()):
                line_words = sorted(rows[y], key=lambda w: w["x0"])
                line_text = " ".join(w["text"] for w in line_words)
                if line_text.strip():
                    blocks.append({
                        "text": line_text,
                        "x0": line_words[0]["x0"], "top": y, "page": page_num,
                        "page_width": page_width,
                    })
    blocks.sort(key=lambda b: (b["page"], b["top"], b["x0"] if b["x0"] is not None else 0))
    return blocks


def page_has_two_columns(blocks):
    """按页检测是否真有左右两栏：该页既有 x0<中线 又有 x0>=中线 的块才标答/问，否则整页为正文。"""
    by_page = defaultdict(list)
    for b in blocks:
        if b.get("x0") is not None and b.get("text", "").strip():
            by_page[b["page"]].append(b)
    result = {}
    for page_num, page_blocks in by_page.items():
        pw = page_blocks[0].get("page_width") or A4_WIDTH_PT
        midline = pw / 2
        has_left = any(b["x0"] < midline for b in page_blocks)
        has_right = any(b["x0"] >= midline for b in page_blocks)
        result[page_num] = has_left and has_right
    return result


def role_by_x0(block, two_col_by_page=None):
    """左栏=答，右栏=问；仅当该页为双栏布局时区分，单栏页标为 ?（正文）。无坐标标为 ?。"""
    x0, pw = block.get("x0"), block.get("page_width") or A4_WIDTH_PT
    if x0 is None:
        return "?"
    if two_col_by_page is not None and not two_col_by_page.get(block["page"], False):
        return "?"
    midline = pw / 2
    return "答" if x0 < midline else "问"


def merge_broken_sentences(lines_with_roles):
    """只合并同一角色（答/问）的断句；角色为 ? 的与前后不合并。"""
    if not lines_with_roles:
        return []
    sentence_end = set(".!?。！？;；")
    merged = []
    text, role = lines_with_roles[0]
    buffer_text, buffer_role = text, role

    for i in range(1, len(lines_with_roles)):
        curr_text, curr_role = lines_with_roles[i]
        prev_stripped = buffer_text.rstrip()
        curr_stripped = curr_text.strip()

        # 不同角色不合并
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


def pdf_to_line_numbered_text(pdf_path, output_path="transcript_with_lines.txt"):
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
    print(f"已处理 {len(blocks)} 个文本块，合并为 {len(merged)} 行（其中答/问 {n_qa} 行，正文/未区分 ? 若干行），已保存: {output_path}")
    return output_path


# 执行：输出放在当前文件夹，文件名为「当前文件夹名_text.txt」
_output_dir = Path.cwd()
_output_name = _output_dir.name + "_text.txt"
_output_path = _output_dir / _output_name
pdf_to_line_numbered_text(PDF_PATH, str(_output_path))

# ---------- 单元格 4：下载结果（可选） ----------
# files.download(_output_name)
