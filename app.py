import streamlit as st
import openai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json
import io
import random
from PIL import Image

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Generador Exámenes USAL - Estilo MIR", layout="wide")

st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px !important; font-family: 'Arial'; }
    .status-ok { color: green; font-weight: bold; }
    .justification-box {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        margin-top: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- ESTADO DE LA SESIÓN ---
if 'files_data' not in st.session_state:
    st.session_state['files_data'] = {} 
if 'files_processed_names' not in st.session_state:
    st.session_state['files_processed_names'] = []
if 'questions_db' not in st.session_state:
    st.session_state['questions_db'] = {}
if 'final_exam_questions' not in st.session_state:
    st.session_state['final_exam_questions'] = []

# --- FUNCIONES DE LÓGICA ---

def extract_content_robust(file):
    """Extrae Texto e IMÁGENES de PDF/PPT"""
    try:
        reader = PdfReader(file)
        text = ""
        extracted_images = []
        
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
            try:
                for img_file_obj in page.images:
                    extracted_images.append(img_file_obj.data)
            except: pass
        
        if len(text.strip()) < 50:
            return None, [], "⚠️ PDF sin texto reconocible"
            
        return text, extracted_images, "OK"
    except Exception as e:
        return None, [], f"❌ Error: {str(e)}"

def call_openai_generator(api_key, text, na, nb, nc, topic):
    client = openai.OpenAI(api_key=api_key)
    
    # --- PROMPT ACTUALIZADO: ESTILO MIR NARRATIVO ---
    system_prompt = """
    Eres un Catedrático de Obstetricia y Ginecología experto en redacción de preguntas tipo MIR (Médico Interno Residente).
    
    OBJETIVO:
    Generar preguntas de alta calidad técnica, discriminatorias y ajustadas a la realidad clínica.
    
    INSTRUCCIONES POR TIPO:
    
    1. TIPO A (Conocimiento Directo): Definiciones, anatomía, clasificaciones o epidemiología. Directas y claras.
    
    2. TIPO B (Conocimiento Integrado): Relaciona fisiopatología con clínica o farmacología.
    
    3. TIPO C (CASOS CLÍNICOS - ESTILO MIR):
       - FORMATO: Redacta un ÚNICO PÁRRAFO narrativo y cohesivo. NO uses listas, guiones ni apartados (Nada de "A) Antecedentes...").
       - CONTENIDO: Integra el perfil de la paciente (edad, paridad), el motivo de consulta, la exploración y las pruebas complementarias de forma fluida.
       - SELECCIÓN DE DATOS: Incluye SOLO los datos relevantes (positivos y negativos pertinentes) para el diagnóstico o diagnóstico diferencial.
         * Ejemplo de irrelevante: No menciones el color de ojos o antecedentes sin relación.
         * Ejemplo de relevante: En una preeclampsia, menciona explícitamente la TA y la proteinuria/plaquetas. En un ectópico, menciona la estabilidad hemodinámica.
       - REALISMO: Usa valores numéricos concretos (ej: "Beta-HCG de 1500 UI/L", "TA 80/50 mmHg", "Hb 9 g/dL") en lugar de "elevado" o "bajo".
       - IMÁGENES: Si el caso se beneficia de una imagen (ecografía, mamografía), redáctalo asumiendo que el alumno la ve (ej: "...en la ecografía se observa la siguiente imagen:").
    
    FORMATO JSON OBLIGATORIO:
    {
        "questions": [
            {
                "type": "Tipo A/B/C",
                "question": "Texto de la pregunta...",
                "options": ["a) ...", "b) ...", "c) ...", "d) ..."],
                "answer_index": 0,
                "justification": "Explicación detallada del porqué de la respuesta correcta y el descarte de las otras."
            }
        ]
    }
    """
    
    user_prompt = f"Tema: {topic}. Genera rigurosamente: {na} preguntas Tipo A, {nb} preguntas Tipo B, {nc} preguntas Tipo C (Estilo MIR).\nTEXTO BASE:\n{text[:25000]}..."

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"}, temperature=0.7
        )
        return json.loads(response.choices[0].message.content).get("questions", [])
    except Exception as e:
        st.error(f"Error OpenAI: {e}")
        return []

