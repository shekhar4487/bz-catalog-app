import os
import tempfile
import requests
import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors


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


def wrap_text(text: str, max_len: int, max_lines: int):
    """
    Simple character-based word wrapping with a maximum number of lines.
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

    card_height = 70 * mm  # taller cards to avoid overflow
    img_height = 32 * mm   # slightly smaller to leave room for text

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

        # Inner margins
        inner_margin_x = 6
        inner_margin_top = 8
        inner_margin_bottom = 8

        # ---- Bottom price bar area ----
        price_bar_height = 8 * mm
        price_bar_y = card_y + inner_margin_bottom

        # ---- Image + name area vertical bounds ----
        content_top = card_y + card_h - inner_margin_top
        content_bottom = price_bar_y + price_bar_height + 4
        content_height = content_top - content_bottom

        # ----- Image placement (centered horizontally) -----
        img_box_h = min(img_height, content_height * 0.6)
        img_box_w = card_w - 2 * inner_margin_x
        card_center_x = card_x + card_w / 2

        # Vertically center image within the upper 60% of content
        img_y = content_bottom + (content_height * 0.6 - img_box_h) / 2 + content_height * 0.4
        img_x = card_center_x - img_box_w / 2

        image_url = str(row.get("image_url", "")).strip()
        tmp_img_path = None

        if image_url:
            tmp_img_path = download_image_to_temp(image_url)

        if tmp_img_path:
            try:
                c.drawImage(
                    tmp_img_path,
                    img_x,
                    img_y,
                    width=img_box_w,
                    height=img_box_h,
                    preserveAspectRatio=True,
                    anchor="sw",
                )
            except Exception:
                c.setFillColor(colors.white)
                c.rect(img_x, img_y, img_box_w, img_box_h, stroke=0, fill=1)
            finally:
                os.remove(tmp_img_path)
        else:
            # Placeholder if no image
            c.setFillColor(colors.white)
            c.rect(img_x, img_y, img_box_w, img_box_h, stroke=0, fill=1)

        # ----- Product name (bold & centred) -----
        name = str(row.get("product_name", "")).strip()

        text_top = img_y - 4
        text_bottom = content_bottom
        available_text_h = text_top - text_bottom
        line_height = 9
        max_lines = max(1, int(available_text_h // line_height))
        max_lines = min(max_lines, 3)  # hard cap

        lines = wrap_text(name, max_len=30, max_lines=max_lines)

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        text_y = text_top
        for line in lines:
            c.drawCentredString(card_center_x, text_y, line)
            text_y -= line_height

        # ----- Price bar (₹ amount, centred) -----
        if show_price:
            price = row.get("price", "")
            if price not in (None, ""):
                price_label = f"₹ {price}"  # rupee symbol before amount

                price_bar_w = card_w - 2 * inner_margin_x
                price_bar_x = card_x + (card_w - price_bar_w) / 2

                c.setFillColor(colors.HexColor("#e2f3ff"))  # light blue
                c.setStrokeColor(colors.HexColor("#4a90e2"))
                c.roundRect(price_bar_x, price_bar_y, price_bar_w, price_bar_height, 3, stroke=1, fill=1)

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
