from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import pyodbc
import json
from datetime import datetime, timedelta
import random

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ⚙️ Kết nối SQL Server
app.config['SQLALCHEMY_DATABASE_URI'] = (
    "mssql+pyodbc://DESKTOP-3074B3E\\MSSQLSERVER01/QLKhachSan?"
    "driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 🔧 Khởi tạo DB và Bcrypt
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# 🧩 Model Users
class User(db.Model):
    __tablename__ = 'Users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

# Helper: Hàm kết nối CSDL
def get_db_connection():
    """Tạo kết nối pyodbc đến CSDL."""
    try:
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=DESKTOP-3074B3E\\MSSQLSERVER01;"
            "DATABASE=QLKhachSan;"
            "Trusted_Connection=yes;"
        )
        return conn
    except Exception as e:
        print(f"Lỗi kết nối CSDL: {e}")
        return None

# =========================================================================
# == API LẤY DANH SÁCH BOOKING CỦA USER ==
# =========================================================================
@app.route('/api/my-bookings')
def api_get_my_bookings():
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Không thể kết nối CSDL"}), 500
    
    try:
        cursor = conn.cursor()
        
        query = """
            SELECT 
                b.id, b.booking_reference, b.status, b.total_amount,
                b.check_in_date, b.check_out_date, b.created_at,
                br.room_id, br.room_type_id, br.price_per_night, br.total_price,
                rt.name as room_type_name
            FROM bookings b
            JOIN booking_rooms br ON b.id = br.booking_id
            JOIN room_types rt ON br.room_type_id = rt.id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
        """
        
        cursor.execute(query, session['user_id'])
        rows = cursor.fetchall()
        
        # Nhóm các phòng theo booking
        bookings_dict = {}
        for row in rows:
            booking_id = row.id
            if booking_id not in bookings_dict:
                bookings_dict[booking_id] = {
                    "id": booking_id,
                    "booking_reference": row.booking_reference,
                    "status": row.status,
                    "total_amount": float(row.total_amount),
                    "check_in_date": row.check_in_date.isoformat(),
                    "check_out_date": row.check_out_date.isoformat(),
                    "created_at": row.created_at.isoformat(),
                    "rooms": []
                }
            
            bookings_dict[booking_id]["rooms"].append({
                "room_id": row.room_id,
                "room_type_id": row.room_type_id,
                "room_type_name": row.room_type_name,
                "price_per_night": float(row.price_per_night),
                "total_price": float(row.total_price) if row.total_price else None
            })
        
        conn.close()
        
        return jsonify({"bookings": list(bookings_dict.values())})
        
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Lỗi hệ thống: {str(e)}"}), 500

# =========================================================================
# == API HỦY BOOKING ==
# =========================================================================
@app.route('/api/cancel-booking/<int:booking_id>', methods=['POST'])
def api_cancel_booking(booking_id):
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Không thể kết nối CSDL"}), 500
    
    try:
        cursor = conn.cursor()
        
        # Kiểm tra booking thuộc về user
        check_query = "SELECT user_id, status FROM bookings WHERE id = ?"
        cursor.execute(check_query, booking_id)
        booking = cursor.fetchone()
        
        if not booking:
            return jsonify({"error": "Không tìm thấy booking!"}), 404
        
        if booking.user_id != session['user_id']:
            return jsonify({"error": "Bạn không có quyền hủy booking này!"}), 403
        
        if booking.status == 'cancelled':
            return jsonify({"error": "Booking đã được hủy trước đó!"}), 400
        
        # Cập nhật trạng thái booking
        update_query = "UPDATE bookings SET status = 'cancelled', updated_at = GETDATE() WHERE id = ?"
        cursor.execute(update_query, booking_id)
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Hủy booking thành công!"})
        
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Lỗi hệ thống: {str(e)}"}), 500

