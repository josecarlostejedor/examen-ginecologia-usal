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
st.set_page_config(page_title="Generador Exámenes Ginecología - Nivel Clínico", layout="wide")

st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px !important; font-family: 'Arial'; }
    .status-ok { color: green; font-weight: bold; }
    .status-err { color: red; font-weight: bold; }
    div[data-testid="stExpander"] div[role="button"] p {
        font-size: 16px;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- ESTADO DE LA SESIÓN ---
if 'files_content' not in st.session_state:
    st.session_state['files_content'] = {}
if 'files_processed_names' not in st.session_state:
    st.session_state['files_processed_names'] = []
if 'questions_db' not in st.session_state:
    st.session_state['questions_db'] = {}

# --- FUNCIONES DE LÓGICA ---

def extract_text_robust(file):
    """Extrae texto de PDF o PDF-PPT evitando bloqueos"""
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
        
        if len(text.strip()) < 50:
            return None, "⚠️ PDF sin texto reconocible (posiblemente imágenes)"
        return text, "OK"
    except Exception as e:
        return None, f"❌ Error: {str(e)}"

def call_openai_generator(api_key, text, na, nb, nc, topic):
    """Llama a GPT-4o con un PROMPT AVANZADO MÉDICO"""
    client = openai.OpenAI(api_key=api_key)
    
    # --- AQUÍ ESTÁ LA MAGIA DEL PROMPT MÉDICO ---
    system_prompt = """
    Eres un Catedrático de Obstetricia y Ginecología con experiencia clínica hospitalaria. 
    Tu objetivo es crear preguntas de examen para alumnos de 4º de Medicina.
    
    INSTRUCCIONES ESPECÍFICAS POR TIPO:
    
    1. TIPO A (Conocimiento Directo): Definiciones, clasificaciones o datos epidemiológicos.
    2. TIPO B (Integrado): Fisiopatología, relación entre farmacología y clínica, etc.
    
    3. TIPO C (CASOS CLÍNICOS - MUY IMPORTANTE):
       Debes redactar "Viñetas Clínicas" completas y realistas.
       NO hagas preguntas simples como "¿Qué tiene la paciente?".
       
       Estructura OBLIGATORIA para Tipo C:
       - PERFIL: Edad, Paridad (GnPn), Antecedentes relevantes (fumadora, cirugías, FUM).
       - ENFERMEDAD ACTUAL: Motivo de consulta, cronología, tipo de dolor/sangrado.
       - EXPLORACIÓN: Constantes vitales (TA, FC, Tª -> CRUCIAL para decidir estabilidad), hallazgos a la especuloscopia y tacto bimanual.
       - PRUEBAS: Descripción técnica de la imagen ecográfica (ej: "imagen en vidrio esmerilado", "línea endometrial de 14mm", "saco gestacional sin embrión", "líquido libre en Douglas") o analítica (Beta-HCG, Hb).
       
       LA PREGUNTA debe requerir INTEGRAR estos datos para decidir la ACTITUD o el DIAGNÓSTICO más probable entre distractores plausibles.
       Ejemplo de estilo: "Ante la inestabilidad hemodinámica y el líquido libre, ¿cuál es la actitud inmediata?"
    
    FORMATO DE SALIDA (JSON):
    {
        "questions": [
            {
                "type": "Tipo A" o "Tipo B" o "Tipo C",
                "question": "Enunciado completo...",
                "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
                "answer_index": 0,
                "justification": "Justificación clínica detallada..."
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
    
    TEXTO BASE DEL TEMA (Diapositivas/Manual):
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
        
        letters = ["a)", "b)", "c)", "d)"]
        for j, opt in enumerate(q['options']):
            # Limpieza básica por si la IA pone letras dobles
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
    st.info("💡 **Novedad:** Ahora los casos clínicos (Tipo C) incluyen constantes vitales y datos de exploración complejos.")

# --- PESTAÑAS (FLUJO DE TRABAJO) ---
tab_upload, tab_review, tab_exam = st.tabs([
    "1️⃣ Subir Material Docente", 
    "2️⃣ Generar y Editar Preguntas", 
    "3️⃣ Crear Examen Final"
])

# --- TAB 1: SUBIDA ---
with tab_upload:
    st.header("Paso 1: Carga de Presentaciones/PDFs")
    uploaded = st.file_uploader("Sube los archivos (Max 35)", type="pdf", accept_multiple_files=True)
    
    if uploaded:
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
            
    validos = list(st.session_state['files_content'].keys())
    if validos:
        st.success(f"✅ {len(validos)} temas cargados correctamente.")
        with st.expander("Ver lista de archivos cargados"):
            for v in validos:
                st.text(f"- {v}")

# --- TAB 2: GENERAR Y EDITAR ---
with tab_review:
    st.header("Paso 2: Generación y Edición Docente")
    
    temas_list = list(st.session_state['files_content'].keys())
    
    if not temas_list:
        st.warning("Por favor, sube archivos en la Pestaña 1 primero.")
    else:
        tema_actual = st.selectbox("Selecciona el tema para trabajar:", temas_list)
        
        if tema_actual:
            st.divider()
            
            # CONFIGURACIÓN
            st.subheader(f"Configuración para: {tema_actual}")
            
            # --- AQUÍ ESTABA EL ERROR ANTERIORMENTE, YA CORREGIDO ---
            c1, c2, c3 = st.columns(3)
            na = c1.number_input("Nº Preguntas Tipo A (Directas)", 0, 20, 2)
            nb = c2.number_input("Nº Preguntas Tipo B (Integradas)", 0, 20, 2)
            nc = c3.number_input("Nº Preguntas Tipo C (Casos Clínicos)", 0, 20, 2)
            # ---------------------------------------------------------
            
            col_btn, col_info = st.columns([1, 2])
            btn_generate = col_btn.button(f"✨ Generar Preguntas", type="primary")
            
            if btn_generate:
                if not api_key:
                    st.error("⚠️ Falta la API Key en la barra lateral.")
                else:
                    with st.spinner("🧠 Analizando caso clínico y redactando viñetas..."):
                        text_src = st.session_state['files_content'][tema_actual]
                        qs = call_openai_generator(api_key, text_src, na, nb, nc, tema_actual)
                        if qs:
                            st.session_state['questions_db'][tema_actual] = qs
                            st.success(f"¡Generadas {len(qs)} preguntas!")
                        else:
                            st.error("No se pudieron generar preguntas. Revisa el archivo o la API Key.")

            # EDICIÓN
            if tema_actual in st.session_state['questions_db']:
                st.markdown("---")
                st.subheader(f"📝 Editor de Preguntas: {tema_actual}")
                
                qs_editor = st.session_state['questions_db'][tema_actual]
                
                with st.form(key=f"form_{tema_actual}"):
                    updated_qs = []
                    for i, q in enumerate(qs_editor):
                        # Visualización clara del tipo
                        tipo_color = "blue" if "Tipo C" in q.get('type', '') else "black"
                        st.markdown(f"<h4 style='color:{tipo_color}'>Pregunta {i+1} - {q.get('type', 'General')}</h4>", unsafe_allow_html=True)
                        
                        # Enunciado grande para casos clínicos
                        height_area = 150 if "Tipo C" in q.get('type', '') else 80
                        new_q_text = st.text_area("Enunciado:", value=q['question'], key=f"q_{tema_actual}_{i}", height=height_area)
                        
                        # Opciones
                        opts = q['options']
                        while len(opts) < 4: opts.append("") 
                        
                        col_ops1, col_ops2 = st.columns(2)
                        o0 = col_ops1.text_input("a)", value=opts[0], key=f"o0_{tema_actual}_{i}")
                        o1 = col_ops2.text_input("b)", value=opts[1], key=f"o1_{tema_actual}_{i}")
                        o2 = col_ops1.text_input("c)", value=opts[2], key=f"o2_{tema_actual}_{i}")
                        o3 = col_ops2.text_input("d)", value=opts[3], key=f"o3_{tema_actual}_{i}")
                        
                        # Respuesta y Justificación
                        c_ans, c_just = st.columns([1, 3])
                        idx_ans = c_ans.selectbox("Opción Correcta:", [0,1,2,3], index=q['answer_index'], 
                                               format_func=lambda x: "a,b,c,d".split(',')[x], key=f"ans_{tema_actual}_{i}")
                        new_just = c_just.text_input("Justificación (Interna):", value=q.get('justification', ''), key=f"just_{tema_actual}_{i}")
                        
                        updated_qs.append({
                            "type": q.get('type'),
                            "question": new_q_text,
                            "options": [o0, o1, o2, o3],
                            "answer_index": idx_ans,
                            "justification": new_just
                        })
                        st.write("---")
                    
                    if st.form_submit_button("💾 Guardar Cambios y Refrescar"):
                        st.session_state['questions_db'][tema_actual] = updated_qs
                        st.success("Preguntas actualizadas correctamente.")

# --- TAB 3: EXAMEN FINAL ---
with tab_exam:
    st.header("Paso 3: Generar Documento de Examen")
    
    all_questions = []
    temas_incluidos = []
    
    for t, qs in st.session_state['questions_db'].items():
        all_questions.extend(qs)
        temas_incluidos.append(t)
    
    total_disponibles = len(all_questions)
    
    if total_disponibles == 0:
        st.warning("No hay preguntas listas. Ve al Paso 2.")
    else:
        st.write(f"Tienes un banco de **{total_disponibles} preguntas** provenientes de:")
        st.caption(", ".join(temas_incluidos))
        
        num_preguntas = st.number_input("Número de preguntas para el examen:", min_value=1, max_value=100, value=40)
        
        if st.button("📄 Descargar Examen (.docx)"):
            # Selección aleatoria si hay más de las necesarias
            if len(all_questions) > num_preguntas:
                seleccionadas = random.sample(all_questions, num_preguntas)
            else:
                seleccionadas = all_questions
                st.warning(f"Solo había {len(all_questions)} preguntas, se han puesto todas.")
            
            # Mezclar orden
            random.shuffle(seleccionadas)
            
            # Generar Word
            doc = create_exam_docx(seleccionadas)
            bio = io.BytesIO()
            doc.save(bio)
            
            st.balloons()
            st.download_button(
                label="⬇️ Descargar Archivo Word",
                data=bio.getvalue(),
                file_name="Examen_Ginecologia_Final.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