def create_header(doc, is_exam=False):
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

    if is_exam:
        # Datos Alumno
        p = doc.add_paragraph()
        p.add_run("CURSO _3º____\n").bold = True
        p.add_run("APELLIDOS _________________________________________________________________________\n")
        p.add_run("NOMBRE __________________________________________ DNI _______________________")
        doc.add_paragraph("")

        # Título
        tit = doc.add_heading("Ginecología", 0)
        tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Cuadro de Instrucciones (TEXTO COMPLETO)
        t = doc.add_table(1, 1)
        t.style = 'Table Grid'
        
        full_text = (
            "Lea atentamente cada cuestión antes de responder.\n"
            "Dispone de 50 minutos para responder a 40 preguntas tipo test "
            "con 4 opciones, de las que sólo una es verdadera.\n"
            "Cada pregunta correcta suma 1 punto. Las respuestas incorrectas "
            "restan 0.25 puntos. Las preguntas no contestadas no suman ni "
            "restan puntuación.\n"
            "Para aprobar el examen será necesario obtener como mínimo una "
            "puntuación final de 5 puntos.\n"
            "La valoración final en las calificaciones será sobre 10 puntos."
        )
        
        cell = t.cell(0,0)
        p_instr = cell.paragraphs[0]
        run_instr = p_instr.add_run(full_text)
        run_instr.font.size = Pt(10)
        doc.add_paragraph("")

def add_image_to_doc(doc, q):
    if 'image_data' in q and q['image_data'] is not None:
        try:
            image_stream = io.BytesIO(q['image_data'])
            doc.add_picture(image_stream, width=Inches(3.0))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except: pass

def create_exam_docx(questions):
    doc = Document()
    create_header(doc, is_exam=True)
    
    for i, q in enumerate(questions):
        p = doc.add_paragraph()
        p.add_run(f"{i+1}. {q['question']}").bold = True
        add_image_to_doc(doc, q)
        
        letters = ["a)", "b)", "c)", "d)"]
        for j, opt in enumerate(q['options']):
            clean = opt.split(') ', 1)[-1] if ')' in opt[:4] else opt
            doc.add_paragraph(f"{letters[j]} {clean}")
        doc.add_paragraph()
    return doc