# =========================================================================
# == API TRẢ JSON PHÒNG VỚI CHỨC NĂNG TÌM KIẾM NÂNG CAO ==
# =========================================================================
@app.route('/api/rooms')
def api_get_rooms():
    """
    API lấy dữ liệu phòng từ schema mới - ĐÃ THÊM room_type_id
    """
    
    # 1. Lấy tất cả các tham số từ URL
    category_slug = request.args.get('category')
    
    # Lấy các tham số tìm kiếm (có thể là None)
    search_name = request.args.get('room_name')
    search_min_area = request.args.get('min_area')
    search_max_price = request.args.get('max_price')
    search_view = request.args.get('room_view')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Không thể kết nối CSDL"}), 500
    
    cursor = conn.cursor()
    
    # Câu query chính - ĐÃ THÊM room_type_id
    base_query = """
        SELECT 
            r.id AS room_id,
            rt.id AS room_type_id,
            rt.name AS title,
            rt.description,
            rt.base_price,
            rt.sale_price,
            rt.discount_percent,
            r.guest_capacity,
            r.bed_type,
            r.area,
            r.room_view,
            rc.slug AS category_slug,
            (SELECT 
                img.image_url, 
                img.image_alt,
                img.is_primary,
                img.display_order
             FROM room_images AS img
             WHERE img.room_id = r.id
             ORDER BY img.display_order
             FOR JSON PATH) AS images_json
        FROM rooms AS r
        JOIN room_types AS rt ON r.room_type_id = rt.id
        JOIN room_categories AS rc ON r.room_category_id = rc.id
    """
    
    # 2. Xây dựng điều kiện WHERE động
    params = []
    where_conditions = []
    
    if category_slug:
        where_conditions.append("rc.slug = ?")
        params.append(category_slug)
    
    # Thêm các điều kiện tìm kiếm
    if search_name:
        where_conditions.append("rt.name LIKE ?")
        params.append(f"%{search_name}%")

    if search_min_area:
        try:
            where_conditions.append("r.area >= ?")
            params.append(float(search_min_area))
        except ValueError:
            pass

    if search_max_price:
        try:
            where_conditions.append("rt.base_price <= ?")
            params.append(float(search_max_price))
        except ValueError:
            pass

    if search_view:
        where_conditions.append("r.room_view LIKE ?")
        params.append(f"%{search_view}%")
        
    # 3. Nối các điều kiện vào câu query
    if where_conditions:
        base_query += " WHERE " + " AND ".join(where_conditions)
            
    try:
        cursor.execute(base_query, tuple(params))
        rows = cursor.fetchall()
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Lỗi truy vấn: {e}"}), 500
    
    conn.close()

    # 4. Xử lý kết quả trả về - ĐÃ THÊM room_type_id
    rooms_list = []
    for row in rows:
        # Xử lý giá trị NULL từ CSDL
        sale_price = float(row.sale_price) if row.sale_price is not None else None
        base_price = float(row.base_price) if row.base_price is not None else 0
        
        # Chuyển đổi JSON string từ CSDL thành list
        images = json.loads(row.images_json) if row.images_json else []
        
        # Sắp xếp hình ảnh
        images.sort(key=lambda x: (not x.get('is_primary', False), x.get('display_order', 99)))

        rooms_list.append({
            "id": row.room_id,
            "room_type_id": row.room_type_id,
            "title": row.title,
            "description": row.description,
            "base_price": base_price,
            "sale_price": sale_price,
            "discount_percent": row.discount_percent,
            "guest_capacity": row.guest_capacity,
            "bed_type": row.bed_type,
            "area": float(row.area) if row.area else 0,
            "room_view": row.room_view,
            "category": row.category_slug,
            "images": images
        })

    return jsonify({"rooms": rooms_list})

