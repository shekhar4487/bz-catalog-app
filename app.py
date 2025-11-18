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
    """
    Download image from URL to a temporary file and return its path.
    If it fails, return None.
    """
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
    """
    Read actual image size and return scaled width/height that fit in max_w x max_h,
    keeping aspect ratio.
    """
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
    """
    Character-based word wrapping with a maximum number of lines.
    """
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


def generate_pdf(products_df: pd.DataFrame, show_price: bool = False, title_text: str = "Catalog"):
    """
    Create a PDF (as bytes) with product image + name (+ price option).
    Clean card layout, image + text centered, price highlighted.
    Expects columns: product_name, price, image_url.
    """
    # Create temporary PDF file
    fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    width, height = A4
    margin = 15 * mm
    heading_y = height - margin

    c = canvas.Canvas(tmp_pdf_path, pagesize=A4)

    def draw_heading():
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(colors.black)
        c.drawCentredString(width / 2, heading_y, title_text)

    draw_heading()
    y_top_row = heading_y - 25  # top of first row of cards

    # Layout: 3 cards per row
    cols = 3
    usable_width = width - 2 * margin
    col_width = usable_width / cols

    card_height = 75 * mm
    col_index = 0

    for _, row in products_df.iterrows():
        # Start a new page if not enough vertical space for a whole row
        if col_index == 0 and (y_top_row - card_height < margin):
            c.showPage()
            draw_heading()
            y_top_row = heading_y - 25
            col_index = 0

        card_x = margin + col_index * col_width
        card_y = y_top_row - card_height
        card_w = col_width - 6
        card_h = card_height

        # ----- Card background + border -----
        c.setStrokeColor(colors.lightgrey)
        c.setFillColor(colors.whitesmoke)
        c.roundRect(card_x, card_y, card_w, card_h, 8, stroke=1, fill=1)

        # Inner padding
        inner_x_margin = 6
        inner_top_margin = 10
        inner_bottom_margin = 8

        # Price bar geometry
        price_bar_height = 8 * mm
        price_bar_y = card_y + inner_bottom_margin

        # Content vertical area (image + name)
        content_top = card_y + card_h - inner_top_margin
        content_bottom = price_bar_y + price_bar_height + 4
        content_height = content_top - content_bottom

        card_center_x = card_x + card_w / 2

        # ----- Image area (top half of content), centred -----
        image_area_height = content_height * 0.55
        image_area_width = card_w - 2 * inner_x_margin
        image_area_x = card_x + inner_x_margin
        image_area_y = content_bottom + content_height * 0.45  # push up a bit

        image_url = str(row.get("image_url", "")).strip()
        tmp_img_path = None

        if image_url:
            tmp_img_path = download_image_to_temp(image_url)

        if tmp_img_path:
            try:
                draw_w, draw_h = get_scaled_image_size(
                    tmp_img_path, image_area_width, image_area_height
                )
                img_x = image_area_x + (image_area_width - draw_w) / 2
                img_y = image_area_y + (image_area_height - draw_h) / 2
                c.drawImage(
                    tmp_img_path,
                    img_x,
                    img_y,
                    width=draw_w,
                    height=draw_h,
                    preserveAspectRatio=False,
                    anchor="sw",
                )
            except Exception:
                c.setFillColor(colors.white)
                c.rect(
                    image_area_x,
                    image_area_y,
                    image_area_width,
                    image_area_height,
                    stroke=0,
                    fill=1,
                )
            finally:
                os.remove(tmp_img_path)
        else:
            c.setFillColor(colors.white)
            c.rect(
                image_area_x,
                image_area_y,
                image_area_width,
                image_area_height,
                stroke=0,
                fill=1,
            )

        # ----- Product name area (bold, centred, limited) -----
        name_area_top = image_area_y - 4
        name_area_bottom = content_bottom
        available_text_h = max(10, name_area_top - name_area_bottom)
        line_height = 8
        max_lines = min(3, int(available_text_h // line_height))

        name = str(row.get("product_name", "")).strip()
        # shorter max_len to avoid spilling horizontally
        lines = wrap_text(name, max_len=24, max_lines=max_lines)

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        text_y = name_area_top
        for line in lines:
            c.drawCentredString(card_center_x, text_y, line)
            text_y -= line_height

        # ----- Price bar (Price: Rs. <amount>) -----
        if show_price:
            price = row.get("price", "")
            if price not in (None, ""):
                # Use "Rs." instead of ₹ because base PDF font doesn't support ₹
                price_label = f"Price: Rs. {price}"

                price_bar_w = card_w - 2 * inner_x_margin
                price_bar_x = card_x + (card_w - price_bar_w) / 2

                c.setFillColor(colors.HexColor("#e2f3ff"))
                c.setStrokeColor(colors.HexColor("#4a90e2"))
                c.roundRect(
                    price_bar_x,
                    price_bar_y,
                    price_bar_w,
                    price_bar_height,
                    3,
                    stroke=1,
                    fill=1,
                )

                c.setFillColor(colors.HexColor("#1f3b70"))
                c.setFont("Helvetica-Bold", 9)
                c.drawCentredString(
                    price_bar_x + price_bar_w / 2,
                    price_bar_y + price_bar_height / 2 - 3,
                    price_label,
                )

        # ---- move to next column / row ----
        col_index += 1
        if col_index == cols:
            col_index = 0
            y_top_row -= card_height + 10

    c.save()

    # Read PDF bytes
    with open(tmp_pdf_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(tmp_pdf_path)

    return pdf_bytes


def normalize_columns(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Map your original Excel columns to internal names:
    Product Name -> product_name
    SP           -> price
    Product Link -> product_url
    Image Link   -> image_url
    """
    df = df_raw.copy()
    df.columns = [c.strip() for c in df.columns]

    rename_map = {
        "Product Name": "product_name",
        "SP": "price",
        "Product Link": "product_url",
        "Image Link": "image_url",
    }

    df = df.rename(columns=rename_map)

    required_cols = ["product_name", "price", "product_url", "image_url"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        st.error(
            "These required columns are missing after mapping: "
            + ", ".join(missing)
            + ". Please check your Excel headers."
        )
        return df.iloc[0:0]

    return df


def filter_products(df_norm: pd.DataFrame, selection_mode: str, input_text: str) -> pd.DataFrame:
    """
    Filter products based on selection mode and user input.
    selection_mode: 'url' or 'name'
    input_text: multi-line string
    Expects normalized columns: product_name, product_url
    """
    df = df_norm.copy()
    lines = [line.strip() for line in input_text.splitlines() if line.strip()]

    if not lines:
        return df.iloc[0:0]

    if selection_mode == "url":
        return df[df["product_url"].isin(lines)]
    else:
        lower_names = [x.lower() for x in lines]
        return df[df["product_name"].str.lower().isin(lower_names)]


# ---------- STREAMLIT APP ----------

st.set_page_config(page_title="Behtar Zindagi Catalog Generator", layout="wide")

st.title("📄 Behtar Zindagi PDF Catalog Generator")

st.markdown(
    """
This app creates **two PDFs** from your product list:

1. **Name + Image**  
2. **Name + Image + Price (using SP)**  

**Your Excel should have these columns**:

- `Product Name`
- `Unit`
- `Hindi Product Name`
- `Category`
- `Single/Pack/Combo`
- `SP`  *(used as price in PDF)*
- `MRP`
- `Brand`
- `Specification`
- `Application`
- `Possible Keywords - Eng`
- `Possible Keywords - Hin`
- `Possible Keywords - Hinglish`
- `Image Link`  *(used for product image)*
- `Video Link`
- `Product Link`  *(used for URL selection)*
"""
)

# 1. Upload master Excel
st.header("1️⃣ Upload Master Excel")

uploaded_file = st.file_uploader(
    "Upload your master Excel file:",
    type=["xlsx", "xls"],
)

df_master_raw = None
df_master = None

if uploaded_file is not None:
    try:
        df_master_raw = pd.read_excel(uploaded_file)
        st.success(f"Loaded {len(df_master_raw)} rows from Excel.")
        st.write("Columns detected:", list(df_master_raw.columns))

        df_master = normalize_columns(df_master_raw)
        if df_master.empty:
            df_master = None
        else:
            st.info("Column mapping successful. Ready to select products.")
    except Exception as e:
        st.error(f"Error reading Excel file: {e}")
        df_master = None
else:
    df_master = None

st.header("2️⃣ Select Products")

if df_master is None:
    st.info("Please upload a valid Excel file above to continue.")
else:
    selection_mode = st.radio(
        "How do you want to select products?",
        ["By product URL (Product Link)", "By product name (Product Name)"],
    )

    if selection_mode == "By product URL (Product Link)":
        mode_key = "url"
        placeholder = "Paste one Product Link per line (must match 'Product Link' column)..."
    else:
        mode_key = "name"
        placeholder = "Paste one Product Name per line (must match 'Product Name' column)..."

    input_text = st.text_area(
        "Product list",
        placeholder=placeholder,
        height=150,
    )

    st.header("3️⃣ Heading & Generate")

    heading = st.text_input("Heading for this PDF (e.g. 'Vetcare Products for Cattle'):")

    if st.button("Generate PDFs", type="primary"):
        if not heading.strip():
            st.error("Please enter a heading.")
        elif not input_text.strip():
            st.error("Please paste at least one product link or name.")
        else:
            selected_df = filter_products(df_master, mode_key, input_text)

            if selected_df.empty:
                st.error("No matching products found. Please check your inputs.")
            else:
                st.success(f"Found {len(selected_df)} matching products.")

                with st.spinner("Creating PDFs..."):
                    pdf_no_price = generate_pdf(
                        selected_df, show_price=False, title_text=heading
                    )
                    pdf_with_price = generate_pdf(
                        selected_df, show_price=True, title_text=heading
                    )

                st.subheader("4️⃣ Download PDFs")

                st.download_button(
                    label="⬇️ Download PDF (Name + Image)",
                    data=pdf_no_price,
                    file_name="catalog_without_price.pdf",
                    mime="application/pdf",
                )

                st.download_button(
                    label="⬇️ Download PDF (Name + Image + SP)",
                    data=pdf_with_price,
                    file_name="catalog_with_price.pdf",
                    mime="application/pdf",
                )
