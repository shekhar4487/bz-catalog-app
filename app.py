import os
import tempfile
import requests
import pandas as pd
import streamlit as st

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from PIL import Image


# ---------- IMAGE + TEXT HELPERS ----------

def download_image_to_temp(image_url: str):
    """
    Download image, resize & compress it (to keep PDF small),
    save to a temporary JPEG file and return its path.
    """
    try:
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()

        # Open image from bytes
        img = Image.open(BytesIO(resp.content))

        # Convert to RGB and downscale to max 500x500 (good for A4 catalog)
        img = img.convert("RGB")
        img.thumbnail((500, 500))

        # Save compressed JPEG to temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        img.save(tmp_path, format="JPEG", quality=70, optimize=True)

        return tmp_path
    except Exception:
        return None


def get_scaled_image_size(path: str, max_w: float, max_h: float):
    """Scale image to fit inside max_w x max_h, keeping aspect ratio."""
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
    """Simple word-wrapping for product names."""
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
    """
    Create a PDF (as bytes) with product:
    - Image
    - Name (bold, centered, spaced)
    - Optional Price bar
    - "Product Details" button linking to product_url
    """
    fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    width, height = A4
    margin = 15 * mm

    c = canvas.Canvas(tmp_pdf_path, pagesize=A4)

    def draw_heading():
        c.setFont("Helvetica-Bold", 20)
        c.setFillColor(colors.black)
        c.drawCentredString(width / 2, height - margin, title_text)

    draw_heading()

    y_top = height - margin - 25

    cols = 3
    usable_width = width - 2 * margin
    col_width = usable_width / cols

    card_h = 90 * mm       # card height
    image_h = 40 * mm      # image frame height
    spacer = 6 * mm        # gap between image and name

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

        # ----- IMAGE FRAME (centered) -----
        img_frame_y = card_y + card_h - image_h - 12
        img_frame_h = image_h
        img_frame_w = card_w - 12

        image_url = str(row.get("image_url", "")).strip()
        tmp_img_path = download_image_to_temp(image_url) if image_url else None

        if tmp_img_path:
            try:
                draw_w, draw_h = get_scaled_image_size(tmp_img_path, img_frame_w, img_frame_h)
                img_x = card_center_x - draw_w / 2
                img_y = img_frame_y + (img_frame_h - draw_h) / 2
                c.drawImage(tmp_img_path, img_x, img_y, width=draw_w, height=draw_h)
            finally:
                os.remove(tmp_img_path)
        else:
            c.setFillColor(colors.white)
            c.rect(card_x + 6, img_frame_y, img_frame_w, img_frame_h, stroke=0, fill=1)

        # ----- PRODUCT NAME (bold, centred, with spacing) -----
        name_y_top = img_frame_y - spacer
        line_height = 8
        max_lines = 2  # keep it clean & inside card

        name = str(row.get("product_name", "")).strip()
        lines = wrap_text(name, max_len=25, max_lines=max_lines)

        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.black)

        text_y = name_y_top - 2
        for line in lines:
            c.drawCentredString(card_center_x, text_y, line)
            text_y -= line_height

        # ----- BOTTOM ACTION AREA (price + Product Details button) -----
        # Layout:
        # [ Price bar ]  (only in price PDF, a bit above)
        # [ Product Details button ]  (always present, clickable)
        button_h = 7 * mm
        button_y = card_y + 7 * mm
        button_w = card_w - 20
        button_x = card_x + (card_w - button_w) / 2

        # Draw "Product Details" button
        c.setFillColor(colors.HexColor("#f0f7ff"))
        c.setStrokeColor(colors.HexColor("#2f80ed"))
        c.roundRect(button_x, button_y, button_w, button_h, 4, stroke=1, fill=1)

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.HexColor("#1f3b70"))
        c.drawCentredString(
            button_x + button_w / 2,
            button_y + button_h / 2 - 3,
            "Product Details",
        )

        # Make the button clickable (link to product_url)
        product_url = str(row.get("product_url", "")).strip()
        if product_url:
            c.linkURL(
                product_url,
                (button_x, button_y, button_x + button_w, button_y + button_h),
                relative=0,
            )

        # Price bar (only in price PDF)
        if show_price:
            price = row.get("price", "")
            if price not in (None, ""):
                bar_h = 8 * mm
                bar_y = button_y + button_h + 2 * mm
                bar_w = card_w - 16
                bar_x = card_x + (card_w - bar_w) / 2

                c.setFillColor(colors.HexColor("#e2f3ff"))
                c.setStrokeColor(colors.HexColor("#4a90e2"))
                c.roundRect(bar_x, bar_y, bar_w, bar_h, 4, stroke=1, fill=1)

                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(colors.HexColor("#1f3b70"))
                c.drawCentredString(
                    bar_x + bar_w / 2,
                    bar_y + bar_h / 2 - 3,
                    f"Price: Rs. {price}",
                )

        # Move to next column / row
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

