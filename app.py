"""
تطبيق رفع مشاريع الطلاب
نظام ديناميكي متكامل يستخدم Streamlit + Supabase + Google Drive
"""

import streamlit as st
from supabase import create_client, Client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json
from datetime import datetime
import io

# ===========================
# 1. إعداد الاتصالات
# ===========================

@st.cache_resource
def init_supabase() -> Client:
    """إنشاء اتصال مع Supabase"""
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"خطأ في الاتصال بقاعدة البيانات: {str(e)}")
        st.stop()

@st.cache_resource
def init_google_drive():
    """إنشاء اتصال مع Google Drive API"""
    try:
        # تحويل secrets إلى dictionary
        credentials_dict = dict(st.secrets["google_credentials"])
        
        # إنشاء credentials من dictionary
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        # بناء خدمة Drive
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"خطأ في الاتصال بـ Google Drive: {str(e)}")
        st.stop()

# ===========================
# 2. دوال قاعدة البيانات
# ===========================

def get_system_config(supabase: Client):
    """جلب إعدادات النظام (السنة والفصل الحالي)"""
    try:
        response = supabase.table('system_config').select('*').limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            st.error("لم يتم العثور على إعدادات النظام في قاعدة البيانات")
            return None
    except Exception as e:
        st.error(f"خطأ في جلب إعدادات النظام: {str(e)}")
        return None

def get_classes(supabase: Client):
    """جلب قائمة المراحل والشعب"""
    try:
        response = supabase.table('classes').select('*').order('grade_level').execute()
        return response.data
    except Exception as e:
        st.error(f"خطأ في جلب قائمة الصفوف: {str(e)}")
        return []

def save_submission(supabase: Client, data: dict):
    """حفظ بيانات التسليم في قاعدة البيانات"""
    try:
        response = supabase.table('submissions').insert(data).execute()
        return response.data
    except Exception as e:
        raise Exception(f"فشل حفظ البيانات: {str(e)}")

# ===========================
# 3. دوال Google Drive
# ===========================

def find_or_create_folder(service, folder_name: str, parent_id: str = None):
    """
    البحث عن مجلد أو إنشاؤه إذا لم يكن موجوداً
    
    Args:
        service: خدمة Google Drive
        folder_name: اسم المجلد
        parent_id: معرف المجلد الأب (None للمجلد الجذر)
    
    Returns:
        معرف المجلد
    """
    try:
        # البحث عن المجلد
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            pageSize=1
        ).execute()
        
        files = results.get('files', [])
        
        if files:
            # المجلد موجود
            return files[0]['id']
        else:
            # إنشاء مجلد جديد
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
            
            folder = service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            return folder['id']
    except Exception as e:
        raise Exception(f"خطأ في إنشاء/البحث عن المجلد '{folder_name}': {str(e)}")

def create_folder_structure(service, year: str, semester: str, grade: str, section: str):
    """
    إنشاء هيكلة المجلدات: Year > Semester > Grade > Section
    
    Returns:
        معرف المجلد النهائي (Section folder)
    """
    try:
        # 1. مجلد السنة
        year_folder_id = find_or_create_folder(service, year)
        
        # 2. مجلد الفصل
        semester_folder_id = find_or_create_folder(service, semester, year_folder_id)
        
        # 3. مجلد المرحلة
        grade_folder_id = find_or_create_folder(service, grade, semester_folder_id)
        
        # 4. مجلد الشعبة
        section_folder_id = find_or_create_folder(service, section, grade_folder_id)
        
        return section_folder_id
    except Exception as e:
        raise Exception(f"خطأ في إنشاء هيكلة المجلدات: {str(e)}")