def create_solution_docx(questions):
    doc = Document()
    create_header(doc, is_exam=False)
    doc.add_heading("SOLUCIONARIO DEL EXAMEN", 0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("Este documento es confidencial para uso del profesorado.\n")
    
    for i, q in enumerate(questions):
        # Enunciado
        p = doc.add_paragraph()
        p.add_run(f"PREGUNTA {i+1}: ").bold = True
        p.add_run(q['question'])
        add_image_to_doc(doc, q)
        
        # Opciones
        letters = ["a)", "b)", "c)", "d)"]
        for j, opt in enumerate(q['options']):
            clean = opt.split(') ', 1)[-1] if ')' in opt[:4] else opt
            p_opt = doc.add_paragraph()
            run_opt = p_opt.add_run(f"{letters[j]} {clean}")
            if j == q['answer_index']:
                run_opt.bold = True
                run_opt.font.color.rgb = RGBColor(0, 128, 0) # Verde
                p_opt.add_run("  [CORRECTA]").bold = True
        
        # Justificación
        p_just = doc.add_paragraph()
        p_just.paragraph_format.left_indent = Inches(0.5)
        run_j = p_just.add_run(f"Justificación: {q.get('justification', 'Sin justificación.')}")
        run_j.italic = True
        run_j.font.color.rgb = RGBColor(100, 100, 100) # Gris
        
        doc.add_paragraph("-" * 30)
        
    return doc

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Escudo_de_la_Universidad_de_Salamanca.svg/1200px-Escudo_de_la_Universidad_de_Salamanca.svg.png", width=80)
    st.title("Generador USAL")
    api_key = st.text_input("Clave API OpenAI", type="password")

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs([
    "1️⃣ Subir Material", 
    "2️⃣ Editor + Imágenes", 
    "3️⃣ Componer Examen",
    "4️⃣ Solucionario"
])

# --- TAB 1: SUBIDA ---
with tab1:
    st.header("Carga de Archivos")
    uploaded = st.file_uploader("Sube PDFs/PPTs", type="pdf", accept_multiple_files=True)
    if uploaded:
        new_files = [f for f in uploaded if f.name not in st.session_state['files_processed_names']]
        if new_files:
            bar = st.progress(0)
            for i, f in enumerate(new_files):
                text, imgs, status = extract_content_robust(f)
                if text:
                    st.session_state['files_data'][f.name] = {'text': text, 'images': imgs}
                    st.session_state['files_processed_names'].append(f.name)
                bar.progress((i+1)/len(new_files))
            st.rerun()
    st.success(f"Archivos cargados: {len(st.session_state['files_data'])}")

# --- TAB 2: EDITOR ---
with tab2:
    st.header("Generación y Edición")
    temas = list(st.session_state['files_data'].keys())
    if not temas: st.warning("Sube archivos primero."); st.stop()
    
    tema_sel = st.selectbox("Tema:", temas)
    if tema_sel:
        st.divider()
        c1, c2, c3, c4 = st.columns([1,1,1,2])
        # LÍMITE DE 40 PREGUNTAS
        na = c1.number_input("A (Directas)", 0, 40, 2)
        nb = c2.number_input("B (Integradas)", 0, 40, 2)
        nc = c3.number_input("C (Casos)", 0, 40, 1)
        
        if c4.button("✨ Generar Preguntas", type="primary"):
            if not api_key: st.error("Falta API Key"); st.stop()
            with st.spinner("Generando preguntas Estilo MIR..."):
                qs = call_openai_generator(api_key, st.session_state['files_data'][tema_sel]['text'], na, nb, nc, tema_sel)
                if qs: st.session_state['questions_db'][tema_sel] = qs; st.success("¡Hecho!")

        if tema_sel in st.session_state['questions_db']:
            qs = st.session_state['questions_db'][tema_sel]
            imgs_pdf = st.session_state['files_data'][tema_sel]['images']
            
            with st.form(f"form_{tema_sel}"):
                updated_qs = []
                for i, q in enumerate(qs):
                    color = "blue" if "Tipo C" in q.get('type','') else "black"
                    st.markdown(f"<h4 style='color:{color}'>P{i+1} - {q.get('type')}</h4>", unsafe_allow_html=True)
                    new_q = st.text_area("Enunciado", q['question'], key=f"q_{i}", height=150)
                    
                    # --- GESTIÓN DE IMÁGENES ---
                    col_img_prev, col_img_ctrl = st.columns([1, 2])
                    current_img_data = q.get('image_data', None)
                    
                    with col_img_prev:
                        if current_img_data:
                            st.image(current_img_data, width=200, caption="Imagen Actual")
                        else:
                            st.info("Sin imagen")

                    with col_img_ctrl:
                        source = st.radio("Fuente de Imagen:", ["Ninguna", "Del PDF", "Subir Archivo"], key=f"src_{i}", horizontal=True)
                        final_img_data = None
                        
                        if source == "Del PDF":
                            if imgs_pdf:
                                idx = st.number_input(f"Índice Imagen PDF (0-{len(imgs_pdf)-1})", 0, len(imgs_pdf)-1, 0, key=f"idx_{i}")
                                final_img_data = imgs_pdf[idx]
                                st.image(final_img_data, width=100)
                            else:
                                st.warning("Este PDF no tiene imágenes.")
                        elif source == "Subir Archivo":
                            uploaded_img = st.file_uploader("Sube tu imagen (PNG/JPG)", type=['png','jpg','jpeg'], key=f"upl_{i}")
                            if uploaded_img:
                                final_img_data = uploaded_img.getvalue()
                                st.image(final_img_data, width=100)
                        
                        if source != "Ninguna" and final_img_data is None and current_img_data is not None:
                             pass 
                        if source == "Ninguna": final_img_data = None
                    # ---------------------------

                    c_ops1, c_ops2 = st.columns(2)
                    opts = q['options']; 
                    while len(opts)<4: opts.append("")
                    o0 = c_ops1.text_input("a)", opts[0], key=f"o0_{i}"); o1 = c_ops2.text_input("b)", opts[1], key=f"o1_{i}")
                    o2 = c_ops1.text_input("c)", opts[2], key=f"o2_{i}"); o3 = c_ops2.text_input("d)", opts[3], key=f"o3_{i}")
