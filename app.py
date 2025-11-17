import os
import tempfile
import requests
import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


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


def wrap_text(text: str, max_len: int = 35, max_lines: int = 3):
    """
    Very simple word-wrapping for drawing text in the PDF.
    """
    words = (text or "").split()
    lines = []
    current = ""
    for w in words:
        if len(current) + len(w) + (1 if current else 0) <= max_len:
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
    Uses ReportLab instead of fpdf.
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
        c.drawCentredString(width / 2, heading_y, title_text)

    draw_heading()
    y = heading_y - 20  # start below heading

    cols = 3
    usable_width = width - 2 * margin
    col_width = usable_width / cols
    img_height = 35 * mm
    text_height = 18 * mm
    block_height = img_height + text_height

    col_index = 0

    for _, row in products_df.iterrows():
        # New page if not enough vertical space
        if col_index == 0 and (y - block_height < margin):
            c.showPage()
            draw_heading()
            y = heading_y - 20
            col_index = 0

        x = margin + col_index * col_width

        # ---- Image ----
        image_url = str(row.get("image_url", "")).strip()
        tmp_img_path = None
        if image_url:
            tmp_img_path = download_image_to_temp(image_url)

        img_bottom = y - img_height
        if tmp_img_path:
            try:
                c.drawImage(
                    tmp_img_path,
                    x + 2,
                    img_bottom,
                    width=col_width - 4,
                    height=img_height,
                    preserveAspectRatio=True,
                    anchor="sw",
                )
            except Exception:
                # Draw placeholder rectangle if image fails to render
                c.rect(x + 2, img_bottom, col_width - 4, img_height)
            finally:
                os.remove(tmp_img_path)
        else:
            # Placeholder rectangle
            c.rect(x + 2, img_bottom, col_width - 4, img_height)

        # ---- Text: name (+ price) under image ----
        name = str(row.get("product_name", "")).strip()
        if show_price:
            price = row.get("price", "")
            if price not in (None, ""):
                name = f"{name} (₹{price})"

        lines = wrap_text(name, max_len=35, max_lines=3)
        text_y = img_bottom - 4
        c.setFont("Helvetica", 8)
        for line in lines:
            c.drawString(x + 2, text_y, line)
            text_y -= 9  # line spacing

        # Next column / row
        col_index += 1
        if col_index == cols:
            col_index = 0
            y -= block_height + 5

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
This app will create **two PDFs** from your product list:

1. **Name + Image**  
2. **Name + Image + Price (using SP)**  

**Your Excel should have these columns** (as you shared):

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

You don't need to change the Excel headers.
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

    heading = st.text_input("Heading for this PDF (e.g. 'Milk Processing Machines'):")

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