# =========================================================================
# == API XỬ LÝ ĐẶT PHÒNG (ĐÃ SỬA LỖI BOOKING_ID) ==
# =========================================================================
@app.route('/api/booking', methods=['POST'])
def api_create_booking():
    """
    API xử lý đặt phòng và lưu vào database - ĐÃ SỬA LỖI booking_id
    """
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập để đặt phòng!"}), 401

    conn = None
    cursor = None
    try:
        # Lấy dữ liệu từ frontend
        booking_data = request.get_json()
        print(f"📥 Dữ liệu nhận được: {booking_data}")
        
        room_id = booking_data.get('roomId')
        room_type_id = booking_data.get('room_type_id')
        fullname = booking_data.get('fullname')
        email = booking_data.get('email')
        phone = booking_data.get('phone')
        checkin = booking_data.get('checkin')
        checkout = booking_data.get('checkout')
        adults = booking_data.get('adults', 1)
        children = booking_data.get('children', 0)
        notes = booking_data.get('notes', '')
        
        # Validate dữ liệu
        if not all([room_id, room_type_id, fullname, email, phone, checkin, checkout]):
            return jsonify({"error": "Vui lòng điền đầy đủ thông tin!"}), 400

        user_id = session['user_id']
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Không thể kết nối CSDL"}), 500

        cursor = conn.cursor()

        # 1. Lấy thông tin phòng và giá
        room_query = """
            SELECT r.id, r.room_type_id, rt.base_price, rt.sale_price
            FROM rooms r
            JOIN room_types rt ON r.room_type_id = rt.id
            WHERE r.id = ?
        """
        cursor.execute(room_query, room_id)
        room = cursor.fetchone()
        
        if not room:
            conn.close()
            return jsonify({"error": "Không tìm thấy phòng!"}), 404

        # Tính giá phòng (ưu tiên sale_price)
        price_per_night = float(room.sale_price) if room.sale_price else float(room.base_price)
        
        # Tính số đêm và tổng tiền
        checkin_date = datetime.strptime(checkin, '%Y-%m-%d').date()
        checkout_date = datetime.strptime(checkout, '%Y-%m-%d').date()
        nights = (checkout_date - checkin_date).days
        
        if nights <= 0:
            return jsonify({"error": "Ngày checkout phải sau ngày checkin!"}), 400
            
        total_amount = price_per_night * nights

        # 2. Tạo booking reference
        booking_ref = generate_booking_reference(cursor)

        print(f"🔨 Bắt đầu tạo booking...")
        print(f"   - User ID: {user_id}")
        print(f"   - Room ID: {room_id}")
        print(f"   - Room Type ID: {room_type_id}")
        print(f"   - Check-in: {checkin_date}, Check-out: {checkout_date}")
        print(f"   - Số đêm: {nights}, Tổng tiền: {total_amount}")

        # 🔧 QUAN TRỌNG: BẮT ĐẦU TRANSACTION
        cursor.execute("BEGIN TRANSACTION")

        try:
            # 3. Insert vào bảng bookings TRƯỚC
            booking_query = """
                INSERT INTO bookings (
                    user_id, booking_reference, status, total_amount, 
                    special_requests, adult_count, child_count, 
                    check_in_date, check_out_date, created_at
                ) OUTPUT INSERTED.id 
                VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, GETDATE())
            """
            
            cursor.execute(booking_query, 
                          user_id, booking_ref, total_amount, notes, 
                          adults, children, checkin_date, checkout_date)
            
            # Lấy booking_id vừa tạo
            booking_row = cursor.fetchone()
            if not booking_row:
                raise Exception("Không thể lấy booking_id sau khi insert")
            
            booking_id = booking_row[0]
            
            print(f"✅ Đã tạo booking thành công với ID: {booking_id}")

            # 4. Insert vào bảng booking_rooms VỚI booking_id hợp lệ
            booking_room_query = """
                INSERT INTO booking_rooms (
                    booking_id, room_id, room_type_id, quantity,
                    price_per_night, total_price, guest_names, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, GETDATE())
            """
            
            guest_names_json = json.dumps([{"name": fullname, "is_primary": True}])
            
            cursor.execute(booking_room_query,
                          booking_id, room_id, room_type_id,
                          price_per_night, total_amount, guest_names_json)

            print(f"✅ Đã thêm booking_rooms với booking_id: {booking_id}")

            # 5. Insert vào bảng booking_guests
            guest_query = """
                INSERT INTO booking_guests (
                    booking_id, full_name, email, phone, is_primary_guest
                ) VALUES (?, ?, ?, ?, 1)
            """
            cursor.execute(guest_query, booking_id, fullname, email, phone)

            print(f"✅ Đã thêm thông tin khách cho booking_id: {booking_id}")

            # 6. Cập nhật room_availability (nếu có bảng này)
            try:
                # Kiểm tra xem bảng room_availability có tồn tại không
                check_table_query = """
                    SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_NAME = 'room_availability'
                """
                cursor.execute(check_table_query)
                if cursor.fetchone()[0] > 0:
                    # Tạo các ngày cần cập nhật
                    current_date = checkin_date
                    while current_date < checkout_date:
                        # Kiểm tra xem đã có bản ghi cho ngày này chưa
                        check_date_query = """
                            SELECT COUNT(*) FROM room_availability 
                            WHERE room_type_id = ? AND date = ?
                        """
                        cursor.execute(check_date_query, room_type_id, current_date)
                        
                        if cursor.fetchone()[0] == 0:
                            # Chưa có, tạo mới
                            insert_availability_query = """
                                INSERT INTO room_availability 
                                (room_type_id, date, total_quantity, booked_quantity)
                                VALUES (?, ?, 10, 1)
                            """
                            cursor.execute(insert_availability_query, room_type_id, current_date)
                        else:
                            # Đã có, cập nhật
                            update_availability_query = """
                                UPDATE room_availability 
                                SET booked_quantity = booked_quantity + 1
                                WHERE room_type_id = ? AND date = ?
                            """
                            cursor.execute(update_availability_query, room_type_id, current_date)
                        
                        current_date += timedelta(days=1)
                    
                    print(f"✅ Đã cập nhật availability cho room_type_id: {room_type_id}")
                else:
                    print("ℹ️ Bảng room_availability không tồn tại, bỏ qua bước này")
            except Exception as availability_error:
                print(f"⚠️ Không thể cập nhật availability: {availability_error}")
                # Không rollback vì đây không phải lỗi critical

            # 🔧 COMMIT TRANSACTION - TẤT CẢ THÀNH CÔNG
            cursor.execute("COMMIT TRANSACTION")
            conn.commit()

            print(f"🎉 Đặt phòng hoàn tất! Booking ID: {booking_id}, Reference: {booking_ref}")

            return jsonify({
                "success": True,
                "message": "Đặt phòng thành công!",
                "booking_reference": booking_ref,
                "booking_id": booking_id,
                "total_amount": total_amount
            })

        except Exception as transaction_error:
            # 🔧 ROLLBACK NẾU CÓ LỖI
            cursor.execute("ROLLBACK TRANSACTION")
            print(f"❌ Lỗi trong transaction: {transaction_error}")
            raise transaction_error

    except Exception as e:
        # Xử lý lỗi tổng
        if conn:
            try:
                cursor.execute("ROLLBACK TRANSACTION")
            except:
                pass
            conn.close()
        
        print(f"❌ Lỗi khi đặt phòng: {str(e)}")
        return jsonify({"error": f"Lỗi hệ thống: {str(e)}"}), 500

