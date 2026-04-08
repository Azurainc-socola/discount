import streamlit as st
import gspread
import re
from google.oauth2.service_account import Credentials

# ==========================================
# CẤU HÌNH GIAO DIỆN STREAMLIT
# ==========================================
st.set_page_config(page_title="Azura Discount Calculator", page_icon="💰", layout="centered")

# ==========================================
# CẤU HÌNH KHÁCH HÀNG & HẰNG SỐ
# ==========================================
CLIENT_SHEETS = {
    "UID": "DKWytU7-ui_4CxentBZbEsJKu9DkImlLVi3OUM693o0",
    "JFT": "1KefQd0dt7R0sarZqVAlq0p-p00Bk9eQLl_uWNkAV78o",
    "Welast": "1zhzPVsrvGKOZeIuFe-6VszV50ZBzfeiB2TUaa6vxSQ4",
    "Husble": "1paJKBq8oAwOl-gAMUzFZ3JdkbEdv9b7fEnGQ-pbrzfo"
}

SHEET_PRODUCT_CODE = "Productcode"
SHEET_TOTAL_DISCOUNT = "Total discount"

# ==========================================
# CÁC HÀM XỬ LÝ LÕI
# ==========================================
@st.cache_resource(show_spinner=False)
def authenticate_google_sheets():
    """Xác thực Google Sheets thông qua Streamlit Secrets cho Public App"""
    try:
        scopes = [
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/spreadsheets'
        ]
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi xác thực Google API (Kiểm tra lại cấu hình Secrets): {e}")
        st.stop()

def parse_discount_price(price_str):
    if not price_str: return 0.0
    cleaned_str = str(price_str).strip().replace('$', '').replace('"', '')
    if ',' in cleaned_str and '.' not in cleaned_str:
        cleaned_str = cleaned_str.replace(',', '.')
    try:
        return float(cleaned_str)
    except ValueError:
        return 0.0

def get_product_discount_map(sh):
    try:
        ws_product = sh.worksheet(SHEET_PRODUCT_CODE)
        records = ws_product.get_all_values()[1:] 
        discount_map = {}
        for row in records:
            if len(row) >= 2:
                product_code = row[0].strip()
                discount_price = parse_discount_price(row[1])
                discount_map[product_code] = discount_price
        return discount_map
    except Exception as e:
        st.error(f"❌ Lỗi khi đọc sheet {SHEET_PRODUCT_CODE}: {e}")
        return None

def calculate_invoice_discount(sh, invoice_number, discount_map):
    try:
        ws_invoice = sh.worksheet(invoice_number)
        header = ws_invoice.row_values(1)
        try:
            item_col_idx = header.index("Items")
        except ValueError:
            item_col_idx = 4
            
        rows = ws_invoice.get_all_values()[1:]
        total_discount = 0.0
        item_pattern = re.compile(r'^(\d+)[xX](.+)$')
        
        for row in rows:
            if len(row) > item_col_idx:
                item_val = row[item_col_idx].strip()
                if not item_val: continue
                match = item_pattern.match(item_val)
                if match:
                    qty = int(match.group(1))
                    product_code = match.group(2).strip()
                    price = discount_map.get(product_code, 0.0)
                    total_discount += (qty * price)
        return total_discount
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy tab nào có tên là `{invoice_number}` trong Sheet của khách hàng này.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi xử lý tab `{invoice_number}`: {e}")
        return None

def write_total_discount(sh, invoice_number, total_discount):
    try:
        ws_total = sh.worksheet(SHEET_TOTAL_DISCOUNT)
        ws_total.append_row([invoice_number, total_discount])
        return True
    except Exception as e:
        st.error(f"❌ Lỗi khi ghi vào sheet {SHEET_TOTAL_DISCOUNT}: {e}")
        return False

# ==========================================
# UI & LUỒNG TƯƠNG TÁC CHÍNH
# ==========================================
def main():
    st.title("🚀 Azura Vibe - Cập Nhật Khấu Trừ")
    st.markdown("Chọn Khách hàng và nhập số Invoice bên dưới để tự động tính tổng Discount và ghi sổ.")
    
    # Xác thực Google một lần
    gc = authenticate_google_sheets()

    # Form nhập liệu
    with st.form("invoice_form"):
        # 1. Dropdown chọn Khách hàng
        selected_client_name = st.selectbox(
            "👥 Chọn Khách hàng (Sheet cần thao tác):", 
            options=list(CLIENT_SHEETS.keys())
        )
        
        # 2. Input Invoice
        invoice_number = st.text_input("👉 Nhập Invoice Number (VD: 412):", placeholder="Ví dụ: 412")
        
        # 3. Nút submit
        submit_btn = st.form_submit_button("⚙️ Tính Toán & Ghi Sổ", use_container_width=True)

    # Xử lý Logic sau khi bấm nút
    if submit_btn:
        invoice_number = invoice_number.strip()
        
        if not invoice_number:
            st.warning("⚠️ Vui lòng nhập mã Invoice trước khi chạy!")
            return

        # Lấy ID Sheet dựa trên tên khách hàng đã chọn
        selected_sheet_id = CLIENT_SHEETS[selected_client_name]

        with st.status(f"Đang xử lý Invoice {invoice_number} cho {selected_client_name}...", expanded=True) as status:
            # Mở đúng Sheet của Khách hàng
            try:
                sh = gc.open_by_key(selected_sheet_id)
            except Exception as e:
                status.update(label="Lỗi kết nối Sheet!", state="error")
                st.error(f"❌ Không thể mở Google Sheet của '{selected_client_name}'. Vui lòng kiểm tra lại ID hoặc quyền truy cập.")
                st.stop()

            st.write(f"🔍 Đang nạp bảng giá từ `{SHEET_PRODUCT_CODE}`...")
            discount_map = get_product_discount_map(sh)
            
            if discount_map is None:
                status.update(label="Xử lý thất bại!", state="error")
                return
            
            st.write(f"⚙️ Đang quét và tính tiền các items trong sheet `{invoice_number}`...")
            total_discount = calculate_invoice_discount(sh, invoice_number, discount_map)
            
            if total_discount is not None:
                st.write(f"📝 Đang lưu kết quả `${total_discount:.2f}` vào `{SHEET_TOTAL_DISCOUNT}`...")
                success = write_total_discount(sh, invoice_number, total_discount)
                
                if success:
                    status.update(label=f"Hoàn tất Invoice {invoice_number}!", state="complete", expanded=False)
                    st.success(f"✅ Đã ghi thành công! Tổng discount cho Invoice **{invoice_number}** của **{selected_client_name}** là **${total_discount:.2f}**")
                    st.balloons()
                else:
                    status.update(label="Ghi dữ liệu thất bại!", state="error")
            else:
                status.update(label="Tính toán thất bại!", state="error")

if __name__ == "__main__":
    main()
