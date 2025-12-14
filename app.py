import streamlit as st
import openai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json
import io
import random
from PIL import Image

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Generador Exámenes Ginecología - Nivel Clínico + Imágenes", layout="wide")

st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px !important; font-family: 'Arial'; }
    .status-ok { color: green; font-weight: bold; }
    .status-err { color: red; font-weight: bold; }
    div[data-testid="stExpander"] div[role="button"] p {
        font-size: 16px;
        font-weight: bold;
    }
    img {
        border: 1px solid #ddd;
        border-radius: 4px;
        padding: 5px;
        max-width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

# --- ESTADO DE LA SESIÓN ---
if 'files_data' not in st.session_state:
    st.session_state['files_data'] = {} # Estructura: {'nombre': {'text': '...', 'images': [img_bytes]}}
if 'files_processed_names' not in st.session_state:
    st.session_state['files_processed_names'] = []
if 'questions_db' not in st.session_state:
    st.session_state['questions_db'] = {}

# --- FUNCIONES DE LÓGICA ---

def extract_content_robust(file):
    """Extrae Texto e IMÁGENES de PDF/PPT"""
    try:
        reader = PdfReader(file)
        text = ""
        extracted_images = []
        
        for page in reader.pages:
            # 1. Extraer Texto
            t = page.extract_text()
            if t: text += t + "\n"
            
            # 2. Extraer Imágenes
            try:
                for img_file_obj in page.images:
                    extracted_images.append(img_file_obj.data)
            except:
                pass # Si falla una imagen, continuamos
        
        # Validación
        if len(text.strip()) < 50:
            return None, [], "⚠️ PDF sin texto reconocible (posiblemente imágenes)"
            
        return text, extracted_images, "OK"
    except Exception as e:
        return None, [], f"❌ Error: {str(e)}"

def call_openai_generator(api_key, text, na, nb, nc, topic):
    """Llama a GPT-4o con un PROMPT AVANZADO MÉDICO"""
    client = openai.OpenAI(api_key=api_key)
    
    system_prompt = """
    Eres un Catedrático de Obstetricia y Ginecología con experiencia clínica hospitalaria. 
    Tu objetivo es crear preguntas de examen para alumnos de 4º de Medicina.
    
    INSTRUCCIONES ESPECÍFICAS POR TIPO:
    
    1. TIPO A (Conocimiento Directo): Definiciones, clasificaciones o datos epidemiológicos.
    2. TIPO B (Integrado): Fisiopatología, relación entre farmacología y clínica.
    
    3. TIPO C (CASOS CLÍNICOS CON POSIBILIDAD DE IMAGEN):
       - Redacta "Viñetas Clínicas" realistas.
       - Si el caso clínico se beneficiaría de una imagen (ej: Ecografía, Mamografía, Histología), 
         redacta el enunciado asumiendo que el alumno estará viendo una imagen adjunta.
         Ejemplo: "Paciente de 30 años... (clínica)... Se realiza ecografía transvaginal obteniendo la siguiente imagen (ver abajo). ¿Cuál es el diagnóstico?"
       - OJO: No describas excesivamente la imagen si la idea es que el alumno la interprete, pero da contexto clínico (FUM, Beta-HCG, dolor).
       
       Estructura OBLIGATORIA Tipo C:
       - PERFIL: Edad, Paridad, Antecedentes.
       - CLÍNICA: Motivo consulta, constantes (TA, FC).
       - PRUEBAS: Menciona que se realiza la prueba de imagen pertinente.
       - PREGUNTA: Diagnóstico, Actitud o Tratamiento.
    
    FORMATO DE SALIDA (JSON):
    {
        "questions": [
            {
                "type": "Tipo A/B/C",
                "question": "Enunciado...",
                "options": ["a) ...", "b) ...", "c) ...", "d) ..."],
                "answer_index": 0,
                "justification": "..."
            }
        ]
    }
    """
    
    user_prompt = f"""
    Tema: {topic}.
    Genera rigurosamente:
    - {na} preguntas Tipo A.
    - {nb} preguntas Tipo B.
    - {nc} preguntas Tipo C (Casos Clínicos Complejos).
    
    TEXTO BASE:
    {text[:25000]}...
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}, 
                      {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("questions", [])
    except Exception as e:
        st.error(f"Error OpenAI: {e}")
        return []

def create_exam_docx(questions):
    """Genera el Word final incluyendo IMÁGENES si existen"""
    doc = Document()
    
    # Cabecera
    table = doc.add_table(1, 2)
    table.autofit = False
    table.columns[0].width = Inches(4)
    table.columns[1].width = Inches(2.5)
    
    c1 = table.cell(0, 0).paragraphs[0]
    c1.add_run("VNIVERSIDAD\nD SALAMANCA\n").bold = True
    c1.runs[0].font.size = Pt(14)
    c1.add_run("CAMPUS DE EXCELENCIA INTERNACIONAL").font.size = Pt(7)
    
    c2 = table.cell(0, 1).paragraphs[0]
    c2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    c2.add_run("FACULTAD DE MEDICINA\nDEPARTAMENTO DE OBSTETRICIA Y GINECOLOGÍA").bold = True
    c2.runs[0].font.size = Pt(9)
    
    doc.add_paragraph()
    
    # Datos alumno
    p = doc.add_paragraph()
    p.add_run("CURSO 3º ______ APELLIDOS ___________________________________ NOMBRE ______________________ DNI ___________").font.size = Pt(10)
    
    # Instrucciones
    doc.add_heading("EXAMEN DE GINECOLOGÍA", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    instr_table = doc.add_table(1, 1)
    instr_table.style = 'Table Grid'
    msg = ("Lea atentamente cada cuestión antes de responder.\n"
           "Dispone de 50 minutos para responder a 40 preguntas tipo test "
           "con 4 opciones, de las que sólo una es verdadera.\n"
           "Cada pregunta correcta suma 1 punto. Las respuestas incorrectas "
           "restan 0.25 puntos. Las preguntas no contestadas no suman ni "
           "restan puntuación.\n"
           "Para aprobar el examen será necesario obtener como mínimo una "
           "puntuación final de 5 puntos.\n"
           "La valoración final en las calificaciones será sobre 10 puntos.")
    instr_table.cell(0,0).text = msg
    
    doc.add_paragraph()
    
    # Preguntas
    for i, q in enumerate(questions):
        p = doc.add_paragraph()
        run = p.add_run(f"{i+1}. {q['question']}")
        run.bold = True
        
        # --- INSERCIÓN DE IMAGEN ---
        if 'image_data' in q and q['image_data'] is not None:
            try:
                # Convertir bytes a stream
                image_stream = io.BytesIO(q['image_data'])
                doc.add_picture(image_stream, width=Inches(3.5)) # Ancho estándar
                # Centrar imagen (truco para python-docx)
                last_p = doc.paragraphs[-1] 
                last_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            except:
                pass # Si la imagen falla, seguimos
        # ---------------------------

        letters = ["a)", "b)", "c)", "d)"]
        for j, opt in enumerate(q['options']):
            clean_opt = opt
            if opt.strip().lower().startswith("a)"): clean_opt = opt[2:].strip()
            elif opt.strip().lower().startswith("b)"): clean_opt = opt[2:].strip()
            elif opt.strip().lower().startswith("c)"): clean_opt = opt[2:].strip()
            elif opt.strip().lower().startswith("d)"): clean_opt = opt[2:].strip()
            
            doc.add_paragraph(f"{letters[j]} {clean_opt}")
        doc.add_paragraph()
        
    return doc

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Escudo_de_la_Universidad_de_Salamanca.svg/1200px-Escudo_de_la_Universidad_de_Salamanca.svg.png", width=80)
    st.title("Generador USAL - Pro")
    api_key = st.text_input("Clave API OpenAI", type="password")
    st.markdown("---")
    st.success("📸 **Soporte de Imágenes Activo:** Ahora puedes extraer ecografías de los PDF y pegarlas en las preguntas.")

# --- PESTAÑAS ---
tab_upload, tab_review, tab_exam = st.tabs([
    "1️⃣ Subir Material", 
    "2️⃣ Generar y Editar (con Imágenes)", 
    "3️⃣ Crear Examen Final"
])

# --- TAB 1: SUBIDA ---
with tab_upload:
    st.header("Paso 1: Carga de Archivos")
    uploaded = st.file_uploader("Sube PDFs/PPTs (Max 35)", type="pdf", accept_multiple_files=True)
    
    if uploaded:
        new_files = [f for f in uploaded if f.name not in st.session_state['files_processed_names']]
        
        if new_files:
            st.info("⏳ Procesando texto e imágenes...")
            bar = st.progress(0)
            for i, f in enumerate(new_files):
                # Extraemos texto e imágenes
                text, imgs, status = extract_content_robust(f)
                
                if text:
                    st.session_state['files_data'][f.name] = {
                        'text': text,
                        'images': imgs # Lista de bytes
                    }
                    st.session_state['files_processed_names'].append(f.name)
                else:
                    st.error(f"Error en {f.name}: {status}")
                bar.progress((i+1)/len(new_files))
            st.success("Procesamiento completado.")
            st.rerun()
            
    validos = list(st.session_state['files_data'].keys())
    if validos:
        st.success(f"✅ {len(validos)} temas cargados.")
        with st.expander("Detalles de archivos cargados"):
            for v in validos:
                n_imgs = len(st.session_state['files_data'][v]['images'])
                st.write(f"- **{v}**: {n_imgs} imágenes detectadas.")

# --- TAB 2: GENERAR Y EDITAR ---
with tab_review:
    st.header("Paso 2: Generación, Imágenes y Edición")
    
    temas_list = list(st.session_state['files_data'].keys())
    
    if not temas_list:
        st.warning("Sube archivos primero.")
    else:
        tema_actual = st.selectbox("Selecciona Tema:", temas_list)
        
        if tema_actual:
            st.divider()
            
            # CONFIG
            c1, c2, c3 = st.columns(3)
            na = c1.number_input("Tipo A", 0, 20, 2)
            nb = c2.number_input("Tipo B", 0, 20, 2)
            nc = c3.number_input("Tipo C (Casos)", 0, 20, 2)
            
            col_btn, col_info = st.columns([1, 2])
            btn_generate = col_btn.button(f"✨ Generar Preguntas", type="primary")
            
            if btn_generate:
                if not api_key:
                    st.error("Falta API Key.")
                else:
                    with st.spinner("Analizando texto y redactando casos clínicos..."):
                        text_src = st.session_state['files_data'][tema_actual]['text']
                        qs = call_openai_generator(api_key, text_src, na, nb, nc, tema_actual)
                        if qs:
                            st.session_state['questions_db'][tema_actual] = qs
                            st.success(f"¡Generadas {len(qs)} preguntas!")
                        else:
                            st.error("Error al generar.")

            # EDITOR
            if tema_actual in st.session_state['questions_db']:
                st.markdown("---")
                st.subheader(f"📝 Editor: {tema_actual}")
                
                # Imágenes disponibles del tema
                available_imgs = st.session_state['files_data'][tema_actual]['images']
                
                qs_editor = st.session_state['questions_db'][tema_actual]
                
                with st.form(key=f"form_{tema_actual}"):
                    updated_qs = []
                    for i, q in enumerate(qs_editor):
                        # Título y Tipo
                        tipo_color = "blue" if "Tipo C" in q.get('type', '') else "black"
                        st.markdown(f"<h4 style='color:{tipo_color}'>P{i+1} - {q.get('type', 'General')}</h4>", unsafe_allow_html=True)
                        
                        # ENUNCIADO
                        new_q_text = st.text_area("Enunciado:", value=q['question'], key=f"q_{tema_actual}_{i}", height=100)
                        
                        # --- SELECTOR DE IMAGEN ---
                        img_data_selected = q.get('image_data', None) # Recuperar si ya tenía una
                        
                        if available_imgs:
                            with st.expander(f"📸 Adjuntar Imagen (Disponibles: {len(available_imgs)})"):
                                # Mostramos galería pequeña
                                col_imgs = st.columns(5)
                                for idx_img, img_bytes in enumerate(available_imgs[:10]): # Limitamos preview a 10 por velocidad
                                    try:
                                        with col_imgs[idx_img % 5]:
                                            st.image(img_bytes, use_container_width=True)
                                            st.caption(f"Img {idx_img}")
                                    except: pass
                                
                                # Selector
                                prev_idx = q.get('image_index_local', -1)
                                sel_idx = st.number_input(f"Escribe el Nº de Img para asociar a P{i+1} (-1 = Ninguna)", 
                                                        min_value=-1, max_value=len(available_imgs)-1, value=prev_idx, key=f"img_sel_{tema_actual}_{i}")
                                
                                if sel_idx >= 0:
                                    img_data_selected = available_imgs[sel_idx]
                                    st.success(f"Imagen {sel_idx} asociada.")
                                else:
                                    img_data_selected = None
                        # --------------------------

                        # OPCIONES
                        c_ops1, c_ops2 = st.columns(2)
                        opts = q['options']
                        while len(opts) < 4: opts.append("") 
                        
                        o0 = c_ops1.text_input("a)", value=opts[0], key=f"o0_{tema_actual}_{i}")
                        o1 = c_ops2.text_input("b)", value=opts[1], key=f"o1_{tema_actual}_{i}")
                        o2 = c_ops1.text_input("c)", value=opts[2], key=f"o2_{tema_actual}_{i}")
                        o3 = c_ops2.text_input("d)", value=opts[3], key=f"o3_{tema_actual}_{i}")
                        
                        # RESPUESTA
                        c_ans, c_just = st.columns([1, 3])
                        idx_ans = c_ans.selectbox("Correcta:", [0,1,2,3], index=q['answer_index'], 
                                               format_func=lambda x: "a,b,c,d".split(',')[x], key=f"ans_{tema_actual}_{i}")
                        new_just = c_just.text_input("Justificación:", value=q.get('justification', ''), key=f"just_{tema_actual}_{i}")
                        
                        updated_qs.append({
                            "type": q.get('type'),
                            "question": new_q_text,
                            "options": [o0, o1, o2, o3],
                            "answer_index": idx_ans,
                            "justification": new_just,
                            "image_data": img_data_selected, # Guardamos los bytes de la imagen
                            "image_index_local": sel_idx if 'sel_idx' in locals() else -1
                        })
                        st.write("---")
                    
                    if st.form_submit_button("💾 Guardar Cambios"):
                        st.session_state['questions_db'][tema_actual] = updated_qs
                        st.success("Preguntas e Imágenes guardadas.")

# --- TAB 3: EXAMEN ---
with tab_exam:
    st.header("Paso 3: Examen Final")
    
    all_qs = []
    for t, qs in st.session_state['questions_db'].items():
        all_qs.extend(qs)
    
    if not all_qs:
        st.warning("No hay preguntas.")
    else:
        st.write(f"Total: **{len(all_qs)} preguntas**.")
        num = st.number_input("Nº Preguntas:", 1, 100, 40)
        
        if st.button("📄 Generar Word (con Imágenes)"):
            if len(all_qs) > num:
                sel = random.sample(all_qs, num)
            else:
                sel = all_qs
            
            random.shuffle(sel)
            doc = create_exam_docx(sel)
            bio = io.BytesIO()
            doc.save(bio)
            
            st.balloons()
            st.download_button("⬇️ Descargar Examen", bio.getvalue(), "Examen_Ginecologia_Final.docx")