def upload_file_to_drive(service, file_content, file_name: str, folder_id: str):
    """
    رفع ملف إلى Google Drive
    
    Args:
        service: خدمة Google Drive
        file_content: محتوى الملف
        file_name: اسم الملف
        folder_id: معرف المجلد المستهدف
    
    Returns:
        رابط الملف
    """
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        # إنشاء ملف مؤقت في الذاكرة
        fh = io.BytesIO(file_content)
        
        media = MediaFileUpload(
            io.BytesIO(file_content),
            mimetype='application/pdf',
            resumable=True
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # جعل الملف قابل للعرض لأي شخص لديه الرابط
        service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        raise Exception(f"فشل رفع الملف: {str(e)}")

# ===========================
# 4. واجهة Streamlit
# ===========================

def main():
    # إعداد الصفحة
    st.set_page_config(
        page_title="نظام رفع المشاريع الطلابية",
        page_icon="📚",
        layout="centered"
    )
    
    # تهيئة الاتصالات
    supabase = init_supabase()
    drive_service = init_google_drive()
    
    # جلب إعدادات النظام
    config = get_system_config(supabase)
    if not config:
        st.stop()
    
    current_year = config['current_year']
    current_semester = config['current_semester']
    
    # العنوان الرئيسي
    st.title("📚 نظام رفع المشاريع الطلابية")
    st.markdown(f"### السنة الدراسية: **{current_year}** | الفصل: **{current_semester}**")
    st.markdown("---")
    
    # جلب قائمة الصفوف
    classes = get_classes(supabase)
    if not classes:
        st.error("لا توجد صفوف مسجلة في النظام")
        st.stop()
    
    # تجهيز البيانات للقوائم المنسدلة
    grades = sorted(list(set([c['grade_level'] for c in classes])))
    
    # نموذج الإدخال
    with st.form("submission_form"):
        st.subheader("📝 معلومات الطالب والمشروع")
        
        # اختيار المرحلة
        selected_grade = st.selectbox(
            "اختر المرحلة الدراسية",
            grades,
            help="اختر المرحلة التي تنتمي إليها"
        )
        
        # تصفية الشعب بناءً على المرحلة المختارة
        sections = [c['section_name'] for c in classes if c['grade_level'] == selected_grade]
        
        # اختيار الشعبة
        selected_section = st.selectbox(
            "اختر الشعبة",
            sections,
            help="اختر شعبتك الدراسية"
        )
        
        # اسم الطالب
        student_name = st.text_input(
            "اسم الطالب الثلاثي",
            placeholder="مثال: أحمد محمد علي",
            help="أدخل الاسم الكامل باللغة العربية"
        )
        
        # عنوان المشروع
        project_title = st.text_input(
            "عنوان المشروع",
            placeholder="مثال: الطاقة المتجددة ومستقبلها",
            help="أدخل عنوان المشروع بشكل واضح"
        )
        
        # رفع الملف
        uploaded_file = st.file_uploader(
            "اختر ملف المشروع (PDF فقط)",
            type=['pdf'],
            help="الحد الأقصى لحجم الملف: 10 MB"
        )
        
        # زر الإرسال
        submitted = st.form_submit_button("🚀 رفع المشروع", use_container_width=True)
    
    # معالجة الإرسال
    if submitted:
        # التحقق من صحة البيانات
        errors = []
        
        if not student_name or len(student_name.strip()) < 6:
            errors.append("⚠️ يجب إدخال اسم الطالب الثلاثي (6 أحرف على الأقل)")
        
        if not project_title or len(project_title.strip()) < 5:
            errors.append("⚠️ يجب إدخال عنوان المشروع (5 أحرف على الأقل)")
        
        if uploaded_file is None:
            errors.append("⚠️ يجب اختيار ملف PDF للمشروع")
        
        if uploaded_file and uploaded_file.size > 10 * 1024 * 1024:  # 10 MB
            errors.append("⚠️ حجم الملف يتجاوز الحد المسموح (10 MB)")
        
        # عرض الأخطاء
        if errors:
            for error in errors:
                st.error(error)
        else:
            # بدء عملية الرفع
            with st.spinner("جاري رفع المشروع... الرجاء الانتظار"):
                try:
                    # 1. إنشاء هيكلة المجلدات في Drive
                    folder_id = create_folder_structure(
                        drive_service,
                        current_year,
                        current_semester,
                        selected_grade,
                        selected_section
                    )
                    
                    # 2. تجهيز اسم الملف
                    # إزالة أي أحرف غير صالحة من اسم الملف
                    safe_student_name = student_name.replace(" ", "_")
                    file_name = f"{safe_student_name}_{project_title[:30]}.pdf"
                    
                    # 3. رفع الملف إلى Drive
                    file_content = uploaded_file.read()
                    file_url = upload_file_to_drive(
                        drive_service,
                        file_content,
                        file_name,
                        folder_id
                    )
                    
                    # 4. حفظ البيانات في قاعدة البيانات
                    submission_data = {
                        'student_name': student_name.strip(),
                        'project_title': project_title.strip(),
                        'file_url': file_url,
                        'grade_level': selected_grade,
                        'section': selected_section,
                        'year': current_year,
                        'semester': current_semester,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    save_submission(supabase, submission_data)
                    
                    # 5. عرض رسالة النجاح
                    st.success("✅ تم رفع المشروع بنجاح!")
                    st.balloons()
                    
                    # عرض تفاصيل التسليم
                    st.info(f"""
                    **تفاصيل التسليم:**
                    - **الطالب:** {student_name}
                    - **المشروع:** {project_title}
                    - **المرحلة:** {selected_grade}
                    - **الشعبة:** {selected_section}
                    - **التاريخ:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
                    """)
                    
                    # رابط الملف
                    st.markdown(f"[🔗 عرض الملف في Google Drive]({file_url})")
                    
                except Exception as e:
                    st.error(f"❌ حدث خطأ أثناء رفع المشروع: {str(e)}")
                    st.warning("لم يتم حفظ البيانات. الرجاء المحاولة مرة أخرى.")
    
    # ملاحظات في الأسفل
    st.markdown("---")
    st.caption("💡 **ملاحظات:**")
    st.caption("• تأكد من رفع ملفات PDF فقط")
    st.caption("• الحد الأقصى لحجم الملف: 10 ميجابايت")
    st.caption("• سيتم حفظ المشروع في Google Drive تلقائياً")

# ===========================
# 5. تشغيل التطبيق
# ===========================

if __name__ == "__main__":
    main()
