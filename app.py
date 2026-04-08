import streamlit as st
import gspread
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# ==========================================
# CẤU HÌNH GIAO DIỆN STREAMLIT
# ==========================================
st.set_page_config(page_title="Azura Discount Calculator", page_icon="💰", layout="centered")

# ==========================================
# CẤU HÌNH KHÁCH HÀNG & HẰNG SỐ
# ==========================================
CLIENT_SHEETS = {
    "UID": "1DKWytU7-ui_4CxentBZbEsJKu9DkImlLVi3OUM693o0",
    "JFT": "1KefQd0dt7R0sarZqVAlq0p-p00Bk9eQLl_uWNkAV78o",
    "Welast": "1zhzPVsrvGKOZeIuFe-6VszV50ZBzfeiB2TUaa6vxSQ4",
    "Husble": "1paJKBq8oAwOl-gAMUzFZ3JdkbEdv9b7fEnGQ-pbrzfo"
}

SHEET_PRODUCT_CODE = "Productcode"
SHEET_TOTAL_DISCOUNT = "Total discount"

# CỐ ĐỊNH EMAIL NHẬN BÁO CÁO
FIXED_TO_EMAIL = "mibi9500@gmail.com"
FIXED_CC_EMAILS = "namhoang243@gmail.com, quynhluong@azurainc.com"

# ==========================================
# CÁC HÀM XỬ LÝ LÕI
# ==========================================
@st.cache_resource(show_spinner=False)
def authenticate_google_sheets():
    try:
        scopes = [
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/spreadsheets'
        ]
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi xác thực Google API: {e}")
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
                price_str = str(row[1]).strip()
                if product_code and price_str != "":
                    discount_map[product_code] = parse_discount_price(price_str)
        return discount_map
    except Exception as e:
        st.error(f"❌ Lỗi khi đọc sheet {SHEET_PRODUCT_CODE}: {e}")
        return None

def calculate_invoice_discount(sh, invoice_number, discount_map):
    try:
        ws_invoice = sh.worksheet(invoice_number)
        header = ws_invoice.row_values(1)
        item_col_idx = header.index("Items") if "Items" in header else 4
            
        rows = ws_invoice.get_all_values()[1:]
        total_discount = 0.0
        item_counts = {}
        missing_codes = set()
        
        item_pattern = re.compile(r'^(\d+)[xX](.+)$')
        
        for row in rows:
            if len(row) > item_col_idx:
                item_val = row[item_col_idx].strip()
                if not item_val: continue
                match = item_pattern.match(item_val)
                if match:
                    qty = int(match.group(1))
                    product_code = match.group(2).strip()
                    
                    if product_code not in discount_map:
                        missing_codes.add(product_code)
                    else:
                        price = discount_map.get(product_code, 0.0)
                        total_discount += (qty * price)
                    
                    item_counts[product_code] = item_counts.get(product_code, 0) + qty
                        
        return total_discount, item_counts, missing_codes
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy tab `{invoice_number}`.")
        return None, None, None
    except Exception as e:
        st.error(f"❌ Lỗi xử lý tab `{invoice_number}`: {e}")
        return None, None, None

def write_total_discount(sh, invoice_number, total_discount, item_counts, discount_map):
    try:
        ws_total = sh.worksheet(SHEET_TOTAL_DISCOUNT)
        rows_to_append = []
        is_first_row = True
        total_qty = 0
        
        for code, qty in item_counts.items():
            unit_price = discount_map.get(code, 0.0)
            line_total = qty * unit_price
            total_qty += qty
            inv_val = invoice_number if is_first_row else ""
            rows_to_append.append([inv_val, "", code, qty, f"${unit_price:.2f}", f"${line_total:.2f}"])
            is_first_row = False
            
        rows_to_append.append(["", f"${total_discount:.2f}", "TỔNG CỘNG", total_qty, "-", f"${total_discount:.2f}"])
        rows_to_append.append(["", "", "", "", "", ""]) 
        
        # FIX LỆCH CỘT: Ép dải bảng bắt đầu từ A
        ws_total.append_rows(rows_to_append, value_input_option="USER_ENTERED", table_range="A1")
        return len(rows_to_append)
    except Exception as e:
        st.error(f"❌ Lỗi khi ghi vào sheet: {e}")
        return 0