def generate_booking_reference(cursor):
    """Tạo mã booking reference duy nhất"""
    prefix = "BK"
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = str(random.randint(1000, 9999))
    booking_ref = f"{prefix}{date_part}{random_part}"
    
    # Kiểm tra trùng lặp
    check_query = "SELECT COUNT(*) FROM bookings WHERE booking_reference = ?"
    cursor.execute(check_query, booking_ref)
    if cursor.fetchone()[0] > 0:
        # Nếu trùng, tạo lại
        return generate_booking_reference(cursor)
    
    return booking_ref

# =========================================================================
# == API LẤY THÔNG TIN BOOKING ==
# =========================================================================
@app.route('/api/bookings/<int:booking_id>')
def api_get_booking(booking_id):
    """
    API lấy thông tin chi tiết booking
    """
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Không thể kết nối CSDL"}), 500

    try:
        cursor = conn.cursor()
        
        # Lấy thông tin booking
        booking_query = """
            SELECT 
                b.id, b.booking_reference, b.status, b.total_amount,
                b.special_requests, b.adult_count, b.child_count,
                b.check_in_date, b.check_out_date, b.created_at,
                u.name as user_name, u.email as user_email
            FROM bookings b
            JOIN Users u ON b.user_id = u.id
            WHERE b.id = ? AND b.user_id = ?
        """
        
        cursor.execute(booking_query, booking_id, session['user_id'])
        booking = cursor.fetchone()
        
        if not booking:
            return jsonify({"error": "Không tìm thấy booking!"}), 404

        # Lấy thông tin phòng trong booking
        rooms_query = """
            SELECT 
                br.room_id, br.room_type_id, br.quantity,
                br.price_per_night, br.total_price, br.guest_names,
                rt.name as room_type_name,
                r.room_view, r.area
            FROM booking_rooms br
            JOIN room_types rt ON br.room_type_id = rt.id
            JOIN rooms r ON br.room_id = r.id
            WHERE br.booking_id = ?
        """
        
        cursor.execute(rooms_query, booking_id)
        rooms = cursor.fetchall()

        # Lấy thông tin khách
        guests_query = """
            SELECT full_name, email, phone, is_primary_guest
            FROM booking_guests
            WHERE booking_id = ?
        """
        
        cursor.execute(guests_query, booking_id)
        guests = cursor.fetchall()

        conn.close()

        # Format dữ liệu trả về
        booking_data = {
            "id": booking.id,
            "booking_reference": booking.booking_reference,
            "status": booking.status,
            "total_amount": float(booking.total_amount),
            "special_requests": booking.special_requests,
            "adult_count": booking.adult_count,
            "child_count": booking.child_count,
            "check_in_date": booking.check_in_date.isoformat(),
            "check_out_date": booking.check_out_date.isoformat(),
            "created_at": booking.created_at.isoformat(),
            "user_name": booking.user_name,
            "user_email": booking.user_email,
            "rooms": [],
            "guests": []
        }

        # Thêm thông tin phòng
        for room in rooms:
            booking_data["rooms"].append({
                "room_id": room.room_id,
                "room_type_id": room.room_type_id,
                "room_type_name": room.room_type_name,
                "quantity": room.quantity,
                "price_per_night": float(room.price_per_night),
                "total_price": float(room.total_price),
                "guest_names": json.loads(room.guest_names) if room.guest_names else [],
                "room_view": room.room_view,
                "area": float(room.area) if room.area else 0
            })

        # Thêm thông tin khách
        for guest in guests:
            booking_data["guests"].append({
                "full_name": guest.full_name,
                "email": guest.email,
                "phone": guest.phone,
                "is_primary_guest": bool(guest.is_primary_guest)
            })

        return jsonify(booking_data)

    except Exception as e:
        conn.close()
        return jsonify({"error": f"Lỗi hệ thống: {str(e)}"}), 500

