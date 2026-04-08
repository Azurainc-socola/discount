import streamlit as st
import gspread
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.service_account import Credentials
import pandas as pd

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
        item_counts = {}
        
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
                    
                    if product_code in item_counts:
                        item_counts[product_code] += qty
                    else:
                        item_counts[product_code] = qty
                        
        return total_discount, item_counts
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy tab `{invoice_number}` trong Sheet của khách hàng này.")
        return None, None
    except Exception as e:
        st.error(f"❌ Lỗi khi xử lý tab `{invoice_number}`: {e}")
        return None, None

def write_total_discount(sh, invoice_number, total_discount, item_counts, discount_map):
    """
    VIBECODER UPDATE: Ghi nguyên một bảng chi tiết vào Sheet thay vì 1 dòng
    """
    try:
        ws_total = sh.worksheet(SHEET_TOTAL_DISCOUNT)
        
        rows_to_append = []
        is_first_row = True
        total_qty = 0
        
        # 1. Tạo các dòng chi tiết cho từng Sản phẩm
        for code, qty in item_counts.items():
            unit_price = discount_map.get(code, 0.0)
            line_total = qty * unit_price
            total_qty += qty
            
            # Chỉ điền Invoice Number ở dòng đầu tiên của cụm này
            inv_val = invoice_number if is_first_row else ""
            
            row = [
                inv_val,                  # Cột A: Invoice number
                "",                       # Cột B: Total (Để trống ở dòng chi tiết)
                code,                     # Cột C: Mã SP
                qty,                      # Cột D: Số Lượng
                f"${unit_price:.2f}",     # Cột E: Đơn Giá
                f"${line_total:.2f}"      # Cột F: Thành Tiền
            ]
            rows_to_append.append(row)
            is_first_row = False
            
        # 2. Tạo dòng TỔNG CỘNG chốt lại ở dưới cùng
        summary_row = [
            "",                           # Cột A: (Trống)
            f"${total_discount:.2f}",     # Cột B: Total Discount của cả Invoice
            "TỔNG CỘNG",                  # Cột C: Mã SP
            total_qty,                    # Cột D: Tổng số lượng
            "-",                          # Cột E: Đơn giá
            f"${total_discount:.2f}"      # Cột F: Tổng tiền
        ]
        rows_to_append.append(summary_row)
        
        # Thêm 1 dòng trống cho thoáng (tách biệt với Invoice tiếp theo)
        rows_to_append.append(["", "", "", "", "", ""])
        
        # 3. Đẩy toàn bộ danh sách dòng này lên Google Sheet cùng lúc
        ws_total.append_rows(rows_to_append)
        return True
    except Exception as e:
        st.error(f"❌ Lỗi khi ghi vào sheet {SHEET_TOTAL_DISCOUNT}: {e}")
        return False

def send_email_report(sender_email, sender_password, client_name, invoice_number, total_discount, item_counts):
    try:
        items_html = ""
        for code, qty in item_counts.items():
            items_html += f"<li><b>{code}</b>: {qty} cái</li>"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2E86C1;">Báo Cáo Khấu Trừ Azura - Khách Hàng {client_name}</h2>
            <p>Hệ thống vừa tính toán và ghi sổ thành công cho <b>Invoice {invoice_number}</b>.</p>
            
            <h3 style="color: #D35400;">💰 Tổng Discount: ${total_discount:.2f}</h3>
            
            <h4>📦 Chi tiết Items (Tổng hợp):</h4>
            <ul>
                {items_html}
            </ul>
            
            <hr>
            <p style="font-size: 12px; color: #7f8c8d;"><i>Email này được gửi tự động từ hệ thống Azura VibeCoder. Vui lòng không trả lời trực tiếp.</i></p>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = FIXED_TO_EMAIL
        msg['Cc'] = FIXED_CC_EMAILS
        msg['Subject'] = f"[Azura Báo Cáo] Invoice {invoice_number} - Khách {client_name} - Discount: ${total_discount:.2f}"
        msg.attach(MIMEText(html_content, 'html'))

        all_recipients = [FIXED_TO_EMAIL] + [email.strip() for email in FIXED_CC_EMAILS.split(',')]

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, all_recipients, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"⚠️ Không thể gửi email báo cáo: {e}")
        return False