def normalize_columns(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Map your Excel columns to internal names:
    Product Name -> product_name
    SP           -> price
    Product Link -> product_url
    Image Link   -> image_url
    """
    df = df_raw.copy()
    df.columns = [c.strip() for c in df.columns]

    df = df.rename(columns={
        "Product Name": "product_name",
        "SP": "price",
        "Product Link": "product_url",
        "Image Link": "image_url",
    })

    required = ["product_name", "price", "product_url", "image_url"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Missing required columns after mapping: {', '.join(missing)}")
        return df.iloc[0:0]

    return df


def filter_products(df: pd.DataFrame, mode: str, text: str) -> pd.DataFrame:
    """Filter products by URL or Name based on user input."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return df.iloc[0:0]

    if mode == "url":
        return df[df["product_url"].isin(lines)]
    else:
        lower_lines = [l.lower() for l in lines]
        return df[df["product_name"].str.lower().isin(lower_lines)]


# ---------- STREAMLIT UI ----------

st.set_page_config(page_title="Behtar Zindagi Catalog Generator", layout="wide")
st.title("📄 Behtar Zindagi Catalog Generator")

st.markdown(
    """
This app creates **two PDFs**:

1. **Name + Image + Product Details button**  
2. **Name + Image + Price + Product Details button**  

Your Excel should contain at least these columns:

- `Product Name`
- `SP` (selling price)
- `Product Link` (buy URL)
- `Image Link` (product image URL)
"""
)

uploaded = st.file_uploader("Upload master Excel", type=["xlsx", "xls"])

df_master = None
if uploaded:
    try:
        df_raw = pd.read_excel(uploaded)
        df_master = normalize_columns(df_raw)
        if not df_master.empty:
            st.success(f"Loaded {len(df_master)} products.")
            st.write("Columns:", list(df_master.columns))
        else:
            df_master = None
    except Exception as e:
        st.error(f"Error reading Excel: {e}")
        df_master = None

if df_master is None:
    st.stop()

st.header("Select Products")

mode_choice = st.radio(
    "Select products by:",
    ["By Product URL (Product Link)", "By Product Name"],
)

if mode_choice == "By Product URL (Product Link)":
    mode_key = "url"
    placeholder = "Paste one Product Link (URL) per line..."
else:
    mode_key = "name"
    placeholder = "Paste one Product Name per line (exact / close match)..."

input_text = st.text_area("Products to include", height=150, placeholder=placeholder)

heading = st.text_input("Heading for PDF (e.g. 'Vetcare for Cattle'):")

if st.button("Generate PDFs"):
    if not heading.strip():
        st.error("Please enter a heading.")
    elif not input_text.strip():
        st.error("Please paste at least one product.")
    else:
        selected = filter_products(df_master, mode_key, input_text)
        if selected.empty:
            st.error("No matching products found. Check your names/URLs.")
        else:
            st.success(f"Found {len(selected)} matching products.")

            with st.spinner("Creating PDFs..."):
                pdf_no_price = generate_pdf(selected, show_price=False, title_text=heading)
                pdf_with_price = generate_pdf(selected, show_price=True, title_text=heading)

            st.subheader("Download")
            st.download_button(
                "⬇️ Download PDF (Name + Image + Details button)",
                data=pdf_no_price,
                file_name="catalog_without_price.pdf",
                mime="application/pdf",
            )
            st.download_button(
                "⬇️ Download PDF (Name + Image + Price + Details button)",
                data=pdf_with_price,
                file_name="catalog_with_price.pdf",
                mime="application/pdf",
            )
