import streamlit as st
import openai
from pypdf import PdfReader
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import json
import io
import random

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Generador Exámenes Medicina - Ginecología", layout="wide")

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
    <style>
    .stExpander { border: 1px solid #ddd; border-radius: 5px; }
    .block-container { padding-top: 2rem; }
    </style>
""", unsafe_allow_html=True)

# --- GESTIÓN DEL ESTADO (SESSION STATE) ---
if 'questions_db' not in st.session_state:
    st.session_state['questions_db'] = {} 
if 'files_content' not in st.session_state:
    st.session_state['files_content'] = {}

# --- FUNCIONES AUXILIARES ---

def extract_text_from_pdf(file):
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        st.error(f"Error leyendo {file.name}: {e}")
        return ""

def create_word_header(doc, is_exam=False):
    # Simulación de cabecera institucional
    header_table = doc.add_table(rows=1, cols=2)
    header_table.autofit = False
    header_table.columns[0].width = Inches(4)
    header_table.columns[1].width = Inches(2.5)
    
    c1 = header_table.cell(0, 0)
    p1 = c1.paragraphs[0]
    r1 = p1.add_run("VNIVERSIDAD\nD SALAMANCA\n")
    r1.bold = True
    r1.font.size = Pt(14)
    p1.add_run("CAMPUS DE EXCELENCIA INTERNACIONAL").font.size = Pt(7)
    
    c2 = header_table.cell(0, 1)
    p2 = c2.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r2 = p2.add_run("FACULTAD DE MEDICINA\n")
    r2.bold = True
    r2.font.size = Pt(11)
    p2.add_run("DEPARTAMENTO DE OBSTETRICIA Y GINECOLOGÍA").font.size = Pt(9)
    
    doc.add_paragraph("") # Espacio

    if is_exam:
        # Datos del alumno
        p_info = doc.add_paragraph()
        p_info.add_run("CURSO _3º____\n").bold = True
        p_info.add_run("APELLIDOS _________________________________________________________________________\n")
        p_info.add_run("NOMBRE __________________________________________ DNI _______________________")
        
        doc.add_paragraph("") # Espacio
        
        # Título Examen
        tit = doc.add_heading("Ginecología", 0)
        tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Cuadro de instrucciones
        table_instr = doc.add_table(rows=1, cols=1)
        table_instr.style = 'Table Grid'
        cell_instr = table_instr.cell(0, 0)
        p_instr = cell_instr.paragraphs[0]
        text_instr = (
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
        p_instr.add_run(text_instr).font.size = Pt(10)
        doc.add_paragraph("")

def generate_questions_llm(api_key, text_content, num_a, num_b, num_c, topic_name):
    client = openai.OpenAI(api_key=api_key)
    
    prompt_system = """
    Eres un profesor universitario experto en Obstetricia y Ginecología (estilo Profesor Alcázar) para 4º de Medicina.
    Tu tarea es generar preguntas de examen tipo test rigurosas.
    Formato de salida OBLIGATORIO: JSON array.
    Estructura de cada objeto JSON:
    {
        "type": "A/B/C",
        "question": "Enunciado...",
        "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
        "answer_index": 0 (0 para A, 1 para B, 2 para C, 3 para D),
        "justification": "Explicación..."
    }
    """
    
    prompt_user = f"""
    Del siguiente texto sobre el tema '{topic_name}', genera exactamente:
    - {num_a} preguntas Tipo A (Conocimiento Directo).
    - {num_b} preguntas Tipo B (Conocimiento Integrado).
    - {num_c} preguntas Tipo C (Caso Clínico detallado).

    Texto base: {text_content[:20000]}...
    
    Asegúrate de:
    1. Que solo haya una respuesta correcta.
    2. Usar terminología médica precisa en español.
    3. Tipo C: Incluir datos clínicos realistas (IMC, paridad, eco).
    4. Distractores plausibles.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o", 
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        if "questions" in data:
            return data["questions"]
        return data 
        
    except Exception as e:
        # En caso de error, devolvemos lista vacía y avisamos en UI
        return []

# --- INTERFAZ SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Escudo_de_la_Universidad_de_Salamanca.svg/1200px-Escudo_de_la_Universidad_de_Salamanca.svg.png", width=100)
    st.title("Generador Exámenes Medicina")
    st.markdown("**Obstetricia y Ginecología**")
    api_key = st.text_input("OpenAI API Key", type="password")
    st.info("Introduce tu clave para empezar.")

# --- TABS PRINCIPALES ---
tab1, tab2, tab3 = st.tabs(["📂 Subir Temas (Max 35)", "✏️ Editar Preguntas", "🎓 Generar Examen Final"])

# --- TAB 1: SUBIDA Y GENERACIÓN ---
with tab1:
    st.header("1. Carga de Material Docente")
    st.markdown("Puedes subir hasta **35 archivos PDF** simultáneamente.")
    
    uploaded_files = st.file_uploader(
        "Arrastra tus archivos aquí", 
        type="pdf", 
        accept_multiple_files=True
    )
    
    # Validación de cantidad de archivos
    if uploaded_files:
        if len(uploaded_files) > 35:
            st.error(f"⚠️ Has subido {len(uploaded_files)} archivos. El límite máximo es 35. Por favor elimina algunos.")
        else:
            st.success(f"✅ {len(uploaded_files)} temas cargados correctamente.")
            st.divider()
            
            # --- CONFIGURACIÓN MASIVA (NUEVO) ---
            st.subheader("⚙️ Configuración de Preguntas")
            col_m1, col_m2, col_m3, col_m4 = st.columns([1,1,1,2])
            with col_m1:
                def_a = st.number_input("Tipo A (Defecto)", 0, 10, 2)
            with col_m2:
                def_b = st.number_input("Tipo B (Defecto)", 0, 10, 2)
            with col_m3:
                def_c = st.number_input("Tipo C (Defecto)", 0, 10, 1)
            with col_m4:
                st.write("") 
                st.write("") 
                apply_all = st.checkbox("Aplicar estos valores a TODOS los temas", value=True)

            st.write("---")

            # Procesar textos
            configs = {}
            # Contenedor con scroll para evitar página infinita si hay 35 temas
            with st.container(height=500):
                for uploaded_file in uploaded_files:
                    # Leer PDF si es nuevo
                    if uploaded_file.name not in st.session_state['files_content']:
                        with st.spinner(f"Indexando {uploaded_file.name}..."):
                            st.session_state['files_content'][uploaded_file.name] = extract_text_from_pdf(uploaded_file)
                    
                    # Interfaz de configuración individual
                    if apply_all:
                        configs[uploaded_file.name] = (def_a, def_b, def_c)
                        st.text(f"📄 {uploaded_file.name}: A={def_a}, B={def_b}, C={def_c} (Auto)")
                    else:
                        with st.expander(f"Configurar: {uploaded_file.name}", expanded=False):
                            c1, c2, c3 = st.columns(3)
                            na = c1.number_input(f"Tipo A - {uploaded_file.name}", min_value=0, value=def_a)
                            nb = c2.number_input(f"Tipo B - {uploaded_file.name}", min_value=0, value=def_b)
                            nc = c3.number_input(f"Tipo C - {uploaded_file.name}", min_value=0, value=def_c)
                            configs[uploaded_file.name] = (na, nb, nc)

            st.write("---")
            if st.button("🚀 Generar Preguntas con IA", type="primary"):
                if not api_key:
                    st.error("Falta la API Key.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total_files = len(uploaded_files)
                    
                    for idx, file in enumerate(uploaded_files):
                        fname = file.name
                        na, nb, nc = configs[fname]
                        
                        if (na + nb + nc) > 0:
                            status_text.text(f"Analizando tema {idx+1}/{total_files}: {fname}...")
                            text = st.session_state['files_content'][fname]
                            # Llamada a IA
                            qs = generate_questions_llm(api_key, text, na, nb, nc, fname)
                            if qs:
                                st.session_state['questions_db'][fname] = qs
                            else:
                                st.warning(f"No se pudieron generar preguntas para {fname} (posible error API o PDF vacío).")
                        
                        progress_bar.progress((idx + 1) / total_files)
                    
                    status_text.text("¡Proceso completado!")
                    st.balloons()
                    st.success("Preguntas generadas. Pasa a la pestaña 'Editar Preguntas'.")

# --- TAB 2: EDICIÓN ---
with tab2:
    st.header("2. Editor de Banco de Preguntas")
    
    if not st.session_state['questions_db']:
        st.info("Aún no hay preguntas. Sube temas en la pestaña anterior.")
    else:
        # Selector de tema
        temas_disponibles = list(st.session_state['questions_db'].keys())
        tema_sel = st.selectbox("Selecciona Tema a Editar:", temas_disponibles)
        
        if tema_sel:
            q_list = st.session_state['questions_db'][tema_sel]
            st.write(f"Total preguntas en este tema: {len(q_list)}")
            
            # Botón descarga individual
            doc_single = Document()
            create_word_header(doc_single)
            doc_single.add_heading(f"Banco: {tema_sel}", 1)
            
            for i, q in enumerate(q_list):
                with st.expander(f"P{i+1} ({q['type']}): {q['question'][:80]}..."):
                    with st.form(f"edit_{tema_sel}_{i}"):
                        new_q = st.text_area("Enunciado", q['question'])
                        c1, c2 = st.columns(2)
                        opts = q['options']
                        # Asegurar 4 opciones
                        while len(opts) < 4: opts.append("")
                        
                        o0 = c1.text_input("A)", opts[0])
                        o1 = c2.text_input("B)", opts[1])
                        o2 = c1.text_input("C)", opts[2])
                        o3 = c2.text_input("D)", opts[3])
                        
                        ans_idx = st.selectbox("Correcta", [0,1,2,3], index=q['answer_index'], 
                                             format_func=lambda x: ["A","B","C","D"][x])
                        just = st.text_area("Justificación", q.get('justification',''))
                        
                        if st.form_submit_button("Guardar Cambios"):
                            st.session_state['questions_db'][tema_sel][i].update({
                                'question': new_q,
                                'options': [o0, o1, o2, o3],
                                'answer_index': ans_idx,
                                'justification': just
                            })
                            st.success("Guardado")
                            st.rerun()

                # Añadir al word temporal
                p = doc_single.add_paragraph()
                p.add_run(f"{i+1}. {q['question']}").bold = True
                for op in q['options']: doc_single.add_paragraph(op, style='List Bullet')
                doc_single.add_paragraph(f"R: {['A','B','C','D'][q['answer_index']]}. {q.get('justification','')}")
            
            bio = io.BytesIO()
            doc_single.save(bio)
            st.download_button(f"📥 Descargar DOCX ({tema_sel})", bio.getvalue(), f"{tema_sel}.docx")

# --- TAB 3: GENERADOR EXAMEN ---
with tab3:
    st.header("3. Componer Examen Final (40 Preguntas)")
    
    total_q_db = sum(len(v) for v in st.session_state['questions_db'].values())
    
    if total_q_db == 0:
        st.warning("No hay preguntas en la base de datos.")
    else:
        st.write(f"Tienes **{total_q_db}** preguntas disponibles en total entre todos los temas.")
        
        # Modo de selección
        mode = st.radio("Método de selección:", ["Manual (Tema por tema)", "Automático (Reparto equitativo)"])
        
        exam_selection = {}
        count_sel = 0
        
        if mode == "Manual (Tema por tema)":
            cols = st.columns(3)
            idx = 0
            for tema, qs in st.session_state['questions_db'].items():
                with cols[idx % 3]:
                    n = st.number_input(f"{tema} (Disp: {len(qs)})", 0, len(qs), 0)
                    exam_selection[tema] = n
                    count_sel += n
                idx += 1
        else:
            # Automático
            if st.button("Distribuir 40 preguntas automáticamente"):
                temas = list(st.session_state['questions_db'].keys())
                n_temas = len(temas)
                base = 40 // n_temas
                remainder = 40 % n_temas
                
                for i, tema in enumerate(temas):
                    disponibles = len(st.session_state['questions_db'][tema])
                    to_take = base + (1 if i < remainder else 0)
                    # No pedir más de las que hay
                    real_take = min(to_take, disponibles)
                    exam_selection[tema] = real_take
                    
                # Guardar en session state para persistencia visual si fuera necesario, 
                # pero aquí lo procesamos directo para generar
                count_sel = sum(exam_selection.values())
                if count_sel < 40:
                    st.warning(f"Solo hay {count_sel} preguntas disponibles en total (se necesitaban 40).")
                else:
                    st.success(f"Reparto calculado: {count_sel} preguntas.")

        st.metric("Total Preguntas Examen", f"{count_sel} / 40")
        
        if count_sel != 40:
            st.error("El examen debe tener exactamente 40 preguntas.")
        else:
            if st.button("📄 GENERAR EXAMEN FINAL"):
                doc_final = Document()
                create_word_header(doc_final, is_exam=True)
                
                final_pool = []
                for tema, num in exam_selection.items():
                    if num > 0:
                        # Selección aleatoria de preguntas del tema
                        pool = st.session_state['questions_db'][tema]
                        selected = random.sample(pool, num)
                        final_pool.extend(selected)
                
                # Mezclar todo el examen
                random.shuffle(final_pool)
                
                # Escribir preguntas
                for i, q in enumerate(final_pool):
                    p = doc_final.add_paragraph()
                    p.add_run(f"{i+1}. {q['question']}").bold = True
                    
                    letters = ['a)', 'b)', 'c)', 'd)']
                    for j, opt in enumerate(q['options']):
                        clean_opt = opt.split(') ', 1)[-1] if ')' in opt[:4] else opt
                        doc_final.add_paragraph(f"{letters[j]} {clean_opt}")
                    
                    doc_final.add_paragraph("")
                
                # Hoja respuestas
                doc_final.add_page_break()
                doc_final.add_heading("PLANTILLA DE CORRECCIÓN", 1)
                table = doc_final.add_table(rows=1, cols=4)
                table.style = 'Table Grid'
                hdr = table.rows[0].cells
                hdr[0].text = "Nº"
                hdr[1].text = "Respuesta"
                hdr[2].text = "Nº"
                hdr[3].text = "Respuesta"
                
                # Llenar tabla en 2 columnas
                mitad = 20
                for i in range(mitad):
                    row = table.add_row().cells
                    # Col 1
                    q1 = final_pool[i]
                    row[0].text = str(i+1)
                    row[1].text = ['a','b','c','d'][q1['answer_index']]
                    
                    # Col 2
                    if i + mitad < 40:
                        q2 = final_pool[i+mitad]
                        row[2].text = str(i+mitad+1)
                        row[3].text = ['a','b','c','d'][q2['answer_index']]

                bio_fin = io.BytesIO()
                doc_final.save(bio_fin)
                st.download_button("⬇️ Descargar Examen (.docx)", bio_fin.getvalue(), "Examen_Final_USAL.docx")