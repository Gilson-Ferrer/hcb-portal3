import os
import io
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, session, flash, jsonify, send_file
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'asyncx_h4ck_loc4l_key')
DATABASE_URL = os.environ.get('DATABASE_URL')
TENANT_ID = os.environ.get('TENANT_ID', 'default_tenant')
INSTITUTION_NAME = os.environ.get('INSTITUTION_NAME', 'NOME INSTITUIÇÃO')
VOTING_LINK = os.environ.get('VOTING_FORM_LINK', 'https://link-pendente.asyncx.com.br')

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def get_event_details(cur):
    cur.execute('SELECT * FROM tenants WHERE id = %s AND is_active = TRUE', (TENANT_ID,))
    return cur.fetchone()

@app.route('/')
def index():
    if 'team_id' in session: 
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    name = request.form['name']
    password = request.form['password']
    
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        SELECT * FROM teams 
        WHERE name = %s AND password = %s AND tenant_id = %s
    ''', (name, password, TENANT_ID))
    team = cur.fetchone()
    
    if team:
        # =================================================================
        # BLOCKER DA LARGADA 
        # =================================================================
        event = get_event_details(cur)
        if event and event.get('start_time'):
            fuso_br = ZoneInfo('America/Sao_Paulo')
            agora = datetime.now(fuso_br)
            inicio_banco = event['start_time']
            if inicio_banco.tzinfo is None:
                inicio_banco = inicio_banco.replace(tzinfo=fuso_br)
            
            if agora < inicio_banco:
                data_formatada = inicio_banco.strftime('%d/%m às %H:%M')
                flash(f"Acesso Negado: A arena só será liberada dia {data_formatada}.", "danger")
                cur.close()
                conn.close()
                return redirect('/')

        session['team_id'] = team['id']
        session['team_name'] = team['name']
        session['tenant_id'] = TENANT_ID
        cur.close()
        conn.close()
        return redirect('/dashboard')

    cur.close()
    conn.close()
    flash("Credenciais Incorretas.", "danger")
    return redirect('/')

@app.route('/dashboard')
def dashboard():
    if 'team_id' not in session: 
        return redirect('/')
        
    conn = get_db()
    cur = conn.cursor()
    event = get_event_details(cur)
    if not event:
        cur.close()
        conn.close()
        return "Este evento não está ativo.", 404

    cur.execute('SELECT score, avatar_url, members FROM teams WHERE id = %s', (session['team_id'],))
    current_team = cur.fetchone()
    team_avatar = current_team['avatar_url'] if current_team and current_team['avatar_url'] else 'default.webp'
    team_members = current_team['members'] if current_team and current_team['members'] else ""
    cur.execute('SELECT id, name, score FROM teams WHERE tenant_id = %s ORDER BY score DESC, last_solve ASC', (TENANT_ID,))
    all_teams = cur.fetchall()

    cur.execute('''
        SELECT c.* FROM challenges c
        JOIN tenant_challenges tc ON c.id = tc.challenge_id
        WHERE tc.tenant_id = %s 
        ORDER BY c.id ASC
    ''', (TENANT_ID,))
    all_challenges = cur.fetchall()
    cur.execute('SELECT team_id, challenge_id FROM solves')
    all_solves = cur.fetchall()
    solves_matrix = {}
    for s in all_solves:
        if s['team_id'] not in solves_matrix: solves_matrix[s['team_id']] = set()
        solves_matrix[s['team_id']].add(s['challenge_id'])

    categories = ['Cyberdetective', 'Invasion', 'Defense', 'Code', 'Arcade', 'Hardware']
    challenges_by_category = {cat: [] for cat in categories}
    for c in all_challenges:
        cat = c.get('category', 'Cyberdetective')
        if cat in challenges_by_category:
            challenges_by_category[cat].append(c)

    cur.execute('SELECT challenge_id FROM solves WHERE team_id = %s', (session['team_id'],))
    solved_ids = [row['challenge_id'] for row in cur.fetchall()]
    cur.execute('SELECT challenge_id FROM hint_purchases WHERE team_id = %s', (session['team_id'],))
    purchased_ids = [row['challenge_id'] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html', 
                           event_name=event['name'],
                           all_teams=all_teams, 
                           all_challenges=all_challenges, 
                           solves_matrix=solves_matrix, 
                           challenges_by_category=challenges_by_category, 
                           solved_ids=solved_ids, 
                           purchased_ids=purchased_ids,
                           ranking=all_teams, 
                           team_avatar=team_avatar,
                           institution_name=INSTITUTION_NAME,
                           team_members=team_members,
                           voting_link=VOTING_LINK,
                           end_time=event['end_time'].isoformat())

@app.route('/leaderboard')
def leaderboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, score FROM teams WHERE tenant_id = %s ORDER BY score DESC, name ASC', (TENANT_ID,))
    all_teams = cur.fetchall()
    
    cur.execute('''
        SELECT c.* FROM challenges c
        JOIN tenant_challenges tc ON c.id = tc.challenge_id
        WHERE tc.tenant_id = %s 
        ORDER BY c.id ASC
    ''', (TENANT_ID,))
    all_challenges = cur.fetchall()
    
    cur.execute('SELECT team_id, challenge_id FROM solves')
    all_solves = cur.fetchall()
    solves_matrix = {}
    for s in all_solves:
        if s['team_id'] not in solves_matrix: solves_matrix[s['team_id']] = set()
        solves_matrix[s['team_id']].add(s['challenge_id'])

    cur.execute('SELECT start_time, end_time FROM tenants WHERE id = %s', (TENANT_ID,))
    event = cur.fetchone()
    
    cur.close()
    conn.close()

    start_time_iso = event.get('start_time').isoformat() if event and event.get('start_time') else ''
    end_time_iso = event.get('end_time').isoformat() if event and event.get('end_time') else ''
    
    return render_template('leaderboard_public.html', 
                           all_teams=all_teams, 
                           all_challenges=all_challenges, 
                           solves_matrix=solves_matrix,
                           start_time=start_time_iso,
                           end_time=end_time_iso)

@app.route('/hint/<int:id>')
def get_hint(id):
    if 'team_id' not in session: 
        return "Acesso negado", 403
        
    conn = get_db()
    cur = conn.cursor()
    
    event = get_event_details(cur)
    if not event or (event['end_time'] and datetime.now() > event['end_time']):
        cur.close()
        conn.close()
        return jsonify({"hint": "O evento terminou! Submissões trancadas.", "error": True})

    cur.execute('SELECT 1 FROM hint_purchases WHERE team_id = %s AND challenge_id = %s', 
                (session['team_id'], id))
    if cur.fetchone():
        cur.execute('SELECT hint FROM challenges WHERE id = %s', (id,))
        hint = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"hint": hint['hint']})

    cur.execute('UPDATE teams SET score = score - 25 WHERE id = %s', (session['team_id'],))
    cur.execute('INSERT INTO hint_purchases (team_id, challenge_id) VALUES (%s, %s)', 
                (session['team_id'], id))
    conn.commit()
    
    cur.execute('SELECT hint FROM challenges WHERE id = %s', (id,))
    hint = cur.fetchone()
    cur.close()
    conn.close()
    
    return jsonify({"hint": hint['hint']})

@app.route('/submit', methods=['POST'])
def submit():
    if 'team_id' not in session: 
        return redirect('/')

    conn = get_db()
    cur = conn.cursor()
    
    event = get_event_details(cur)
    
    # =========================================================================
    # BLOQUEIO TEMPORAL
    # =========================================================================
    if not event:
        cur.close()
        conn.close()
        flash("Evento não encontrado ou inativo.", "danger")
        return redirect('/dashboard')
        
    if event['end_time']:
        fuso_br = ZoneInfo('America/Sao_Paulo')
        agora = datetime.now(fuso_br)
        fim_banco = event['end_time']

        if fim_banco.tzinfo is None:
            fim_banco = fim_banco.replace(tzinfo=fuso_br)
            
        if agora > fim_banco:
            cur.close()
            conn.close()
            flash("O evento terminou! Submissões encerradas pelo servidor.", "danger")
            return redirect('/dashboard')
    # =========================================================================

    challenge_id = request.form.get('challenge_id')
    flag = request.form['flag'].strip()

    cur.execute('''
            SELECT c.* FROM challenges c
            JOIN tenant_challenges tc ON c.id = tc.challenge_id
            WHERE c.id = %s AND c.flag = %s AND tc.tenant_id = %s
    ''', (challenge_id, flag, TENANT_ID))
    challenge = cur.fetchone()
    
    if challenge:
        cur.execute('SELECT * FROM solves WHERE team_id = %s AND challenge_id = %s', 
                    (session['team_id'], challenge['id']))

        if not cur.fetchone():
            cur.execute('INSERT INTO solves (team_id, challenge_id) VALUES (%s, %s)', 
                        (session['team_id'], challenge['id']))

            fuso_br = ZoneInfo('America/Sao_Paulo')
            agora_solve = datetime.now(fuso_br)
            
            cur.execute('UPDATE teams SET score = score + %s, last_solve = %s WHERE id = %s', 
                        (challenge['points'], agora_solve, session['team_id']))
            conn.commit()
            flash("Flag correta! Pontuação atualizada.", "success")
    else:
        flash("Flag incorreta!", "danger")
        
    cur.close()
    conn.close()
    return redirect('/dashboard')

@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    if 'team_id' not in session:
        return jsonify({"success": False, "message": "Não autorizado"}), 403
    
    data = request.get_json()
    avatar_name = data.get('avatar_name')
    
    conn = get_db()
    cur = conn.cursor()

    cur.execute('UPDATE teams SET avatar_url = %s WHERE id = %s', 
                (avatar_name, session['team_id']))
    conn.commit()
    cur.close()
    conn.close()

    session['team_avatar'] = avatar_name    
    return jsonify({"success": True})


@app.route('/generate_certificate', methods=['POST'])
def generate_certificate():
    if 'team_id' not in session:
        return "Não autorizado", 403
        
    member_name = request.form.get('member_name')
    if not member_name:
        return "Nome do integrante inválido", 400

    conn = get_db()
    cur = conn.cursor()
    
    event = get_event_details(cur)
    cur.close()
    conn.close()
    
    if not event:
        return "Evento não configurado", 404

    # =========================================================================
    # BLOQUEIO TEMPORAL CERTIFICADO
    # =========================================================================

    fuso_br = ZoneInfo('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    end_time_banco = event['end_time'].replace(tzinfo=fuso_br)

    if agora < end_time_banco:
        return "Acesso Negado: A emissão do certificado só estará disponível após o encerramento oficial do evento.", 403

    event_title = event['name']                           
    inst_name = INSTITUTION_NAME                          
    
    end_date = event['end_time']
    start_date = end_date - timedelta(days=2) 
    
    # --- DICIONÁRIO DE TRADUÇÃO DOS MESES  ---

    meses_pt = {
            1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
            5: "maio", 6: "junho", 7: "julho", 8: "agosto",
            9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
        }

    month_name = meses_pt.get(end_date.month)
    year_name = end_date.strftime('%Y')

    date_range_str = f"no período de {start_date.day} a {end_date.day} de {month_name} de {year_name}"

    # =========================================================================
    # VERIFICAÇÃO/GERAÇÃO DO HASH ÚNICO E REGISTRO DE AUTENTICIDADE
    # =========================================================================
    conn = get_db()
    cur_cert = conn.cursor()
    
    try:
        cur_cert.execute("""
            SELECT hash_code FROM certificados_emitidos 
            WHERE member_name = %s AND event_name = %s
        """, (member_name, event_title))
        
        registro_existente = cur_cert.fetchone()
        
        if registro_existente:
            certificado_hash = registro_existente['hash_code']
        else:
            certificado_hash = uuid.uuid4().hex[:12].upper()
            data_emissao = datetime.now(fuso_br)
            
            cur_cert.execute("""
                INSERT INTO certificados_emitidos (hash_code, member_name, event_name, issue_date)
                VALUES (%s, %s, %s, %s)
            """, (certificado_hash, member_name, event_title, data_emissao))
            conn.commit()
            
    except Exception as e:
        conn.rollback()
        return f"Erro ao acessar ou registrar a credencial no banco de dados: {str(e)}", 500
    finally:
        cur_cert.close()
        conn.close()
    # =========================================================================
    # LEITURA DINÂMICA DAS DIMENSÕES DO CERTIFICADO
    # =========================================================================
    template_path = os.path.join(app.root_path, 'static', 'materials', 'certificate_background.pdf')
    
    try:
        existing_pdf = PdfReader(open(template_path, "rb"))
        page = existing_pdf.pages[0]
    except FileNotFoundError:
        return "Arquivo de template do certificado não encontrado no servidor.", 404

    bg_width = float(page.mediabox.width)
    bg_height = float(page.mediabox.height)
    center_x = bg_width / 2.0

    # =========================================================================
    # RENDERIZAÇÃO DA TIPOGRAFIA BASE
    # =========================================================================
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(bg_width, bg_height))
    
    # --- CONFIGURAÇÃO DO NOME DO ALUNO ---
    can.setFont("Helvetica-Bold", 20)                   
    can.setFillColorRGB(0, 0, 0)                          
    
    # Posição do nome
    pos_y_nome = bg_height * 0.55 
    can.drawCentredString(center_x, pos_y_nome, member_name.upper()) 
    
    # --- CONFIGURAÇÃO DO TEXTO PRINCIPAL ---
    can.setFont("Helvetica", 16)                     
    can.setFillColorRGB(0.2, 0.2, 0.2)                    

    texto_linha1 = f"Concluiu com êxito os desafios propostos pelo evento"
    texto_linha2 = f"{event_title}, realizada na instituição {inst_name},"
    texto_linha3 = f"{date_range_str}, cumprindo integralmente uma carga horária"
    texto_linha4 = f"de 12 horas de desafios práticos de Programação e Cibersegurança."

    pos_y_texto_inicial = bg_height * 0.50
    can.drawCentredString(center_x, pos_y_texto_inicial, texto_linha1)
    can.drawCentredString(center_x, pos_y_texto_inicial - 25, texto_linha2)
    can.drawCentredString(center_x, pos_y_texto_inicial - 50, texto_linha3)
    can.drawCentredString(center_x, pos_y_texto_inicial - 75, texto_linha4)
    
    # --- INJEÇÃO DA VALIDAÇÃO E HASH NO RODAPÉ ---
    can.setFont("Helvetica-Bold", 10)
    can.setFillColorRGB(0.4, 0.4, 0.4)
    
    pos_y_rodape = bg_height * 0.05
    url_validacao = f"Verifique a autenticidade deste documento em: https://asyncx.com.br/validador com código {certificado_hash}"
    
    can.drawCentredString(center_x, pos_y_rodape, url_validacao)
    
    can.save()
    packet.seek(0)

    # =========================================================================
    # COMPILAÇÃO DO ARQUIVO DISPARO DE DOWNLOAD
    # =========================================================================
    try:
        new_pdf = PdfReader(packet)
        output = PdfWriter()
        
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        
        response_stream = io.BytesIO()
        output.write(response_stream)
        response_stream.seek(0)
        
        filename = f"Certificado_AsyncX_{member_name.replace(' ', '_')}.pdf"
        
        return send_file(
            response_stream,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return f"Erro interno ao injetar metadados no certificado: {str(e)}", 500
    

@app.route('/sorteio')
def sorteio():

    return render_template('sorteio.html')

@app.route('/participar_sorteio', methods=['POST'])
def participar_sorteio():
    nome = request.form.get('nome')
    arroba = request.form.get('arroba')
    
    if not nome or not arroba:
        return jsonify({"status": "error", "message": "Preencha todos os campos."}), 400
        
    nome = nome.strip()
    arroba = "".join(arroba.split()).lower()

    if not arroba.startswith('@'):
        arroba = '@' + arroba

    conn = get_db()
    cur = conn.cursor()
    

    # VALIDAÇÃO DE TEMPO (48 horas)
    cur.execute('SELECT end_time FROM tenants WHERE id = %s', (TENANT_ID,))
    event = cur.fetchone()
    
    if event and event.get('end_time'):
        fuso_br = ZoneInfo('America/Sao_Paulo')
        agora = datetime.now(fuso_br)
        fim_banco = event['end_time']
        
        if fim_banco.tzinfo is None:
            fim_banco = fim_banco.replace(tzinfo=fuso_br)
        
        limite_sorteio = fim_banco + timedelta(hours=48)
        
        if agora > limite_sorteio:
            cur.close(); conn.close()
            return jsonify({"status": "error", "message": "Inscrições encerradas."}), 403

    # VALIDAÇÃO UNICIDADE DO @
    cur.execute('SELECT id FROM sorteio_participantes WHERE tenant_id = %s AND arroba = %s', (TENANT_ID, arroba))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"status": "error", "message": f"O perfil {arroba} já está inscrito!"}), 409

    cur.execute('''
        INSERT INTO sorteio_participantes (tenant_id, nome, arroba) 
        VALUES (%s, %s, %s)
    ''', (TENANT_ID, nome, arroba))
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({"status": "success"})


@app.route('/api/get_sorteio_lista')
def get_sorteio_lista():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT nome, arroba FROM sorteio_participantes WHERE tenant_id = %s ORDER BY RANDOM()', (TENANT_ID,))
    participantes = cur.fetchall()
    cur.close()
    conn.close()

    lista_formatada = [f"{p['nome']} ({p['arroba']})" for p in participantes]
    return jsonify(lista_formatada)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)