# ==========================================
# UI & LUỒNG TƯƠNG TÁC CHÍNH
# ==========================================
def main():
    st.title("🚀 Azura Vibe - Cập Nhật Khấu Trừ")
    st.markdown("Chọn Khách hàng và nhập số Invoice bên dưới để tính toán, ghi sổ và gửi báo cáo.")
    
    gc = authenticate_google_sheets()

    with st.form("invoice_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_client_name = st.selectbox("👥 Chọn Khách hàng:", options=list(CLIENT_SHEETS.keys()))
            invoice_number = st.text_input("👉 Nhập Invoice Number:", placeholder="Ví dụ: 412")
        with col2:
            st.info(f"**📧 Email tự động gửi đến:**\n\n**To:** {FIXED_TO_EMAIL}\n\n**CC:** {FIXED_CC_EMAILS}")
            st.markdown("<br>", unsafe_allow_html=True)
            submit_btn = st.form_submit_button("⚙️ Tính Toán, Ghi Sổ & Gửi Email", use_container_width=True)

    if submit_btn:
        invoice_number = invoice_number.strip()
        
        if not invoice_number:
            st.warning("⚠️ Vui lòng nhập mã Invoice!")
            return

        selected_sheet_id = CLIENT_SHEETS[selected_client_name]

        with st.status(f"Đang xử lý Invoice {invoice_number} cho {selected_client_name}...", expanded=True) as status:
            try:
                sh = gc.open_by_key(selected_sheet_id)
            except Exception as e:
                status.update(label="Lỗi kết nối Sheet!", state="error")
                st.stop()

            st.write(f"🔍 Đang nạp bảng giá từ `{SHEET_PRODUCT_CODE}`...")
            discount_map = get_product_discount_map(sh)
            if discount_map is None:
                status.update(label="Xử lý thất bại!", state="error")
                return
            
            st.write(f"⚙️ Đang quét và tổng hợp items trong sheet `{invoice_number}`...")
            total_discount, item_counts = calculate_invoice_discount(sh, invoice_number, discount_map)
            
            if total_discount is not None:
                st.write(f"📝 Đang lưu kết quả chi tiết vào `{SHEET_TOTAL_DISCOUNT}`...")
                
                # UPDATE: Truyền thêm item_counts và discount_map vào hàm ghi file
                success_write = write_total_discount(sh, invoice_number, total_discount, item_counts, discount_map)
                
                if success_write:
                    st.write(f"📩 Đang gửi email báo cáo...")
                    try:
                        sender_email = st.secrets["email_config"]["sender_email"]
                        sender_password = st.secrets["email_config"]["app_password"]
                        
                        email_sent = send_email_report(
                            sender_email, sender_password, selected_client_name, 
                            invoice_number, total_discount, item_counts
                        )
                        
                        if email_sent:
                            status.update(label=f"Hoàn tất! Đã ghi sổ và gửi Email.", state="complete", expanded=False)
                            st.success(f"✅ Đã ghi thành công! Invoice **{invoice_number}** có tổng discount là **${total_discount:.2f}**")
                            st.info(f"📧 Đã gửi báo cáo chi tiết đến {FIXED_TO_EMAIL} (kèm CC).")
                            
                            st.markdown("---")
                            st.subheader("📊 Bảng Kê Chi Tiết Khấu Trừ (Đã ghi vào Sheet)")
                            
                            table_data = []
                            for code, qty in item_counts.items():
                                unit_price = discount_map.get(code, 0.0)
                                line_total = qty * unit_price
                                table_data.append({
                                    "Mã Sản Phẩm": code,
                                    "Số Lượng": qty,
                                    "Đơn Giá Discount": f"${unit_price:.2f}",
                                    "Thành Tiền": f"${line_total:.2f}"
                                })
                            
                            df = pd.DataFrame(table_data)
                            total_row = pd.DataFrame([{
                                "Mã Sản Phẩm": "TỔNG CỘNG", 
                                "Số Lượng": sum(item_counts.values()), 
                                "Đơn Giá Discount": "-", 
                                "Thành Tiền": f"${total_discount:.2f}"
                            }])
                            df = pd.concat([df, total_row], ignore_index=True)
                            
                            st.dataframe(df, use_container_width=True, hide_index=True)
                            
                            st.balloons()
                            
                    except KeyError:
                        status.update(label=f"Ghi sổ thành công, nhưng thiếu cấu hình Email!", state="warning", expanded=False)
                        st.error("❌ Chưa cấu hình [email_config] trong Streamlit Secrets. Dữ liệu bảng tính đã được ghi, nhưng chưa gửi được email.")
                else:
                    status.update(label="Ghi dữ liệu thất bại!", state="error")
            else:
                status.update(label="Tính toán thất bại!", state="error")

if __name__ == "__main__":
    main()