# =========================================================================
# == CÁC ROUTE KHÁC ==
# =========================================================================

# 🏠 Trang đăng nhập / đăng ký
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('TrangChu'))
    return render_template('Login&Registration.html')

# 📝 Xử lý đăng ký
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash("Email đã tồn tại!", "error")
            return redirect(url_for('index'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(name=name, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        flash("Đăng ký thành công! Vui lòng đăng nhập.", "success")
        return redirect(url_for('index'))
    return render_template('Login&Registration.html')

# 🔑 Xử lý đăng nhập
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['name'] = user.name
            flash("Đăng nhập thành công!", "success")
            return redirect(url_for('TrangChu'))
        else:
            flash("Sai email hoặc mật khẩu!", "error")
            return redirect(url_for('index'))
    return render_template('Login&Registration.html')

# 🏡 Trang chủ
@app.route('/TrangChu')
def TrangChu():
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('TrangChu.html', logged_in=logged_in, name=name)

# 🎯 Trang Sale Rooms
@app.route('/SaleRooms')
def SaleRooms():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem phòng ưu đãi!", "warning")
        return redirect(url_for('index'))
    
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('SaleRooms.html', logged_in=logged_in, name=name)

# Trang giới thiệu
@app.route('/GioiThieu')
def GioiThieu():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem phòng ưu đãi!", "warning")
        return redirect(url_for('index'))
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('GioiThieu.html', logged_in=logged_in, name=name)

# Trang Tiên nghi
@app.route('/tiennghi')
def tiennghi():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem phòng ưu đãi!", "warning")
        return redirect(url_for('index'))
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('tiennghi.html', logged_in=logged_in, name=name)
    
# Thông tin cá nhân
@app.route('/TTCN')
def TTCN():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem thông tin cá nhân!", "warning")
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash("Người dùng không tồn tại!", "error")
        return redirect(url_for('index'))
    
    return render_template('TTCN.html', user=user)

# Phong doi
@app.route('/phongdoi')
def phongdoi():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem phòng đôi!", "warning")
        return redirect(url_for('index'))
    
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('phongdoi.html', logged_in=logged_in, name=name)

# Phong don
@app.route('/phongdon')
def phongdon():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem phòng đơn!", "warning")
        return redirect(url_for('index'))
    
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('phongdon.html', logged_in=logged_in, name=name)

# LienHe
@app.route('/Lienhe')
def Lienhe():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem liên hệ!", "warning")
        return redirect(url_for('index'))
    
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('Lienhe.html', logged_in=logged_in, name=name)

# Thanh toán
@app.route('/ThanhToan')
def ThanhToan():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để thanh toán!", "warning")
        return redirect(url_for('index'))
    
    logged_in = 'user_id' in session
    name = session.get('name')
    return render_template('ThanhToan.html', logged_in=logged_in, name=name)

# 📄 Xem chi tiết phòng
@app.route('/Xemchitiet/<int:room_id>')
def xem_chi_tiet(room_id):
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập để xem chi tiết phòng!", "warning")
        return redirect(url_for('index'))
        
    conn = get_db_connection()
    if not conn:
        flash("Lỗi kết nối CSDL!", "error")
        return redirect(url_for('TrangChu'))
        
    cursor = conn.cursor()
    
    # Query để lấy thông tin chi tiết của 1 phòng
    query = """
        SELECT 
            r.id, rt.name, rt.description, rt.base_price, rt.sale_price,
            r.guest_capacity, r.bed_type, r.area, r.room_view, r.amenities,
            rc.name as category_name, rt.id as room_type_id
        FROM rooms AS r
        JOIN room_types AS rt ON r.room_type_id = rt.id
        JOIN room_categories AS rc ON r.room_category_id = rc.id
        WHERE r.id = ?
    """
    
    # Query để lấy tất cả hình ảnh của phòng đó
    images_query = """
        SELECT image_url, image_alt, is_primary, display_order 
        FROM room_images
        WHERE room_id = ?
        ORDER BY display_order
    """
    
    try:
        cursor.execute(query, room_id)
        room_data = cursor.fetchone()
        
        cursor.execute(images_query, room_id)
        images_data = cursor.fetchall()
    except Exception as e:
        conn.close()
        flash(f"Lỗi truy vấn: {e}", "error")
        return redirect(url_for('TrangChu'))
        
    conn.close()

    if not room_data:
        flash("Không tìm thấy phòng!", "error")
        return redirect(url_for('TrangChu'))

    # Xử lý dữ liệu
    room_details = {
        "id": room_data.id,
        "title": room_data.name,
        "description": room_data.description,
        "base_price": float(room_data.base_price) if room_data.base_price else 0,
        "sale_price": float(room_data.sale_price) if room_data.sale_price else None,
        "guest_capacity": room_data.guest_capacity,
        "bed_type": room_data.bed_type,
        "area": float(room_data.area) if room_data.area else 0,
        "room_view": room_data.room_view,
        "room_type_id": room_data.room_type_id,  # THÊM DÒNG NÀY
        "category": room_data.category_name,
        "amenities": json.loads(room_data.amenities) if room_data.amenities else [],
        "images": [{"url": img.image_url, "alt": img.image_alt, "is_primary": img.is_primary} for img in images_data]
    }

    logged_in = 'user_id' in session
    name = session.get('name')
    
    return render_template("Xemchitiet.html", room=room_details, logged_in=logged_in, name=name)

# 🚪 Đăng xuất
@app.route('/logout')
def logout():
    session.clear()
    flash("Bạn đã đăng xuất!", "info")
    return redirect(url_for('index'))

# 🚀 Chạy Flask
if __name__ == '__main__':
    # Kiểm tra kết nối CSDL trước khi chạy
    print("Đang kiểm tra kết nối CSDL...")
    
    # Khởi tạo database (tạo bảng Users nếu chưa tồn tại)
    try:
        with app.app_context():
            db.create_all()
            print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️ Lỗi khi khởi tạo database: {e}")
    
    # Chạy ứng dụng
    app.run(debug=True, host='0.0.0.0', port=5000)