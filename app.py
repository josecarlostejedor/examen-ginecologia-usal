import streamlit as st
import openai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json
import io
import random

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Generador Exámenes Ginecología", layout="wide")

st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px !important; }
    .status-ok { color: green; font-weight: bold; }
    .status-err { color: red; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- ESTADO DE LA SESIÓN (MEMORIA) ---
if 'files_content' not in st.session_state:
    st.session_state['files_content'] = {} # Texto extraído de los PDFs
if 'files_processed_names' not in st.session_state:
    st.session_state['files_processed_names'] = []
if 'questions_db' not in st.session_state:
    st.session_state['questions_db'] = {} # Preguntas generadas y revisadas

# --- FUNCIONES DE LÓGICA ---

def extract_text_robust(file):
    """Extrae texto de PDF o PDF-PPT evitando bloqueos"""
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
        
        # Validación de contenido mínimo
        if len(text.strip()) < 50:
            return None, "⚠️ PDF sin texto reconocible (posiblemente imágenes)"
        return text, "OK"
    except Exception as e:
        return None, f"❌ Error: {str(e)}"

def call_openai_generator(api_key, text, na, nb, nc, topic):
    """Llama a GPT-4o para crear las preguntas"""
    client = openai.OpenAI(api_key=api_key)
    
    system_prompt = """
    Actúa como Catedrático de Obstetricia y Ginecología (estilo Profesor Alcázar).
    Analiza el texto proporcionado (que puede venir de DIAPOSITIVAS esquemáticas) y genera preguntas de examen.
    
    IMPORTANTE: Devuelve SOLO un JSON válido con esta estructura:
    {
        "questions": [
            {
                "type": "A (Directa) / B (Integrada) / C (Caso Clínico)",
                "question": "Enunciado completo...",
                "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
                "answer_index": 0,
                "justification": "Explicación breve..."
            }
        ]
    }
    """
    
    user_prompt = f"""
    Tema: {topic}.
    Genera exactamente:
    - {na} preguntas Tipo A (Memorísticas/Definiciones).
    - {nb} preguntas Tipo B (Relación conceptos/Fisiopatología).
    - {nc} preguntas Tipo C (Casos Clínicos con edad, antecedentes y datos concretos).
    
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
    """Genera el Word final con formato oficial"""
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
    msg = ("Lea atentamente. 50 minutos. 40 preguntas. "
           "Acierto: +1. Fallo: -0.25. Blanco: 0. Aprobar: 5/10.")
    instr_table.cell(0,0).text = msg
    
    doc.add_paragraph()
    
    # Preguntas
    for i, q in enumerate(questions):
        p = doc.add_paragraph()
        p.add_run(f"{i+1}. {q['question']}").bold = True
        letters = ["a)", "b)", "c)", "d)"]
        for j, opt in enumerate(q['options']):
            clean_opt = opt.replace("a) ", "").replace("b) ", "").replace("c) ", "").replace("d) ", "")
            doc.add_paragraph(f"{letters[j]} {clean_opt}")
        doc.add_paragraph()
        
    return doc

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Escudo_de_la_Universidad_de_Salamanca.svg/1200px-Escudo_de_la_Universidad_de_Salamanca.svg.png", width=80)
    st.title("Generador USAL")
    api_key = st.text_input("Clave API OpenAI", type="password")

# --- PESTAÑAS (FLUJO DE TRABAJO) ---
tab_upload, tab_review, tab_exam = st.tabs([
    "1️⃣ Subir Archivos", 
    "2️⃣ Generar y Editar Preguntas", 
    "3️⃣ Crear Examen Final"
])

# --- TAB 1: SUBIDA ---
with tab_upload:
    st.header("Paso 1: Carga de Material")
    uploaded = st.file_uploader("Sube PDFs o PPTs exportados a PDF (Max 35)", type="pdf", accept_multiple_files=True)
    
    if uploaded:
        # Detectar nuevos
        new_files = [f for f in uploaded if f.name not in st.session_state['files_processed_names']]
        
        if new_files:
            st.info("⏳ Procesando texto de los nuevos archivos...")
            bar = st.progress(0)
            for i, f in enumerate(new_files):
                text, status = extract_text_robust(f)
                if text:
                    st.session_state['files_content'][f.name] = text
                    st.session_state['files_processed_names'].append(f.name)
                else:
                    st.error(f"Error en {f.name}: {status}")
                bar.progress((i+1)/len(new_files))
            st.success("Procesamiento completado.")
            st.rerun()
            
    # Mostrar resumen
    validos = list(st.session_state['files_content'].keys())
    if validos:
        st.success(f"✅ {len(validos)} temas listos para generar preguntas.")
        with st.expander("Ver lista de temas cargados"):
            st.write(validos)

# --- TAB 2: GENERAR Y EDITAR (EL CORAZÓN DE LA APP) ---
with tab_review:
    st.header("Paso 2: Generación y Revisión por Tema")
    
    temas_list = list(st.session_state['files_content'].keys())
    
    if not temas_list:
        st.warning("Primero sube archivos en la pestaña 1.")
    else:
        # Selector de tema
        tema_actual = st.selectbox("Selecciona el tema para trabajar:", temas_list)
        
        if tema_actual:
            st.divider()
            
            # --- ZONA DE CONFIGURACIÓN ---
            col1, col2, col3, col4 = st.columns([1,1,1,2])
            na = col1.number_input("Tipo A", 0, 10, 2)
            nb = col2.number_input("Tipo B", 0, 10, 2)
            nc = col3.number_input("Tipo C", 0, 10, 1)
            
            # Botón Generar
            btn_generate = col4.button(f"✨ Generar Preguntas para: {tema_actual}", type="primary")
            
            if btn_generate:
                if not api_key:
                    st.error("Falta la API Key.")
                else:
                    with st.spinner("La IA está leyendo las diapositivas y creando preguntas..."):
                        text_src = st.session_state['files_content'][tema_actual]
                        qs = call_openai_generator(api_key, text_src, na, nb, nc, tema_actual)
                        if qs:
                            st.session_state['questions_db'][tema_actual] = qs
                            st.success(f"¡Se han generado {len(qs)} preguntas! Revísalas abajo 👇")
                        else:
                            st.error("Error generando preguntas. Inténtalo de nuevo.")
            
            # --- ZONA DE EDICIÓN (VISIBLE SI HAY PREGUNTAS) ---
            if tema_actual in st.session_state['questions_db']:
                qs_editor = st.session_state['questions_db'][tema_actual]
                
                st.subheader(f"📝 Revisión: {tema_actual}")
                st.info("Edita aquí cualquier error. Dale a 'Guardar Correcciones' al final para confirmar los cambios.")
                
                # Formulario para editar todo el bloque del tema
                with st.form(key=f"form_{tema_actual}"):
                    updated_qs = []
                    
                    for i, q in enumerate(qs_editor):
                        st.markdown(f"**Pregunta {i+1} ({q.get('type','?')})**")
                        
                        # Enunciado
                        new_q_text = st.text_area("Enunciado:", value=q['question'], key=f"q_{tema_actual}_{i}", height=70)
                        
                        # Opciones
                        c_opt1, c_opt2 = st.columns(2)
                        opts = q['options']
                        while len(opts) < 4: opts.append("...") # Relleno seguridad
                        
                        o0 = c_opt1.text_input("A)", value=opts[0], key=f"o0_{tema_actual}_{i}")
                        o1 = c_opt2.text_input("B)", value=opts[1], key=f"o1_{tema_actual}_{i}")
                        o2 = c_opt1.text_input("C)", value=opts[2], key=f"o2_{tema_actual}_{i}")
                        o3 = c_opt2.text_input("D)", value=opts[3], key=f"o3_{tema_actual}_{i}")
                        
                        # Respuesta
                        idx_ans = st.selectbox("Correcta:", [0,1,2,3], index=q['answer_index'], 
                                               format_func=lambda x: "ABCD"[x], key=f"ans_{tema_actual}_{i}")
                        
                        st.markdown("---")
                        
                        # Reconstruir objeto
                        updated_qs.append({
                            "type": q.get('type', 'General'),
                            "question": new_q_text,
                            "options": [o0, o1, o2, o3],
                            "answer_index": idx_ans,
                            "justification": q.get('justification', '')
                        })
                    
                    # Botón de Guardado (Refrescar)
                    if st.form_submit_button("💾 Guardar Correcciones de este Tema"):
                        st.session_state['questions_db'][tema_actual] = updated_qs
                        st.success("✅ ¡Cambios guardados! Ya puedes pasar al siguiente tema o crear el examen.")
            else:
                st.info("Aún no hay preguntas generadas para este tema. Pulsa el botón de arriba.")

# --- TAB 3: EXAMEN FINAL ---
with tab_exam:
    st.header("Paso 3: Composición del Examen Final")
    
    total_preguntas = sum(len(qs) for qs in st.session_state['questions_db'].values())
    temas_con_preguntas = list(st.session_state['questions_db'].keys())
    
    if total_preguntas == 0:
        st.warning("Aún no has generado ni guardado ninguna pregunta. Ve a la Pestaña 2.")
    else:
        st.write(f"Tienes un banco de **{total_preguntas} preguntas** revisadas de **{len(temas_con_preguntas)} temas**.")
        
        target = st.number_input("Número de preguntas en el examen final:", value=40)
        
        if st.button("📄 Generar Examen Final (.docx)"):
            # Lógica de selección: Reparto proporcional simple
            final_pool = []
            
            # Juntamos todas
            all_qs = []
            for t in temas_con_preguntas:
                all_qs.extend(st.session_state['questions_db'][t])
            
            if len(all_qs) < target:
                st.warning(f"Solo tienes {len(all_qs)} preguntas disponibles. Se usarán todas.")
                final_pool = all_qs
            else:
                final_pool = random.sample(all_qs, target)
            
            # Crear documento
            doc = create_exam_docx(final_pool)
            bio = io.BytesIO()
            doc.save(bio)
            
            st.balloons()
            st.download_button(
                label="⬇️ Descargar Examen Oficial",
                data=bio.getvalue(),
                file_name="Examen_Ginecologia_Final.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
