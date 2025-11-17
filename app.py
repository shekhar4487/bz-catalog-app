import os
import tempfile
import requests
import pandas as pd
from fpdf import FPDF
import streamlit as st


# ---------- PDF CLASS ----------

class ProductPDF(FPDF):
    def __init__(self, title_text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_text = title_text

    def header(self):
        # Heading at the top center
        if self.title_text:
            self.set_font("Helvetica", "B", 18)
            self.cell(0, 10, self.title_text, ln=1, align="C")
            self.ln(5)


# ---------- HELPERS ----------

def download_image_to_temp(image_url):
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


def generate_pdf(products_df, show_price=False, title_text="Catalog"):
    """
    Create a PDF in memory (as bytes) with product image + name (+ price option).
    Returns bytes of the PDF file.
    """
    pdf = ProductPDF(title_text=title_text, orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)

    # Layout: 3 products per row
    cols = 3
    page_width = pdf.w - 2 * pdf.l_margin
    col_width = page_width / cols
    img_height = 35
    block_height = img_height + 20

    x_start = pdf.l_margin
    y = pdf.get_y()
    col_index = 0

    products_df = products_df.copy()
    products_df.columns = [c.strip().lower() for c in products_df.columns]

    for _, row in products_df.iterrows():
        if col_index == 0 and (pdf.get_y() + block_height > pdf.h - pdf.b_margin):
            pdf.add_page()
            y = pdf.get_y()

        x = x_start + col_index * col_width

        # Image
        image_url = str(row.get("image_url", "")).strip()
        tmp_img_path = None
        if image_url:
            tmp_img_path = download_image_to_temp(image_url)

        if tmp_img_path:
            pdf.image(tmp_img_path, x=x + 2, y=y, w=col_width - 4, h=img_height)
            os.remove(tmp_img_path)
        else:
            # Placeholder rectangle if image not found
            pdf.rect(x + 2, y, col_width - 4, img_height)

        # Text: name (+ price)
        pdf.set_xy(x + 2, y + img_height + 2)
        name = str(row.get("product_name", "")).strip()

        if show_price:
            price = row.get("price", "")
            text = f"{name}\n₹{price}"
        else:
            text = name

        pdf.multi_cell(col_width - 4, 5, txt=text, align="L")

        col_index += 1
        if col_index == cols:
            col_index = 0
            y += block_height + 5

    # Return as bytes
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        pdf.output(tmp_file.name)
        tmp_file.flush()
        tmp_file.seek(0)
        pdf_bytes = tmp_file.read()
    os.remove(tmp_file.name)
    return pdf_bytes


def filter_products(df, selection_mode, input_text):
    """
    Filter products based on selection mode and user input.
    selection_mode: 'url' or 'name'
    input_text: multi-line string
    """
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    lines = [line.strip() for line in input_text.splitlines() if line.strip()]

    if not lines:
        return df.iloc[0:0]  # empty df

    if selection_mode == "url":
        if "product_url" not in df.columns:
            st.error("Column 'product_url' not found in Excel. Please rename accordingly.")
            return df.iloc[0:0]
        return df[df["product_url"].isin(lines)]

    else:  # by name
        if "product_name" not in df.columns:
            st.error("Column 'product_name' not found in Excel. Please rename accordingly.")
            return df.iloc[0:0]

        lower_names = [x.lower() for x in lines]
        return df[df["product_name"].str.lower().isin(lower_names)]


# ---------- STREAMLIT APP ----------

st.set_page_config(page_title="Behtar Zindagi Catalog Generator", layout="wide")

st.title("📄 Behtar Zindagi PDF Catalog Generator")

st.markdown(
    """
This app will create **two PDFs** from your product list:

1. **Name + Image**  
2. **Name + Image + Price**

---

### How to use:

1. Upload your **master Excel file** (with all products).  
   Required columns (case-insensitive):  
   - `product_name`  
   - `price`  
   - `product_url`  
   - `image_url`  

2. Choose how you want to select products (by URL or by name).  
3. Paste product URLs or product names (one per line).  
4. Type a heading for the PDF.  
5. Click **Generate PDFs** and then download.
"""
)

# 1. Upload master Excel
st.header("1️⃣ Upload Master Excel")

uploaded_file = st.file_uploader(
    "Upload your master Excel file (e.g. products_master.xlsx):",
    type=["xlsx", "xls"],
)

if uploaded_file is not None:
    try:
        df_master = pd.read_excel(uploaded_file)
        st.success(f"Loaded {len(df_master)} products from Excel.")
        st.write("Columns detected:", list(df_master.columns))
    except Exception as e:
        st.error(f"Error reading Excel file: {e}")
        df_master = None
else:
    df_master = None

st.header("2️⃣ Select Products")

if df_master is None:
    st.info("Please upload an Excel file above to continue.")
else:
    selection_mode = st.radio(
        "How do you want to select products?",
        ["By product URL", "By product name"],
    )

    if selection_mode == "By product URL":
        mode_key = "url"
        placeholder = "Paste one product URL per line (must match the 'product_url' column)..."
    else:
        mode_key = "name"
        placeholder = "Paste one product name per line (must match the 'product_name' column in Excel)..."

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
            st.error("Please paste at least one product URL or product name.")
        else:
            selected_df = filter_products(df_master, mode_key, input_text)

            if selected_df.empty:
                st.error("No matching products found. Please check your inputs and Excel columns.")
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
                    label="⬇️ Download PDF (Name + Image + Price)",
                    data=pdf_with_price,
                    file_name="catalog_with_price.pdf",
                    mime="application/pdf",
                )
