import os
import tempfile
import requests
import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from PIL import Image


# ---------- HELPERS ----------

def download_image_to_temp(image_url: str):
    """Download image locally."""
    try:
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
        return tmp_path
    except Exception:
        return None


def get_scaled_image_size(path: str, max_w: float, max_h: float):
    """Scale image perfectly inside given box preserving ratio."""
    try:
        with Image.open(path) as img:
            w, h = img.size
        if w == 0 or h == 0:
            return max_w, max_h
        scale = min(max_w / w, max_h / h)
        return w * scale, h * scale
    except Exception:
        return max_w, max_h


def wrap_text(text: str, max_len: int, max_lines: int):
    """Soft wrap for product names."""
    if not text:
        return []
    words = text.split()
    lines = []
    current = ""
    for w in words:
        extra = (1 if current else 0) + len(w)
        if len(current) + extra <= max_len:
            current = (current + " " + w) if current else w
        else:
            lines.append(current)
            current = w
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


# ---------- PDF GENERATION ----------

def generate_pdf(products_df: pd.DataFrame, show_price: bool, title_text: str):
    fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    width, height = A4
    margin = 15 * mm

    c = canvas.Canvas(tmp_pdf_path, pagesize=A4)

    def draw_heading():
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width / 2, height - margin, title_text)

    draw_heading()

    y_top = height - margin - 25

    cols = 3
    usable_width = width - 2 * margin
    col_width = usable_width / cols

    card_h = 85 * mm       # bigger cards → better design
    image_h = 40 * mm      # fixed height frame
    image_pad = 5 * mm     # inside padding
    name_area_h = 18 * mm  # fixed area for product name

    spacer = 6 * mm        # spacing between image → name

    col_index = 0

    for _, row in products_df.iterrows():

        # New page if needed
        if col_index == 0 and (y_top - card_h < margin):
            c.showPage()
            draw_heading()
            y_top = height - margin - 25

        card_x = margin + col_index * col_width
        card_y = y_top - card_h
        card_w = col_width - 6

        # ----- CARD BOX -----
        c.setStrokeColor(colors.lightgrey)
        c.setFillColor(colors.whitesmoke)
        c.roundRect(card_x, card_y, card_w, card_h, 10, stroke=1, fill=1)

        card_center_x = card_x + card_w / 2

        # ----- IMAGE FRAME (center aligned) -----
        img_frame_y = card_y + card_h - image_h - 10
        img_frame_h = image_h
        img_frame_w = card_w - 10

        image_url = str(row.get("image_url", "")).strip()
        tmp = download_image_to_temp(image_url)

        if tmp:
            draw_w, draw_h = get_scaled_image_size(tmp, img_frame_w, img_frame_h)
            img_x = card_center_x - draw_w / 2
            img_y = img_frame_y + (img_frame_h - draw_h) / 2
            try:
                c.drawImage(tmp, img_x, img_y, width=draw_w, height=draw_h)
            finally:
                os.remove(tmp)
        else:
            c.setFillColor(colors.white)
            c.rect(card_x + 5, img_frame_y, img_frame_w, img_frame_h, stroke=0, fill=1)

        # ----- PRODUCT NAME (center aligned, BEAUTIFUL SPACING) -----
        name_y_top = img_frame_y - spacer
        name_y_bottom = name_y_top - name_area_h
        line_height = 8

        max_lines = 2  # cleanest appearance
        name = str(row.get("product_name", "")).strip()

        lines = wrap_text(name, max_len=25, max_lines=max_lines)

        c.setFont("Helvetica-Bold", 9)

        text_y = name_y_top - 2
        for line in lines:
            c.drawCentredString(card_center_x, text_y, line)
            text_y -= line_height

        # ----- PRICE BAR -----
        if show_price:
            price = row.get("price", "")
            if price:
                bar_h = 8 * mm
                bar_y = card_y + 8 * mm
                bar_w = card_w - 12
                bar_x = card_x + 6

                c.setFillColor(colors.HexColor("#e2f3ff"))
                c.setStrokeColor(colors.HexColor("#4a90e2"))
                c.roundRect(bar_x, bar_y, bar_w, bar_h, 4, stroke=1, fill=1)

                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(colors.HexColor("#1f3b70"))
                c.drawCentredString(bar_x + bar_w/2, bar_y + bar_h/2 - 3, f"Price: Rs. {price}")

        # next column
        col_index += 1
        if col_index == cols:
            col_index = 0
            y_top -= card_h + 12

    c.save()

    with open(tmp_pdf_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(tmp_pdf_path)

    return pdf_bytes


# ---------- DATA PROCESSING ----------

def normalize_columns(df_raw):
    df = df_raw.copy()
    df.columns = [c.strip() for c in df.columns]

    df = df.rename(columns={
        "Product Name": "product_name",
        "SP": "price",
        "Product Link": "product_url",
        "Image Link": "image_url"
    })

    return df


def filter_products(df, mode, text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return df.iloc[0:0]

    if mode == "url":
        return df[df["product_url"].isin(lines)]
    else:
        return df[df["product_name"].str.lower().isin([l.lower() for l in lines])]


# ---------- STREAMLIT UI ----------

st.set_page_config(page_title="Behtar Zindagi Catalog Generator", layout="wide")
st.title("📄 Behtar Zindagi Catalog Generator")

uploaded = st.file_uploader("Upload master Excel", type=["xlsx", "xls"])

if uploaded:
    df_raw = pd.read_excel(uploaded)
    df = normalize_columns(df_raw)

    st.success("Excel loaded.")

    mode = st.radio("Select products by:", ["URL", "Name"])
    box_text = st.text_area("Paste URLs or Names (one per line)")
    heading = st.text_input("Heading for PDF:")

    if st.button("Generate PDFs"):
        selected = filter_products(df, "url" if mode == "URL" else "name", box_text)

        with st.spinner("Generating..."):
            pdf1 = generate_pdf(selected, show_price=False, title_text=heading)
            pdf2 = generate_pdf(selected, show_price=True, title_text=heading)

        st.download_button("Download PDF (Name + Image)", pdf1, "catalog_without_price.pdf")
        st.download_button("Download PDF (Name + Image + Price)", pdf2, "catalog_with_price.pdf")
