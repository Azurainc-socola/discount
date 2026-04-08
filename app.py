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
            
            rows_to_append.append([
                inv_val, "", code, qty, f"${unit_price:.2f}", f"${line_total:.2f}"
            ])
            is_first_row = False
            
        rows_to_append.append(["", f"${total_discount:.2f}", "TỔNG CỘNG", total_qty, "-", f"${total_discount:.2f}"])
        rows_to_append.append(["", "", "", "", "", ""]) 
        
        ws_total.append_rows(rows_to_append)
        return len(rows_to_append)
    except Exception as e:
        st.error(f"❌ Lỗi khi ghi vào sheet {SHEET_TOTAL_DISCOUNT}: {e}")
        return 0

def send_email_report(sender_email, sender_password, client_name, invoice_number, total_discount, item_counts, sheet_url, new_rows_count):
    try:
        items_html = ""
        for code, qty in item_counts.items():
            items_html += f"<li><b>{code}</b>: {qty} cái</li>"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2E86C1;">Báo Cáo Khấu Trừ Azura - Khách Hàng {client_name}</h2>
            <p>Hệ thống vừa cập nhật dữ liệu thành công cho <b>Invoice {invoice_number}</b>.</p>
            
            <div style="background-color: #f9f9f9; padding: 15px; border-left: 5px solid #2E86C1; margin-bottom: 20px;">
                <h3 style="color: #D35400; margin-top: 0;">💰 Tổng Discount: ${total_discount:.2f}</h3>
                <p style="margin-bottom: 5px;">📍 <b>Vị trí ghi:</b> Tab <code>{SHEET_TOTAL_DISCOUNT}</code></p>
                <p style="margin-bottom: 5px;">📝 <b>Số dòng mới:</b> {new_rows_count} dòng</p>
                <p style="margin-top: 10px;">🔗 <b>Link truy cập Sheet:</b> <a href="{sheet_url}" target="_blank">Nhấn vào đây để xem chi tiết</a></p>
            </div>
            
            <h4>📦 Chi tiết Items (Tổng hợp):</h4>
            <ul>
                {items_html}
            </ul>
            
            <hr>
            <p style="font-size: 11px; color: #7f8c8d;">
                <i>Email tự động gửi bởi VibeCoder Assistant lúc {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}.</i>
            </p>
        </body>
        </html>
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
    except Exception as e:
        st.error(f"⚠️ Không thể gửi email báo cáo: {e}")
        return False

# ==========================================
# UI & LUỒNG TƯƠNG TÁC CHÍNH
# ==========================================
def main():
    st.title("🚀 Azura Vibe - Cập Nhật Khấu Trừ")
    st.markdown("Chọn Khách hàng và nhập số Invoice để tính toán và gửi báo cáo.")
    
    gc = authenticate_google_sheets()

    with st.form("invoice_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_client_name = st.selectbox("👥 Chọn Khách hàng:", options=list(CLIENT_SHEETS.keys()))
            invoice_number = st.text_input("👉 Nhập Invoice Number:", placeholder="Ví dụ: 412")
        with col2:
            st.info(f"**📧 Email tự động gửi đến:**\n\n**To:** {FIXED_TO_EMAIL}\n\n**CC:** {FIXED_CC_EMAILS}")
            st.markdown("<br>", unsafe_allow_html=True)
            submit_btn = st.form_submit_button("⚙️ Chạy Quy Trình", use_container_width=True)

    if submit_btn:
        invoice_number = invoice_number.strip()
        if not invoice_number:
            st.warning("⚠️ Vui lòng nhập mã Invoice!")
            return

        sheet_id = CLIENT_SHEETS[selected_client_name]
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid=0"

        with st.status(f"Đang xử lý Invoice {invoice_number}...", expanded=True) as status:
            try:
                sh = gc.open_by_key(sheet_id)
            except Exception:
                status.update(label="Lỗi kết nối Sheet!", state="error")
                st.stop()

            # ---------------------------------------------------------
            # 💡 VIBECODER UPDATE: KIỂM TRA TRÙNG LẶP INVOICE (CHỐNG NHÂN ĐÔI)
            # ---------------------------------------------------------
            st.write(f"🛡️ Đang kiểm tra lịch sử dữ liệu...")
            try:
                ws_total = sh.worksheet(SHEET_TOTAL_DISCOUNT)
                # Lấy toàn bộ dữ liệu cột A và xóa khoảng trắng dư thừa
                existing_invoices = [str(val).strip() for val in ws_total.col_values(1)]
                
                # Nếu Invoice đã tồn tại -> Phanh lại ngay lập tức
                if invoice_number in existing_invoices:
                    status.update(label="Phát hiện trùng lặp!", state="error")
                    st.error(f"❌ **CẢNH BÁO:** Invoice `{invoice_number}` đã được tính toán và ghi sổ trước đó!")
                    st.warning("Hệ thống đã tự động dừng lại để tránh bị nhân đôi (Duplicate) tiền khấu trừ. Vui lòng vào file Sheet để kiểm tra lại lịch sử.")
                    st.link_button(f"🔗 Mở Sheet kiểm tra lịch sử ({selected_client_name})", sheet_url)
                    st.stop() # Lệnh này sẽ ngắt hoàn toàn tiến trình chạy tiếp theo
            except gspread.exceptions.WorksheetNotFound:
                # Nếu tab 'Total discount' chưa được tạo, bỏ qua bước kiểm tra này
                pass
            except Exception as e:
                st.error(f"Lỗi khi kiểm tra trùng lặp: {e}")
                st.stop()
            # ---------------------------------------------------------

            st.write(f"🔍 Đang nạp bảng giá từ `{SHEET_PRODUCT_CODE}`...")
            discount_map = get_product_discount_map(sh)
            if not discount_map: return
            
            st.write(f"⚙️ Đang tính toán dữ liệu...")
            total_discount, item_counts = calculate_invoice_discount(sh, invoice_number, discount_map)
            
            if total_discount is not None:
                st.write(f"📝 Đang ghi vào `{SHEET_TOTAL_DISCOUNT}`...")
                new_rows_count = write_total_discount(sh, invoice_number, total_discount, item_counts, discount_map)
                
                if new_rows_count > 0:
                    try:
                        st.write(f"📩 Đang gửi email...")
                        sender_email = st.secrets["email_config"]["sender_email"]
                        sender_password = st.secrets["email_config"]["app_password"]
                        
                        email_sent = send_email_report(
                            sender_email, sender_password, selected_client_name, 
                            invoice_number, total_discount, item_counts, sheet_url, new_rows_count
                        )
                        
                        if email_sent:
                            status.update(label=f"Hoàn tất Invoice {invoice_number}!", state="complete", expanded=False)
                            st.success(f"✅ Đã ghi thành công **{new_rows_count} dòng** vào tab `{SHEET_TOTAL_DISCOUNT}`!")
                            st.link_button("🔗 Mở Google Sheet Kiểm Tra", sheet_url)
                            
                            st.markdown("---")
                            table_data = []
                            for code, qty in item_counts.items():
                                up = discount_map.get(code, 0.0)
                                table_data.append({"Mã SP": code, "Số Lượng": qty, "Đơn Giá": f"${up:.2f}", "Thành Tiền": f"${qty*up:.2f}"})
                            df = pd.DataFrame(table_data)
                            st.dataframe(df, use_container_width=True, hide_index=True)
                            st.balloons()
                    except KeyError:
                        st.error("❌ Thiếu cấu hình [email_config] trong Secrets.")
                else:
                    status.update(label="Ghi dữ liệu thất bại!", state="error")

if __name__ == "__main__":
    main()