def send_alert_email(sender_email, sender_password, client_name, invoice_number, missing_codes, sheet_url):
    try:
        codes_html = "".join([f"<li><b>{code}</b></li>" for code in missing_codes])
        html_content = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #E74C3C;">⚠️ CẢNH BÁO TỪ CHỐI GHI SỔ - {client_name}</h2>
            <p>Hệ thống <b>TỪ CHỐI</b> Invoice <b>{invoice_number}</b> do thiếu đơn giá sản phẩm:</p>
            <div style="background-color: #FDEDEC; padding: 15px; border-left: 5px solid #E74C3C;">
                <ul>{codes_html}</ul>
                <p>🔗 <b>Link cập nhật giá:</b> <a href="{sheet_url}">Mở Google Sheet</a></p>
            </div>
        </body></html>
        """
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = FIXED_TO_EMAIL
        msg['Cc'] = FIXED_CC_EMAILS
        msg['Subject'] = f"[CẢNH BÁO] Thiếu Giá SP - Invoice {invoice_number} ({client_name})"
        msg.attach(MIMEText(html_content, 'html'))
        all_recipients = [FIXED_TO_EMAIL] + [e.strip() for e in FIXED_CC_EMAILS.split(',')]
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, all_recipients, msg.as_string())
        server.quit()
        return True
    except: return False

def send_success_email(sender_email, sender_password, client_name, invoice_number, total_discount, item_counts, sheet_url, new_rows):
    try:
        items_html = "".join([f"<li><b>{code}</b>: {qty} cái</li>" for code, qty in item_counts.items()])
        html_content = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #2E86C1;">Báo Cáo Khấu Trừ Azura - {client_name}</h2>
            <div style="background-color: #f9f9f9; padding: 15px; border-left: 5px solid #2E86C1;">
                <h3>💰 Tổng Discount: ${total_discount:.2f}</h3>
                <p>📍 Tab: <code>{SHEET_TOTAL_DISCOUNT}</code> | 📝 Ghi mới: {new_rows} dòng</p>
                <p>🔗 <a href="{sheet_url}">Nhấn vào đây để xem chi tiết trên Sheet</a></p>
            </div>
            <h4>📦 Chi tiết:</h4><ul>{items_html}</ul>
        </body></html>
        """
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = FIXED_TO_EMAIL
        msg['Cc'] = FIXED_CC_EMAILS
        msg['Subject'] = f"[Azura] Invoice {invoice_number} - {client_name} - ${total_discount:.2f}"
        msg.attach(MIMEText(html_content, 'html'))
        all_recipients = [FIXED_TO_EMAIL] + [e.strip() for e in FIXED_CC_EMAILS.split(',')]
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, all_recipients, msg.as_string())
        server.quit()
        return True
    except: return False

# ==========================================
# UI & LUỒNG CHÍNH
# ==========================================
def main():
    st.title("🚀 Azura Vibe - Cập Nhật Khấu Trừ")
    
    gc = authenticate_google_sheets()

    with st.form("invoice_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_client_name = st.selectbox("👥 Chọn Khách hàng:", options=list(CLIENT_SHEETS.keys()))
            invoice_number = st.text_input("👉 Nhập Invoice Number:", placeholder="Ví dụ: 412")
        with col2:
            # 💡 VIBECODER UPDATE: OPTION GỬI EMAIL
            is_send_email = st.checkbox("📩 Tự động gửi Email báo cáo", value=True)
            st.info(f"**Người nhận:** {FIXED_TO_EMAIL}")
            submit_btn = st.form_submit_button("⚙️ Chạy Quy Trình", use_container_width=True)

    if submit_btn:
        inv_no = invoice_number.strip()
        if not inv_no:
            st.warning("⚠️ Vui lòng nhập mã Invoice!")
            return

        sid = CLIENT_SHEETS[selected_client_name]
        s_url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"

        with st.status(f"Đang xử lý Invoice {inv_no}...", expanded=True) as status:
            try:
                sh = gc.open_by_key(sid)
            except:
                status.update(label="Lỗi kết nối Sheet!", state="error"); st.stop()

            # 1. KIỂM TRA TRÙNG
            try:
                ws_t = sh.worksheet(SHEET_TOTAL_DISCOUNT)
                if inv_no in [str(v).strip() for v in ws_t.col_values(1)]:
                    status.update(label="Trùng lặp!", state="error")
                    st.error(f"❌ Invoice `{inv_no}` đã tồn tại!"); st.link_button("Mở Sheet kiểm tra", s_url); st.stop()
            except gspread.exceptions.WorksheetNotFound: pass
            
            # 2. NẠP GIÁ & TÍNH TOÁN
            d_map = get_product_discount_map(sh)
            total_d, i_counts, m_codes = calculate_invoice_discount(sh, inv_no, d_map)
            
            if total_d is not None:
                # 3. KIỂM TRA THIẾU GIÁ (HARD STOP)
                if m_codes:
                    status.update(label="Thiếu dữ liệu giá!", state="error")
                    st.error(f"❌ **LỖI:** Thiếu giá cho các mã: {', '.join(m_codes)}")
                    if is_send_email:
                        s_em = st.secrets["email_config"]["sender_email"]
                        s_pw = st.secrets["email_config"]["app_password"]
                        send_alert_email(s_em, s_pw, selected_client_name, inv_no, m_codes, s_url)
                    st.link_button("Bổ sung giá ngay", s_url); st.stop()

                # 4. GHI SỔ
                n_rows = write_total_discount(sh, inv_no, total_d, i_counts, d_map)
                
                if n_rows > 0:
                    if is_send_email:
                        s_em = st.secrets["email_config"]["sender_email"]
                        s_pw = st.secrets["email_config"]["app_password"]
                        send_success_email(s_em, s_pw, selected_client_name, inv_no, total_d, i_counts, s_url, n_rows)
                    
                    status.update(label=f"Xong Invoice {inv_no}!", state="complete", expanded=False)
                    st.success(f"✅ Đã ghi thành công vào `{selected_client_name}`")
                    st.link_button("🔗 Mở Google Sheet", s_url)
                    
                    # Hiện bảng kê
                    df = pd.DataFrame([{"Mã SP": c, "SL": q, "Đơn Giá": f"${d_map[c]:.2f}", "Thành Tiền": f"${q*d_map[c]:.2f}"} for c in i_counts])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    st.balloons()

if __name__ == "__main__":
    main()
